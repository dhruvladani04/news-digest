"""
Dedupe and ranking.

Two stories are "the same story" if they share a canonical URL, or if their
titles overlap enough after normalisation. When several outlets carry the same
story that is strong evidence it matters, so duplicates are merged into one
entry and the merge count becomes a ranking signal.
"""

import re
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

# ---------------------------------------------------------------- ranking knobs

TIER_WEIGHT = {1: 6.0, 2: 3.5, 3: 1.5}

# Half-life in hours for the recency decay. A 12h-old story scores half the
# freshness points of a brand new one.
RECENCY_HALF_LIFE_H = 12.0
RECENCY_MAX = 5.0

# Each *additional* outlet carrying the story. Deliberately steep: cross-outlet
# corroboration is the single best "is this actually big" signal we have.
CORROBORATION_BONUS = 4.0
CORROBORATION_CAP = 16.0

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "of", "in", "on", "at", "to", "for",
    "with", "from", "by", "as", "is", "are", "was", "were", "be", "been", "it",
    "its", "this", "that", "these", "those", "will", "would", "can", "could",
    "has", "have", "had", "not", "no", "new", "says", "say", "said", "after",
    "over", "into", "amid", "how", "why", "what", "who", "his", "her", "their",
}

# Keyword boosts. Sector -> [(regex, points)]
KEYWORD_BOOSTS = {
    "ai_tech": [
        (r"\b(gpt|claude|gemini|llama|mistral|deepseek|qwen)\b", 3.0),
        (r"\b(open ?ai|anthropic|deepmind|nvidia|tsmc)\b", 2.5),
        (r"\b(benchmark|state[- ]of[- ]the[- ]art|breakthrough|releases?|launch(es|ed)?)\b", 1.5),
        (r"\b(chip|semiconductor|gpu|data ?cent(er|re))\b", 1.5),
        (r"\b(acqui(re|res|red|sition)|funding|ipo)\b", 1.5),
    ],
    "finance": [
        (r"\b(fed|federal reserve|rbi|ecb|boj|central bank)\b", 3.0),
        (r"\b(rate (cut|hike|decision)|inflation|cpi|gdp|recession)\b", 2.5),
        (r"\b(earnings|guidance|profit|revenue|beats?|misses?)\b", 1.5),
        (r"\b(nifty|sensex|s&p|nasdaq|dow|bond yield)\b", 1.5),
        (r"\b(bitcoin|ethereum|crypto)\b", 1.0),
    ],
    "geopolitics": [
        (r"\b(sanction|treaty|ceasefire|summit|tariff|embargo)\b", 3.0),
        (r"\b(strike|invasion|offensive|missile|escalat)\w*", 2.5),
        (r"\b(election|coup|referendum|parliament)\b", 2.0),
        (r"\b(china|russia|ukraine|israel|iran|india|taiwan|nato)\b", 1.5),
    ],
    "frontier": [
        (r"\b(series [a-e]|seed round|raises?|valuation|unicorn)\b", 3.0),
        (r"\b(study|research|discover(y|ed)|trial|published in)\b", 2.0),
        (r"\b(solar|battery|nuclear|fusion|grid|renewable|emissions)\b", 2.0),
        (r"\b(launch|orbit|mars|telescope|spacecraft)\b", 1.5),
    ],
    "entertainment": [
        # franchise focus -- these surface first, as requested
        (r"\b(marvel|mcu|avengers|spider[- ]?man|x[- ]men|deadpool|thor|loki|"
         r"fantastic four|doctor strange|wakanda|daredevil|punisher)\b", 5.0),
        (r"\b(dc(u|eu)?|batman|superman|wonder woman|joker|justice league|"
         r"james gunn|aquaman|the flash|peacemaker|supergirl)\b", 5.0),
        (r"\b(trailer|first look|teaser|casting|cast as|release date)\b", 2.5),
        (r"\b(box office|opening weekend|renewed|cancell?ed|season \d)\b", 2.0),
        (r"\b(oscar|emmy|golden globe|cannes|sundance)\b", 2.0),
    ],
}

FRANCHISE_TAGS = [
    ("Marvel", r"\b(marvel|mcu|avengers|spider[- ]?man|x[- ]men|deadpool|thor|"
               r"loki|fantastic four|doctor strange|wakanda|daredevil|punisher|"
               r"kevin feige)\b"),
    ("DC",     r"\b(dc(u|eu)?\b|batman|superman|wonder woman|joker|justice league|"
               r"james gunn|aquaman|the flash|peacemaker|supergirl)"),
]

