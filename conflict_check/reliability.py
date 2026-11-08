"""Reliability ratings: how much to trust each connection, and how thorough each check was.

Connection score
----------------
score = 100 x (weighted mean of the factors below, each 0..1) + Open Payments bonus,
clamped to 0..100 and rounded half-up to a whole number.

  factor          weight  values
  identity         .20    ORCID auto-confirmed 1.0 · picked by a person 0.8 · unknown 0.5
  attribution      .20    best evidence: full name 1.0 · surname + initial .9 · surname .85 · initials .75 ·
                          semicolon continuation .7 · he/she/they .6
  source           .20    best evidence: research-paper disclosure 1.0 · institutional page
                          (.edu, .gov, .ac.xx) .85 · other web page .6
  corroboration    .15    independent websites: 1 -> .55 · 2 -> .85 · 3+ -> 1.0
  wording          .10    most specific tie word: employment/equity/board/founder/patents 1.0 ·
                          consulting/advisory/research funding/speaking .9 · personal fees .75 · other .6
  recency          .10    newest year seen in the evidence: <=3 years 1.0 (disclosures usually cover
                          36 months) · <=6 years .75 · older .5 · no year found .7
  organization     .05    full name 1.0 · bare acronym (GSK) .8
  Open Payments    bonus  +8 when a single physician's payments from this company match; never negative

Labels: Strong >= 80, Moderate >= 60, Weak below. A score exactly on a boundary takes the higher
label (80 is Strong). Rounding happens before labelling, and half-up: 79.5 -> 80 -> Strong.

What happens on a tie (equal scores)
------------------------------------
Connections for one expert are ordered by, in turn:
  1. named in this story first (relevance to the article outranks the score)
  2. higher score
  3. more independent websites
  4. stronger best source (paper > institutional page > other)
  5. more serious kind of tie (employment > equity > board > founder > patents > consulting >
     advisory board > research funding > speaking > personal fees > other)
  6. organization name, case-insensitive A-Z
  7. the order they were found (the sort is stable)
So the order is fully deterministic: two runs on the same evidence always list ties the same way.

Coverage (per expert)
---------------------
How thorough the search was, which matters most for a clean "no confirmed connections" result:
identity (as above, .4), pages checked (0 -> 0 · 1-2 -> .5 · 3-5 -> .8 · 6+ -> 1.0, weight .35) and
search channels that returned pages (Exa and Tavily both 1.0 · one .6 · none 0, weight .25).
Same rounding and labels. Not rated when identity wasn't confirmed or the search failed.
"""
from __future__ import annotations

import datetime
import re
import urllib.parse
from decimal import ROUND_HALF_UP, Decimal

WEIGHTS = {"identity": .20, "attribution": .20, "source": .20, "corroboration": .15,
           "wording": .10, "recency": .10, "organization": .05}
OP_BONUS = 8
BANDS = ((80, "Strong"), (60, "Moderate"), (0, "Weak"))

IDENTITY = {"orcid": 1.0, "user": .8}
ATTRIBUTION = {"full name": 1.0, "surname + initial": .9, "surname": .85, "initials": .75, "continuation": .7, "pronoun": .6}
SOURCE = {"paper": 1.0, "institution": .85, "web": .6}
WORDING = {"employment": 1.0, "equity": 1.0, "board": 1.0, "founder": 1.0, "patents / royalties": 1.0,
           "consulting": .9, "advisory board": .9, "research funding": .9, "speaking": .9,
           "personal fees": .75, "other": .6}
CATEGORY_RANK = ["employment", "equity", "board", "founder", "patents / royalties", "consulting",
                 "advisory board", "research funding", "speaking", "personal fees", "other"]
YEAR = re.compile(r"(?<!\d\.)(?<![\d,])(199\d|20\d\d)(?!\d|,\d)")  # skips 0.2024, 9,400 and 2,025,000; keeps jama.2024 and "In 2019, …"
INSTITUTIONAL = re.compile(r"\.(?:edu|gov|mil)$|\.(?:ac|edu|gov|nhs)\.[a-z]{2}$|\.nhs\.uk$")


