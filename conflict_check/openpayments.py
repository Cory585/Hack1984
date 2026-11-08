"""CMS Open Payments as a *confirmation badge* on a tie already found in papers or bios.

It never creates a tie on its own: Open Payments matches by name, city and state,
not by institution, so it can't prove identity. The badge shows the physician's
city, state and NPI so a human can judge, and it's withheld when more than one
physician with that name was paid by the company.
"""
from __future__ import annotations

import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from .clients import open_payments_query
from .session import Session
from .ties import distinctive_tokens

# General Payment datasets (identifiers from the CMS metastore, checked 2026-11-07).
DEFAULT_DATASETS = {
    "2025": "fb0b1734-1410-429d-92f6-3f4b35218e5e",
    "2024": "e6b17c6a-2534-4207-a4a1-6746a14911ff",
}


def datasets() -> dict[str, str]:
    """OPEN_PAYMENTS_DATASETS="2025:id,2024:id" overrides; OPEN_PAYMENTS=off disables."""
    if os.environ.get("OPEN_PAYMENTS", "").lower() in ("0", "off", "false"):
        return {}
    raw = os.environ.get("OPEN_PAYMENTS_DATASETS")
    if not raw:
        return DEFAULT_DATASETS
    return dict(pair.split(":", 1) for pair in raw.split(",") if ":" in pair)


def _amount(row: dict) -> float:
    try:
        return float(row.get("total_amount_of_payment_usdollars") or 0)
    except ValueError:
        return 0.0


def summarize(rows: list[dict], org: str) -> dict | None:
    toks = [t.lower() for t in distinctive_tokens(org)]
    rows = [r for r in rows
            if all(t in (r.get("applicable_manufacturer_or_applicable_gpo_making_payment_name") or "").lower()
                   for t in toks)]
    if not rows:
        return None
    npis = {r.get("covered_recipient_npi") for r in rows}
    if len(npis) > 1:
        return {"status": "ambiguous", "physicians": len(npis),
                "note": f"{len(npis)} physicians with this name received payments from {org}; not shown."}
    r0 = rows[0]
    natures = Counter(r.get("nature_of_payment_or_transfer_of_value") for r in rows)
    return {
        "status": "name_match",
        "npi": r0.get("covered_recipient_npi"),
        "location": f"{(r0.get('recipient_city') or '').title()}, {r0.get('recipient_state') or ''}".strip(", "),
        "specialty": (r0.get("covered_recipient_specialty_1") or "").split("|")[-1],
        "payer": r0.get("applicable_manufacturer_or_applicable_gpo_making_payment_name"),
        "payments": len(rows),
        "total_usd": round(sum(_amount(r) for r in rows), 2),
        "years": sorted({r["_year"] for r in rows}),
        "top_natures": [n for n, _ in natures.most_common(3) if n],
        "note": "Name match only. Open Payments lists city and state, not employer, so check the location.",
    }


def badge_for_tie(s: Session, name: str, org: str) -> dict | None:
    sets = datasets()
    toks = distinctive_tokens(org)
    if not sets or not toks:
        return None
    parts = name.split()
    first, last = parts[0], parts[-1]
    needle = max(toks, key=len)
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(sets)) as pool:  # one query per year, side by side
        futures = {year: pool.submit(open_payments_query, s, ds, year, first, last, needle)
                   for year, ds in sets.items()}
        for year, f in futures.items():
            for r in f.result():
                r["_year"] = year
                rows.append(r)
    return summarize(rows, org)