TRACKING_PARAMS = re.compile(
    r"^(utm_|fbclid|gclid|mc_cid|mc_eid|ref|ref_src|source|cmpid|ncid|at_|__twitter)"
)


# --------------------------------------------------------------------- helpers

def canonical_url(url: str) -> str:
    """Strip tracking junk so the same article from two feeds collapses."""
    if not url:
        return ""
    try:
        p = urlparse(url.strip())
    except ValueError:
        return url.strip()
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
         if not TRACKING_PARAMS.match(k)]
    path = p.path.rstrip("/") or "/"
    netloc = p.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if netloc.startswith("amp."):
        netloc = netloc[4:]
    return urlunparse(("https", netloc, path, "", urlencode(q), ""))


def title_tokens(title: str) -> frozenset:
    t = re.sub(r"[^a-z0-9 ]+", " ", (title or "").lower())
    return frozenset(w for w in t.split() if len(w) > 2 and w not in STOPWORDS)


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def keyword_score(text: str, sector: str) -> float:
    text = (text or "").lower()
    total = 0.0
    for pattern, pts in KEYWORD_BOOSTS.get(sector, []):
        if re.search(pattern, text):
            total += pts
    return total


def franchise_tags(text: str):
    text = (text or "").lower()
    return [name for name, pat in FRANCHISE_TAGS if re.search(pat, text)]


def recency_points(published_iso: str, now: datetime) -> float:
    if not published_iso:
        return 0.0
    try:
        dt = datetime.fromisoformat(published_iso)
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_h = max((now - dt).total_seconds() / 3600.0, 0.0)
    return RECENCY_MAX * (0.5 ** (age_h / RECENCY_HALF_LIFE_H))


# ----------------------------------------------------------------------- dedupe

def dedupe(items, title_threshold=0.62):
    """
    Collapse duplicate stories. Keeps the highest-tier version as the canonical
    entry and records every other outlet that ran it in `also_in`.

    Deliberately O(n * buckets) rather than O(n^2): titles are bucketed by their
    rarest two tokens so only plausible candidates get compared.
    """
    items = sorted(items, key=lambda i: (i["tier"], -len(i.get("summary") or "")))

    by_url = {}
    for it in items:
        cu = it["canonical_url"]
        if cu and cu in by_url:
            _merge(by_url[cu], it)
        else:
            by_url[cu or id(it)] = it

    survivors = []
    buckets = {}          # token -> [index into survivors]
    for it in by_url.values():
        toks = it["_tokens"]
        cand_idx = set()
        for tok in toks:
            cand_idx.update(buckets.get(tok, ()))

        hit = None
        for idx in cand_idx:
            if jaccard(toks, survivors[idx]["_tokens"]) >= title_threshold:
                hit = survivors[idx]
                break

        if hit is not None:
            _merge(hit, it)
        else:
            survivors.append(it)
            pos = len(survivors) - 1
            for tok in toks:
                buckets.setdefault(tok, []).append(pos)

    return survivors


def _merge(keeper, other):
    if other["source"] != keeper["source"] and other["source"] not in keeper["also_in"]:
        keeper["also_in"].append(other["source"])
    # keep the earliest publication time we saw -- that is when the story broke
    if other.get("published") and (
        not keeper.get("published") or other["published"] < keeper["published"]
    ):
        keeper["published"] = other["published"]
    # prefer a real summary over an empty one
    if len(other.get("summary") or "") > len(keeper.get("summary") or ""):
        keeper["summary"] = other["summary"]


# ------------------------------------------------------------------------ score

def score_all(items, now: datetime):
    for it in items:
        blob = f"{it['title']} {it.get('summary') or ''}"
        corro = min(len(it["also_in"]) * CORROBORATION_BONUS, CORROBORATION_CAP)
        it["corroboration"] = len(it["also_in"]) + 1
        it["tags"] = franchise_tags(blob)
        it["score"] = round(
            TIER_WEIGHT.get(it["tier"], 1.0)
            + recency_points(it.get("published"), now)
            + corro
            + keyword_score(blob, it["sector"]),
            2,
        )
    return sorted(items, key=lambda i: (-i["score"], i.get("published") or ""))
