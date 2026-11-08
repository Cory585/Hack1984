"""Confirm who an expert is before searching for ties.

A common name matching the wrong person means a false accusation, so the rule is
strict: exactly one ORCID record matching name + the affiliation the article
gives -> confirmed. Anything else -> "identity not confirmed" and no ties shown.
"""
from __future__ import annotations

from .clients import orcid_search
from .session import Session


def split_name(name: str) -> tuple[str, str]:
    parts = name.split()
    return " ".join(parts[:-1]), parts[-1]


def _records(data: dict) -> list[dict]:
    out = []
    for r in (data or {}).get("expanded-result") or []:
        out.append({
            "orcid": r.get("orcid-id"),
            "name": f"{r.get('given-names') or ''} {r.get('family-names') or ''}".strip(),
            "institutions": (r.get("institution-name") or [])[:4],
        })
    return out


def resolve_identity(s: Session, name: str, affiliation: str | None) -> dict:
    given, family = split_name(name)
    if not affiliation:
        return {"status": "not_confirmed",
                "reason": "The article gives no affiliation to confirm this person against.",
                "candidates": []}
    recs = _records(orcid_search(s, given, family, affiliation))
    if len(recs) == 1:
        return {"status": "confirmed", "orcid": recs[0]["orcid"], "record": recs[0],
                "reason": f"One ORCID record matches {name} at {affiliation}."}
    if len(recs) > 1:
        return {"status": "not_confirmed", "reason": f"{len(recs)} ORCID records match; can't tell which.",
                "candidates": recs}
    return {"status": "not_confirmed",
            "reason": f"No ORCID record matches {name} at {affiliation}.", "candidates": []}
