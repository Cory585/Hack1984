"""Score Conflict Check against a hand-checked test set (the 'can't prove it works' slide).

    python -m eval.run_eval [--replay] [--testset eval/testset.json]

testset.json: list of cases
  {"id": "...", "url": "..." | "text_file": "path", "experts": {"Full Name": ["Org A", "Org B"]}}
Each expert maps to the undisclosed ties a human confirmed ([] = should find nothing).
Reports tie precision/recall and how often the tool declines (identity not confirmed).
"""
from __future__ import annotations

import argparse
import json
import os

from conflict_check.pipeline import check_article
from conflict_check.server import CACHE, load_env
from conflict_check.session import Session
from conflict_check.ties import same_org


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--testset", default=os.path.join(os.path.dirname(__file__), "testset.json"))
    ap.add_argument("--replay", action="store_true")
    args = ap.parse_args()
    load_env()
    with open(args.testset, encoding="utf-8") as f:
        cases = json.load(f)

    tp = fp = fn = experts = declined = 0
    for case in cases:
        text = None
        if case.get("text_file"):
            with open(case["text_file"], encoding="utf-8") as f:
                text = f.read()
        s = Session(cache_dir=CACHE, replay=args.replay)
        result = check_article(s, url=case.get("url"), text=text)
        got = {e["name"]: e for e in result["experts"]}
        for name, expected in case["experts"].items():
            experts += 1
            e = got.get(name)
            if not e or e["status"] in ("identity_not_confirmed", "error"):
                declined += 1
                print(f"[{case['id']}] {name}: declined ({e['status'] if e else 'not extracted'})")
                continue
            found = [t["org"] for t in e["ties"]]
            hit = [o for o in found if any(same_org(o, x) for x in expected)]
            tp += len(hit)
            fp += len(found) - len(hit)
            fn += sum(1 for x in expected if not any(same_org(o, x) for o in found))
            print(f"[{case['id']}] {name}: found {found}, expected {expected}")

    prec = tp / (tp + fp) if tp + fp else 1.0
    rec = tp / (tp + fn) if tp + fn else 1.0
    print(f"\n{experts} experts | declined {declined} | precision {prec:.0%} | recall {rec:.0%} "
          f"(TP {tp}, FP {fp}, FN {fn})")


if __name__ == "__main__":
    main()
