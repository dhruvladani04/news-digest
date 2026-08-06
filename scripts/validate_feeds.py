#!/usr/bin/env python3
"""
Feed health check. Run after cloning and any time you add a feed:

    python scripts/validate_feeds.py              # report
    python scripts/validate_feeds.py --verbose    # full error text
    python scripts/validate_feeds.py --json out.json

Uses the exact same retry ladder as the real pipeline, and tells you which
strategy each feed needed -- so a feed marked OK (legacy-tls) is one that would
have failed with a naive fetcher.

Note: SSL and 403 failures are often specific to the network you run from.
Corporate networks, ISP TLS inspection and consumer antivirus all cause
handshake failures that GitHub's runners never see. Before deleting a feed that
fails here, run the same check from CI:
    Actions -> Validate feeds -> Run workflow
"""

import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import feedparser

sys.path.insert(0, str(Path(__file__).resolve().parent))
from feeds import FEEDS                              # noqa: E402
from http_client import (FeedClient, describe_error,      # noqa: E402
                         trust_store_status, is_cert_error,
                         looks_like_block_page)

GREEN, YELLOW, RED, DIM, BOLD, RESET = (
    "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m")
if not sys.stdout.isatty():
    GREEN = YELLOW = RED = DIM = BOLD = RESET = ""


def check(feed, client):
    name, url, sector, tier = feed
    import time
    t0 = time.time()
    try:
        resp, strategy = client.get(url)
    except Exception as exc:                          # noqa: BLE001
        return dict(name=name, sector=sector, url=url, status="DEAD",
                    detail=describe_error(exc), full=str(exc),
                    strategy=None, entries=0, ms=int((time.time() - t0) * 1000))

    ms = int((time.time() - t0) * 1000)
    if looks_like_block_page(resp.content, resp.headers.get("Content-Type", "")):
        return dict(name=name, sector=sector, url=url, status="DEAD",
                    detail="blocked by a network filter", full="",
                    strategy=strategy, entries=0, ms=ms)
    parsed = feedparser.parse(resp.content)
    n = len(parsed.entries)
    if n == 0:
        return dict(name=name, sector=sector, url=url, status="EMPTY",
                    detail="parsed but no entries", full="", strategy=strategy,
                    entries=0, ms=ms)
    dated = sum(1 for e in parsed.entries
                if e.get("published_parsed") or e.get("updated_parsed"))
    if dated == 0:
        return dict(name=name, sector=sector, url=url, status="EMPTY",
                    detail=f"{n} entries, none dated", full="", strategy=strategy,
                    entries=n, ms=ms)
    return dict(name=name, sector=sector, url=url, status="OK",
                detail=f"{dated}/{n} dated", full="", strategy=strategy,
                entries=dated, ms=ms)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="print the full error for every failure")
    ap.add_argument("--json", metavar="PATH", help="also write results as JSON")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    print(f"{DIM}{trust_store_status()}{RESET}")
    print(f"Checking {len(FEEDS)} feeds "
          f"(fallbacks are chosen per error, not walked blindly)...\n")

    client = FeedClient()
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(check, f, client) for f in FEEDS]
        for fut in as_completed(futs):
            results.append(fut.result())

    results.sort(key=lambda r: (r["sector"], r["name"]))
    colour = {"OK": GREEN, "EMPTY": YELLOW, "DEAD": RED}
    current = None
    for r in results:
        if r["sector"] != current:
            print(f"\n{BOLD}{r['sector']}{RESET}")
            current = r["sector"]
        via = ""
        if r["strategy"] and r["strategy"] != "browser":
            via = f" {YELLOW}via {r['strategy']}{RESET}"
        print(f"  {colour[r['status']]}{r['status']:<6}{RESET} {r['name']:<22} "
              f"{DIM}{r['detail']:<32} {r['ms']:>5}ms{RESET}{via}")
        if args.verbose and r["full"]:
            print(f"         {DIM}{r['full'][:300]}{RESET}")

    c = Counter(r["status"] for r in results)
    print(f"\n{GREEN}{c['OK']} ok{RESET}  {YELLOW}{c['EMPTY']} empty{RESET}  "
          f"{RED}{c['DEAD']} dead{RESET}   ({len(FEEDS)} total)")

    rescued = [r for r in results
               if r["status"] == "OK" and r["strategy"] not in (None, "browser")]
    if rescued:
        print(f"\n{YELLOW}Rescued by fallback{RESET} "
              f"(these would fail a naive fetcher):")
        for r in rescued:
            print(f"  {r['name']:<22} {r['strategy']}")

    bad = [r for r in results if r["status"] != "OK"]
    if bad:
        print(f"\n{RED}Still failing{RESET}:")
        for r in bad:
            print(f"  {r['name']:<22} {r['detail']:<28} {r['url']}")
        certs = [r for r in bad if "untrusted certificate" in r["detail"]]
        if certs:
            print(f"\n{YELLOW}{len(certs)} feeds were served an untrusted certificate.{RESET}")
            print(f"{DIM}Rejected by both certifi and the OS trust store, which means{RESET}")
            print(f"{DIM}the chain is being replaced in transit rather than simply being{RESET}")
            print(f"{DIM}unknown to Python. Find out by whom:{RESET}")
            print(f"  uv run python scripts/diagnose_tls.py")
            print(f"{DIM}This affects your network only -- CI is not behind it.{RESET}")
        print(f"\n{DIM}Before deleting anything, run the same check from CI --{RESET}\n"
              f"{DIM}  Actions -> Validate feeds -> Run workflow{RESET}")

    # per-sector health, so you notice when a sector is running thin
    print(f"\n{BOLD}per sector{RESET}")
    by_sec = {}
    for r in results:
        by_sec.setdefault(r["sector"], []).append(r)
    for sec, rs in sorted(by_sec.items()):
        ok = sum(1 for r in rs if r["status"] == "OK")
        warn = RED if ok < 4 else (YELLOW if ok < 6 else GREEN)
        print(f"  {warn}{ok}/{len(rs)}{RESET} {sec}")

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=1), encoding="utf-8")
        print(f"\nwrote {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
