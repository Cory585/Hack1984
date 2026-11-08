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


SCHOLARLY = re.compile(
    r"(?:^|\.)(?:doi\.org|ncbi\.nlm\.nih\.gov|europepmc\.org|pubmed\.gov|sciencedirect\.com|springer\.com|wiley\.com|"
    r"nature\.com|thelancet\.com|jamanetwork\.com|nejm\.org|bmj\.com|plos\.org|frontiersin\.org|mdpi\.com|arxiv\.org|"
    r"biorxiv\.org|medrxiv\.org|oup\.com|tandfonline\.com|sagepub\.com|cell\.com|karger\.com|ahajournals\.org|"
    r"acpjournals\.org|cmaj\.ca|biomedcentral\.com|semanticscholar\.org)$")


def source_kind(ev: dict) -> str:
    """'paper' needs evidence of one: a scholarly host, or a page with a DOI and a conflict-of-interest
    heading (ev['paper_signals'], set by ties.find_ties). Which API found the page doesn't decide it:
    Exa's 'research paper' category can still return blogs and news."""
    host = (urllib.parse.urlparse(ev.get("url") or "").hostname or "").lower()
    if SCHOLARLY.search(host) or ev.get("paper_signals"):
        return "paper"
    return "institution" if INSTITUTIONAL.search(host) else "web"


def source_year(evidence: list[dict], now: int) -> tuple[int | None, str | None]:
    """(year, how): the publication date the search API reported (Exa publishedDate, Tavily
    published_date) when there is one; otherwise a year in the page title or link. Years inside the
    quote are never used: 'since 2012' or 'founded in 2023' say nothing about how old the source is."""
    published = [int(m.group(1)) for ev in evidence
                 if (m := re.match(r"(199\d|20\d\d)", str(ev.get("published") or ""))) and int(m.group(1)) <= now]
    if published:
        return max(published), "published"
    years = [int(y) for ev in evidence for field in ("title", "url")
             for y in YEAR.findall(ev.get(field) or "") if 1990 <= int(y) <= now]
    return (max(years), "dated") if years else (None, None)


def newest_year(evidence: list[dict], now: int) -> int | None:
    return source_year(evidence, now)[0]


def _factor(key: str, value: float, note: str) -> dict:
    # Values stay unrounded here; scores are computed from these and only the display copy is rounded.
    return {"key": key, "value": value, "weight": WEIGHTS.get(key), "note": note}


def _weighted_score(factors: list[dict], bonus: int = 0) -> int:
    total = sum(f["weight"] for f in factors)
    score = max(0, min(100, round_half_up(100 * sum(f["value"] * f["weight"] for f in factors) / total + bonus)))
    for f in factors:
        f["value"] = round(f["value"], 3)  # display only, after the score is computed
    return score


def score_tie(tie: dict, identity: dict | None, now: int | None = None) -> dict:
    """Adds tie['reliability'] = {score, label, factors, bonus} and returns it."""
    now = now or datetime.date.today().year
    evidence = tie.get("evidence") or []
    if not evidence:  # same shape as a normal rating, so callers never need a special case
        rel = {"score": 0, "label": "Weak", "factors": [], "bonus": 0, "sites": 0, "best_source": None,
               "note": "No evidence."}
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
    year, how = source_year(evidence, now)
    if year is None:
        f_rec = _factor("recency", .7, "no date found")
    else:
        age = now - year
        f_rec = _factor("recency", 1.0 if age <= 3 else .75 if age <= 6 else .5,
                        f"published {year}" if how == "published" else f"dated {year} (title or link)")
    org = (tie.get("org") or "").strip()
    acronym = bool(re.fullmatch(r"[A-Z0-9&]{2,5}", org))
    f_org = _factor("organization", .8 if acronym else 1.0, "acronym only" if acronym else "full name")

    factors = [f_ident, f_attr, f_src, f_corr, f_word, f_rec, f_org]
    op = tie.get("open_payments") or {}
    bonus = OP_BONUS if op.get("status") == "name_match" else 0
    score = _weighted_score(factors, bonus)
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
    """How thorough the check was. None when identity wasn't confirmed or the search failed (the
    pipeline only rates successful searches, but this is public, so it guards anyway).
    Only pages that mention the person count (page['about'], set by the pipeline): ten pages about
    other people with a similar name are no evidence of a thorough search."""
    ident = result.get("identity") or {}
    if ident.get("status") != "confirmed" or result.get("status") == "error":
        return None
    about = [p for p in pages if p.get("about", True)]
    n = len(about)
    channels = {p.get("api") for p in about if p.get("api")}
    factors = [
        {"key": "identity", "value": IDENTITY.get(ident.get("by"), .5), "weight": .4,
         "note": {"orcid": "confirmed by ORCID", "user": "picked by a person"}.get(ident.get("by"), "identity unknown")},
        {"key": "pages", "value": 0 if n == 0 else .5 if n <= 2 else .8 if n <= 5 else 1.0, "weight": .35,
         "note": f"{n} of {len(pages)} pages found mention them"},
        {"key": "channels", "value": 1.0 if {"exa", "tavily"} <= channels else .6 if channels else 0, "weight": .25,
         "note": ("both Exa and Tavily found pages about them" if {"exa", "tavily"} <= channels
                  else f"only {next(iter(channels)).capitalize()} found pages about them" if channels
                  else "no search found pages about them")},
    ]
    score = _weighted_score(factors)
    return {"score": score, "label": label(score), "factors": factors}


def rate_expert(result: dict, pages: list[dict], now: int | None = None) -> dict:
    """Score every tie (shown and disclosed), order them, and add the expert's coverage rating."""
    for group in ("ties", "disclosed"):
        for t in result.get(group) or []:
            score_tie(t, result.get("identity"), now)
        result[group] = order_ties(result.get(group) or [])
    result["coverage"] = coverage(result, pages)
    return result
