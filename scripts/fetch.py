#!/usr/bin/env python3
"""
Daily news digest builder.

Pulls every feed in feeds.py, keeps the last 24h (configurable), dedupes across
outlets, ranks per sector, and writes:

    data/YYYY-MM-DD.json   the digest for that IST day
    data/index.json        list of every day available, newest first
    data/latest.json       copy of the newest digest, for a fast first paint

A feed that fails does not fail the run -- it is recorded in meta.failed_feeds
and the digest is built from whatever came back.
"""

import argparse
import html
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rank as R                              # noqa: E402
from feeds import FEEDS, SECTORS              # noqa: E402
from http_client import (FeedClient, describe_error,   # noqa: E402
                         looks_like_block_page)

IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

TOP_N = 10                 # headline stories shown per sector
MORE_N = 25                # additional stories under "show more"
SUMMARY_CHARS = 420


# ---------------------------------------------------------------- text cleanup

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean_text(raw: str) -> str:
    if not raw:
        return ""
    txt = TAG_RE.sub(" ", raw)
    txt = html.unescape(txt)
    txt = WS_RE.sub(" ", txt).strip()
    # drop the "The post X appeared first on Y" boilerplate WordPress feeds add
    txt = re.sub(r"\s*The post .{0,120}? appeared first on .*$", "", txt)
    txt = re.sub(r"\s*Continue reading\.*$", "", txt, flags=re.I)
    return txt


def truncate(txt: str, limit: int = SUMMARY_CHARS) -> str:
    if len(txt) <= limit:
        return txt
    cut = txt[:limit]
    # prefer a sentence boundary, fall back to a word boundary
    for stop in (". ", "! ", "? "):
        idx = cut.rfind(stop)
        if idx > limit * 0.55:
            return cut[: idx + 1].strip()
    idx = cut.rfind(" ")
    return (cut[:idx] if idx > 0 else cut).strip() + "…"


def entry_summary(entry) -> str:
    for key in ("summary", "description"):
        val = entry.get(key)
        if val:
            return truncate(clean_text(val))
    content = entry.get("content")
    if content and isinstance(content, list) and content[0].get("value"):
        return truncate(clean_text(content[0]["value"]))
    return ""


def entry_author(entry) -> str:
    a = entry.get("author") or ""
    if not a and entry.get("authors"):
        a = entry["authors"][0].get("name", "") if entry["authors"] else ""
    a = clean_text(a)
    # some feeds stuff an email in there
    a = re.sub(r"\S+@\S+\.\S+", "", a).strip(" ()<>-,")
    return a[:80]


def entry_published(entry):
    for key in ("published_parsed", "updated_parsed"):
        tm = entry.get(key)
        if tm:
            try:
                return datetime.fromtimestamp(time.mktime(tm), tz=timezone.utc)
            except (ValueError, OverflowError, TypeError):
                continue
    return None


def resolve_google_news(url: str, source: str):
    """Google News RSS wraps the real article URL. Keep the wrapper as the link
    (it redirects fine in a browser) but pull the true publisher out of the
    title suffix Google appends: 'Headline - Reuters'."""
    return url


# --------------------------------------------------------------------- fetching

def fetch_one(feed, client, window_start):
    name, url, sector, tier = feed
    try:
        resp, strategy = client.get(url)
        if looks_like_block_page(resp.content, resp.headers.get("Content-Type", "")):
            return (name, [],
                    "blocked by a network filter (not the publisher)", strategy)
        parsed = feedparser.parse(resp.content)
    except Exception as exc:                      # noqa: BLE001
        return name, [], describe_error(exc), None

    if parsed.bozo and not parsed.entries:
        return name, [], f"unparseable: {str(parsed.get('bozo_exception'))[:90]}", strategy

    out = []
    for entry in parsed.entries:
        title = clean_text(entry.get("title", ""))
        link = entry.get("link") or ""
        if not title or not link:
            continue

        published = entry_published(entry)
        if published is None:
            continue                              # undated -> can't trust it
        if published < window_start:
            continue
        # tolerate small clock skew, reject obviously-future dates
        if published > datetime.now(timezone.utc) + timedelta(hours=6):
            continue

        source = name
        # Google News titles look like "Real headline - Publisher"
        if "news.google.com" in url and " - " in title:
            head, _, pub = title.rpartition(" - ")
            if head and len(pub) < 40:
                title, source = head.strip(), pub.strip()

        item = {
            "title": title,
            "url": link,
            "canonical_url": R.canonical_url(link),
            "source": source,
            "feed": name,
            "tier": tier,
            "sector": sector,
            "author": entry_author(entry),
            "published": published.isoformat(),
            "summary": entry_summary(entry),
            "also_in": [],
        }
        item["_tokens"] = R.title_tokens(title)
        out.append(item)

    return name, out, None, strategy