def round_half_up(x: float) -> int:
    # str(round(x, 6)) first, so 79.4999999999 from float arithmetic still counts as 79.5.
    return int(Decimal(str(round(x, 6))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def label(score: int | None) -> str | None:
    if score is None:
        return None
    return next(name for floor, name in BANDS if score >= floor)


def site(url: str | None) -> str:
    """Registrable domain, so two pages on one website count once: news.example.co.uk -> example.co.uk."""
    host = (urllib.parse.urlparse(url or "").hostname or "").lower().removeprefix("www.")
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in {"co", "ac", "gov", "edu", "org", "com", "nhs", "net"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def source_kind(ev: dict) -> str:
    if ev.get("api") == "exa":  # Exa is queried with category "research paper"
        return "paper"
    host = (urllib.parse.urlparse(ev.get("url") or "").hostname or "").lower()
    return "institution" if INSTITUTIONAL.search(host) else "web"


def newest_year(evidence: list[dict], now: int) -> int | None:
    years = [int(y) for ev in evidence for field in ("title", "url", "quote")
             for y in YEAR.findall(ev.get(field) or "") if 1990 <= int(y) <= now]
    return max(years) if years else None


def _factor(key: str, value: float, note: str) -> dict:
    return {"key": key, "value": round(value, 3), "weight": WEIGHTS.get(key), "note": note}


def score_tie(tie: dict, identity: dict | None, now: int | None = None) -> dict:
    """Adds tie['reliability'] = {score, label, factors, bonus} and returns it."""
    now = now or datetime.date.today().year
    evidence = tie.get("evidence") or []
    if not evidence:
        rel = {"score": 0, "label": "Weak", "factors": [], "bonus": 0, "note": "No evidence."}
        tie["reliability"] = rel
        return rel

    by = (identity or {}).get("by")
    f_ident = _factor("identity", IDENTITY.get(by, .5),
                      {"orcid": "confirmed by ORCID", "user": "picked by a person"}.get(by, "identity unknown"))
    best_attr = min((ev.get("matched_by") or "pronoun" for ev in evidence), key=lambda m: list(ATTRIBUTION).index(m)
                    if m in ATTRIBUTION else 99)
    f_attr = _factor("attribution", ATTRIBUTION.get(best_attr, .6), f"named by {best_attr}")
    kinds = [source_kind(ev) for ev in evidence]
    best_kind = max(kinds, key=lambda k: SOURCE[k])
    f_src = _factor("source", SOURCE[best_kind], {"paper": "research-paper disclosure",
                                                   "institution": "institutional page", "web": "web page"}[best_kind])
    sites = {site(ev.get("url")) for ev in evidence if ev.get("url")}
    n_sites = max(len(sites), 1)
    f_corr = _factor("corroboration", 1.0 if n_sites >= 3 else .85 if n_sites == 2 else .55,
                     f"{n_sites} independent website{'s' if n_sites != 1 else ''}")
    cats = tie.get("categories") or [tie.get("category") or "other"]
    best_cat = max(cats, key=lambda c: WORDING.get(c, .6))
    f_word = _factor("wording", WORDING.get(best_cat, .6), best_cat)
    year = newest_year(evidence, now)
    if year is None:
        f_rec = _factor("recency", .7, "no date found")
    else:
        age = now - year
        f_rec = _factor("recency", 1.0 if age <= 3 else .75 if age <= 6 else .5, f"newest source {year}")
    org = (tie.get("org") or "").strip()
    acronym = bool(re.fullmatch(r"[A-Z0-9&]{2,5}", org))
    f_org = _factor("organization", .8 if acronym else 1.0, "acronym only" if acronym else "full name")

    factors = [f_ident, f_attr, f_src, f_corr, f_word, f_rec, f_org]
    base = 100 * sum(f["value"] * f["weight"] for f in factors) / sum(WEIGHTS.values())
    op = tie.get("open_payments") or {}
    bonus = OP_BONUS if op.get("status") == "name_match" else 0
    score = max(0, min(100, round_half_up(base + bonus)))
    rel = {"score": score, "label": label(score), "factors": factors, "bonus": bonus,
           "sites": n_sites, "best_source": best_kind}
    tie["reliability"] = rel
    return rel


def tie_sort_key(indexed: tuple[int, dict]):
    """See 'What happens on a tie' above. Takes (found_order, tie) so the last tiebreaker is stable."""
    i, t = indexed
    r = t.get("reliability") or {}
    cats = t.get("categories") or [t.get("category") or "other"]
    most_serious = min(CATEGORY_RANK.index(c) if c in CATEGORY_RANK else len(CATEGORY_RANK) for c in cats)
    return (not t.get("related_to_story", False), -r.get("score", 0), -r.get("sites", 0),
            -SOURCE.get(r.get("best_source"), 0), most_serious, (t.get("org") or "").casefold(), i)


def order_ties(ties: list[dict]) -> list[dict]:
    return [t for _, t in sorted(enumerate(ties), key=tie_sort_key)]


def coverage(result: dict, pages: list[dict]) -> dict | None:
    """How thorough the check was. None when identity wasn't confirmed or the search failed."""
    ident = result.get("identity") or {}
    if ident.get("status") != "confirmed" or result.get("status") == "error":
        return None
    n = len(pages)
    channels = {p.get("api") for p in pages if p.get("api")}
    factors = [
        {"key": "identity", "value": IDENTITY.get(ident.get("by"), .5), "weight": .4,
         "note": {"orcid": "confirmed by ORCID", "user": "picked by a person"}.get(ident.get("by"), "identity unknown")},
        {"key": "pages", "value": 0 if n == 0 else .5 if n <= 2 else .8 if n <= 5 else 1.0, "weight": .35,
         "note": f"{n} page{'s' if n != 1 else ''} checked"},
        {"key": "channels", "value": 1.0 if {"exa", "tavily"} <= channels else .6 if channels else 0, "weight": .25,
         "note": " and ".join(sorted(channels)) + " returned pages" if channels else "no search returned pages"},
    ]
    score = max(0, min(100, round_half_up(100 * sum(f["value"] * f["weight"] for f in factors))))
    return {"score": score, "label": label(score), "factors": factors}


def rate_expert(result: dict, pages: list[dict], now: int | None = None) -> dict:
    """Score every tie (shown and disclosed), order them, and add the expert's coverage rating."""
    for group in ("ties", "disclosed"):
        for t in result.get(group) or []:
            score_tie(t, result.get("identity"), now)
        result[group] = order_ties(result.get(group) or [])
    result["coverage"] = coverage(result, pages)
    return result
