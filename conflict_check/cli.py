"""Command-line runner for quick tests on real articles (the hour-1 test).

    python -m conflict_check.cli https://example.com/article
    python -m conflict_check.cli --file article.txt --experts-only
    python -m conflict_check.cli URL --expert "Jane Doe@Harvard Medical School" --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys

from .pipeline import check_article, find_experts
from .server import cache_dir, load_env
from .session import Session


def parse_expert(raw: str) -> dict:
    name, _, aff = raw.partition("@")
    return {"name": name.strip(), "affiliation": aff.strip() or None}


def print_result(r: dict) -> None:
    for e in r["experts"]:
        print(f"\n== {e['name']}  ({e.get('affiliation') or 'no affiliation'})  -> {e['status']}")
        ident = e.get("identity") or {}
        if ident.get("reason"):
            print(f"   identity: {ident['reason']}")
        for c in (ident.get("candidates") or [])[:5]:
            print(f"     candidate {c['orcid']}  {c['name']}  {', '.join(c['institutions'])}")
        if e.get("error"):
            print(f"   error: {e['error']}")
        for group, ties in (("NOT MENTIONED", e.get("ties") or []), ("disclosed", e.get("disclosed") or [])):
            for t in ties:
                where = "related to story" if t.get("related_to_story") else "other"
                print(f"   [{group}] {t['org']}  ({t['relation']}, {where})")
                for ev in t["evidence"]:
                    print(f"       \"{ev['quote'][:160]}\"\n       {ev['url']}")
                op = t.get("open_payments")
                if op and op.get("status") == "name_match":
                    print(f"       Open Payments: ${op['total_usd']:,} in {op['payments']} payment(s), "
                          f"{op['location']}, NPI {op['npi']}")
                elif op:
                    print(f"       Open Payments: {op.get('note')}")
    if r.get("skipped_experts"):
        print(f"\nnot checked (limit): {', '.join(r['skipped_experts'])}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Conflict Check from the command line")
    ap.add_argument("url", nargs="?")
    ap.add_argument("--file", help="read article text from a file instead of a URL")
    ap.add_argument("--expert", action="append", help='"Name@Affiliation"; overrides extraction (repeatable)')
    ap.add_argument("--experts-only", action="store_true", help="only list extracted experts")
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--json", help="also write the full result to this file")
    args = ap.parse_args()
    load_env()
    text = open(args.file, encoding="utf-8").read() if args.file else None
    if not (args.url or text):
        ap.error("give a URL or --file")
    s = Session(cache_dir=cache_dir(), replay=args.replay)

    if args.experts_only:
        r = find_experts(s, url=args.url, text=text)
        for e in r["experts"]:
            print(f"{e['name']:<28} {e.get('affiliation') or '-':<40} mentions={e['mentions']} {e['signals']}")
            print(f"    {e['context'][:140]}")
    else:
        experts = [parse_expert(x) for x in args.expert] if args.expert else None
        r = check_article(s, url=args.url, text=text, experts=experts)
        print_result(r)
        r.pop("text", None)

    calls = {}
    for c in s.calls:
        calls[c["api"]] = calls.get(c["api"], 0) + 1
    print(f"\nAPI calls: {calls}", file=sys.stderr)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(r, f, indent=1)


if __name__ == "__main__":
    main()
