"""Confirm who an expert is before searching for ties.

A common name matching the wrong person means a false accusation, so the rule is
strict: exactly one ORCID record matching name + the affiliation the article
gives -> confirmed. Anything else -> "identity not confirmed", no ties shown, and
the candidates are returned so the user can pick the right person in one click.
A user-picked ORCID iD is re-checked against the expert's surname.
"""
from __future__ import annotations

import re

from .clients import openalex_institutions, orcid_person, orcid_search
from .session import Session

MAX_CORROBORATE = 5  # OpenAlex lookups per expert
ORCID_ID = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


_ABBREV = (("ucsf", "university of california san francisco"), ("ucla", "university of california los angeles"),
           ("ucsd", "university of california san diego"), ("uc ", "university of california "),
           ("univ ", "university "), ("univ. ", "university "))


def institution_key(name: str) -> frozenset[str]:
    """Spellings of one institution compare equal: 'UC San Francisco' == 'University of California, San
    Francisco'. Whole-name equality only, so 'University of California' never matches one campus."""
    n = re.sub(r"[^a-z0-9 ]", " ", name.lower().replace("&", " and "))
    n = " " + re.sub(r"\s+", " ", n).strip() + " "
    for short, full in _ABBREV:
        n = n.replace(" " + short.strip() + " ", " " + full.strip() + " ")
    return frozenset(w for w in n.split() if w not in {"the", "of", "at", "and"})


_PARTICLES = {"de", "del", "della", "di", "da", "dos", "du", "van", "von", "der", "den", "la", "le", "bin", "ibn", "al", "el", "st", "st."}


def split_name(name: str) -> tuple[str, str]:
    """Given and family names. Lowercase particles stay with the family name: 'Etienne de Villers-Sidani'."""
    parts = name.split()
    i = len(parts) - 1
    while i > 1 and parts[i - 1].lower() in _PARTICLES:
        i -= 1
    return " ".join(parts[:i]), " ".join(parts[i:])


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
    if affiliation:
        recs = _records(orcid_search(s, given, family, affiliation))
        # An article often gives a long unit ("University of Oxford Nuffield Department of Primary Care ..."),
        # which ORCID's institution field won't match. Retry with shorter prefixes ("University of Oxford");
        # a prefix that is too general matches several people and so stays unconfirmed.
        words = affiliation.split()
        for n in range(len(words) - 1, 1, -1) if not recs and len(words) > 3 else ():
            recs = _records(orcid_search(s, given, family, " ".join(words[:n])))
            if recs:
                affiliation = " ".join(words[:n])
                break
        if len(recs) == 1:
            return {"status": "confirmed", "by": "orcid", "orcid": recs[0]["orcid"], "record": recs[0],
                    "reason": f"One ORCID record matches {name} at {affiliation}."}
        if len(recs) > 1:
            return {"status": "not_confirmed", "candidates": recs,
                    "reason": f"{len(recs)} ORCID records match {name} at {affiliation}; pick the right one."}
        reason = f"No ORCID record matches {name} at {affiliation}."
    else:
        reason = "The article gives no affiliation to confirm this person against."
    # Name-only search. It confirms only when exactly one record lists this institution under another
    # spelling ("UC San Francisco"); otherwise it just offers candidates to pick from.
    recs = _records(orcid_search(s, given, family))
    if affiliation:
        want = institution_key(affiliation)
        same = [r for r in recs if any(institution_key(i) == want for i in r["institutions"])]
        if len(same) == 1:
            r = same[0]
            return {"status": "confirmed", "by": "orcid", "orcid": r["orcid"], "record": r,
                    "reason": f"The only ORCID record for {name} lists {affiliation} (as "
                              f"{next(i for i in r['institutions'] if institution_key(i) == want)})."}
    if affiliation and 0 < len(recs) <= MAX_CORROBORATE:
        # ORCID records often list no institution at all. Check each candidate's papers (OpenAlex) and confirm
        # only if exactly one of them shows this institution.
        want = institution_key(affiliation)
        hits = [r for r in recs
                if any(institution_key(i) == want for i in openalex_institutions(s, r["orcid"]))]
        if len(hits) == 1:
            r = hits[0]
            return {"status": "confirmed", "by": "orcid+openalex", "orcid": r["orcid"], "record": r,
                    "reason": f"The only ORCID record for {name} whose papers list {affiliation} (OpenAlex)."}
    if recs:
        reason += f" {len(recs)} record(s) match the name alone; pick one if you recognise them."
    return {"status": "not_confirmed", "reason": reason, "candidates": recs}


def identity_from_pick(s: Session, name: str, orcid: str) -> dict:
    """The user picked an ORCID iD from the candidates. Check it exists and the surname matches."""
    if not ORCID_ID.match(orcid or ""):
        return {"status": "not_confirmed", "reason": f"'{orcid}' isn't a valid ORCID iD.", "candidates": []}
    rec = orcid_person(s, orcid) or {}
    n = rec.get("name") or {}
    given = ((n.get("given-names") or {}).get("value") or "").strip()
    family = ((n.get("family-name") or {}).get("value") or "").strip()
    if family.lower() != split_name(name)[1].lower():
        return {"status": "not_confirmed", "candidates": [],
                "reason": f"ORCID {orcid} belongs to '{given} {family}', not {name}."}
    return {"status": "confirmed", "by": "user", "orcid": orcid,
            "record": {"orcid": orcid, "name": f"{given} {family}".strip(), "institutions": []},
            "reason": f"Picked by the user; ORCID {orcid} is {given} {family}."}