def gather(window_hours: int, workers: int = 16):
    window_start = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    client = FeedClient()
    items, failed, per_feed, strategies = [], [], {}, {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_one, f, client, window_start): f for f in FEEDS}
        for fut in as_completed(futures):
            name, got, err, strategy = fut.result()
            if err:
                failed.append({"feed": name, "error": err})
                print(f"  [fail] {name}: {err}", file=sys.stderr)
            else:
                per_feed[name] = len(got)
                items.extend(got)
                if strategy and strategy != "browser":
                    strategies[name] = strategy
                note = f"  (via {strategy})" if strategy and strategy != "browser" else ""
                print(f"  [ ok ] {name}: {len(got)}{note}", file=sys.stderr)

    return items, failed, per_feed, strategies


# ----------------------------------------------------------------------- output

def strip_private(item):
    return {k: v for k, v in item.items() if not k.startswith("_")}


def build(window_hours: int):
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(IST)

    print(f"Fetching {len(FEEDS)} feeds (last {window_hours}h)...", file=sys.stderr)
    items, failed, per_feed, strategies = gather(window_hours)
    raw_count = len(items)

    sectors_out = []
    kept_total = 0
    for sec in SECTORS:
        pool = [i for i in items if i["sector"] == sec["id"]]
        deduped = R.dedupe(pool)
        ranked = R.score_all(deduped, now_utc)
        top = [strip_private(i) for i in ranked[:TOP_N]]
        more = [strip_private(i) for i in ranked[TOP_N:TOP_N + MORE_N]]
        kept_total += len(top) + len(more)
        sectors_out.append({
            "id": sec["id"],
            "name": sec["name"],
            "blurb": sec["blurb"],
            "count": len(ranked),
            "top": top,
            "more": more,
        })

    digest = {
        "date": now_ist.strftime("%Y-%m-%d"),
        "generated_at": now_ist.isoformat(),
        "window_hours": window_hours,
        "sectors": sectors_out,
        "meta": {
            "feeds_total": len(FEEDS),
            "feeds_ok": len(FEEDS) - len(failed),
            "failed_feeds": sorted(failed, key=lambda f: f["feed"]),
            "items_fetched": raw_count,
            "items_published": kept_total,
            "per_feed": dict(sorted(per_feed.items())),
            "fallback_strategies": dict(sorted(strategies.items())),
        },
    }
    return digest


def write(digest):
    DATA.mkdir(parents=True, exist_ok=True)
    day_path = DATA / f"{digest['date']}.json"
    day_path.write_text(json.dumps(digest, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "latest.json").write_text(
        json.dumps(digest, ensure_ascii=False, indent=1), encoding="utf-8")

    dates = sorted(
        (p.stem for p in DATA.glob("*.json")
         if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem)),
        reverse=True,
    )
    index = {
        "updated": digest["generated_at"],
        "latest": dates[0] if dates else digest["date"],
        "dates": dates,
    }
    (DATA / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return day_path, len(dates)


def main():
    ap = argparse.ArgumentParser(description="Build the daily news digest.")
    ap.add_argument("--hours", type=int, default=int(os.getenv("WINDOW_HOURS", "24")),
                    help="how far back to look (default 24)")
    ap.add_argument("--dry-run", action="store_true",
                    help="build and report but do not write files")
    args = ap.parse_args()

    digest = build(args.hours)
    m = digest["meta"]

    print("\n--- digest summary ---", file=sys.stderr)
    print(f"date            {digest['date']}", file=sys.stderr)
    print(f"feeds ok        {m['feeds_ok']}/{m['feeds_total']}", file=sys.stderr)
    print(f"items fetched   {m['items_fetched']}", file=sys.stderr)
    print(f"items published {m['items_published']}", file=sys.stderr)
    for s in digest["sectors"]:
        print(f"  {s['name']:<28} {s['count']:>4} unique", file=sys.stderr)
    if m["failed_feeds"]:
        print(f"failed          {', '.join(f['feed'] for f in m['failed_feeds'])}",
              file=sys.stderr)

    if args.dry_run:
        print("\n(dry run, nothing written)", file=sys.stderr)
        return 0

    # Guard: never overwrite a good digest with an empty one.
    if m["items_published"] == 0:
        print("\nERROR: zero stories collected, refusing to write.", file=sys.stderr)
        return 1

    path, ndays = write(digest)
    print(f"\nwrote {path.name}  ({ndays} days in archive)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
