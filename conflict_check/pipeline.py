"""Article -> experts -> identity check -> evidence search -> verified ties -> Open Payments badges."""
from __future__ import annotations

import copy
import datetime
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .clients import exa_search, tavily_extract, tavily_search
from .extract import Expert, extract_experts
from .identity import identity_from_pick, resolve_identity
from .openpayments import badge_for_tie, datasets
from .reliability import rate_expert
from .session import Session
from .ties import classify_tie, find_ties, person_patterns, surname

MAX_EXPERTS = 5
SCOPE_NOTE = ("Shows connections disclosed elsewhere (papers, bios, filings) that this article didn't "
              "mention. It can't find ties that were never disclosed anywhere, and 'no confirmed "
              "connections' is a normal result.")

Event = Callable[[dict], None]


def load_article(s: Session, url: str | None, text: str | None) -> dict:
    if text and text.strip():
        return {"url": url, "text": text.strip(), "source": "pasted"}
    if not url:
        raise ValueError("Provide an article URL or paste its text.")
    if not re.match(r"https?://[^\s/]+\.[^\s/]+", url.strip(), re.I):
        raise ValueError("That doesn't look like an article URL (it should start with http:// or https://). Paste the text instead.")
    url = url.strip()
    results = tavily_extract(s, [url])
    if not results or not results[0].get("raw_content"):
        raise ValueError("Tavily couldn't extract that article; paste the text instead.")
    return {"url": url, "text": results[0]["raw_content"], "source": "tavily extract"}


def find_experts(s: Session, url: str | None = None, text: str | None = None) -> dict:
    """Step 1: load the article and list the experts for the user to review."""
    article = load_article(s, url, text)
    experts = extract_experts(article["text"])
    return {
        "article": {"url": article["url"], "source": article["source"], "chars": len(article["text"])},
        "text": article["text"],
        "experts": [dict(e.to_dict(), selected=e.kind == "expert" and i < MAX_EXPERTS)
                    for i, e in enumerate(experts)],
        "max_experts": MAX_EXPERTS,
        "calls": s.calls,
    }


def experts_from_request(items: list[dict]) -> list[tuple[Expert, str | None]]:
    """[{name, affiliation?, role?, orcid?}] as edited in the UI -> (Expert, picked ORCID)."""
    if not isinstance(items, list) or not all(isinstance(it, dict) for it in items):
        raise ValueError("experts must be a list of {name, affiliation} objects.")
    out, seen = [], set()
    for it in items:
        name = " ".join(str(it.get("name") or "").split())
        if len(name.split()) < 2:
            continue  # need a first and last name to search safely
        key = (name.casefold(), str(it.get("affiliation") or "").strip().casefold(), str(it.get("orcid") or "").strip())
        if key in seen:
            continue  # the same person listed twice would cost a second round of API calls
        seen.add(key)
        e = Expert(name=name, role=(it.get("role") or None), affiliation=str(it.get("affiliation") or "").strip() or None,
                   context=it.get("context") or "", signals=["user"] if it.get("added") else ["reviewed"])
        out.append((e, str(it.get("orcid") or "").strip() or None))
    return out


def with_highlights(hit: dict) -> str:
    """Page text plus any Exa highlight that the (length-capped) text doesn't already contain, such as a
    disclosure section at the end of a long paper. Highlights are sentences from the page, so quotes
    taken from them still verify against this text."""
    text = hit.get("text") or ""
    seen = " ".join(text.split())
    extra = [h.strip() for h in hit.get("highlights") or [] if h and " ".join(h.split()) not in seen]
    return text + ("\n\n" + "\n\n".join(extra) if extra else "")


def recent_cutoff() -> str:
    """Disclosures usually cover the last 36 months, so the second Exa query looks at the last three years."""
    return f"{datetime.date.today().year - 3}-01-01T00:00:00.000Z"


def gather_pages(s: Session, name: str, affiliation: str | None) -> list[dict]:
    """Exa research-paper searches (papers carry conflict statements) + Tavily web search.

    Three searches run side by side, because each finds people the others miss: Exa on the disclosure wording,
    Exa again restricted to recent papers that contain the person's name, and Tavily in plain language at
    advanced depth (its basic depth ignored most of the query)."""
    aff = affiliation or ""
    pages: list[dict] = []
    cutoff = recent_cutoff()
    with ThreadPoolExecutor(max_workers=3) as pool:
        exa_f = pool.submit(exa_search, s, f'"{name}" {aff} competing interests disclosure', 5, "research paper")
        recent_f = pool.submit(exa_search, s, f'"{name}" {aff} competing interests disclosure', 5, "research paper",
                               name, cutoff)
        tav_f = pool.submit(tavily_search, s, f"{name} {aff} financial disclosures conflict of interest "
                                              f"consulting advisory board", 5, True, "advanced")
        exa_hits, recent_hits, hits = exa_f.result(), recent_f.result(), tav_f.result()
    exa_hits = list({r.get("url"): r for r in [*exa_hits, *recent_hits] if r.get("url")}.values())  # one per page
    for r in exa_hits:
        pages.append({"url": r.get("url"), "title": r.get("title"), "text": with_highlights(r), "api": "exa",
                      "published": r.get("publishedDate")})
    seen = {p["url"] for p in pages}
    hits = [h for h in hits if h.get("url") and h["url"] not in seen][:5]
    for h in hits:
        if h.get("raw_content"):  # the search already returned the page text: no extract round trip
            pages.append({"url": h["url"], "title": h.get("title"), "text": h["raw_content"], "api": "tavily",
                          "published": h.get("published_date")})
    meta = {h["url"]: h for h in hits}
    for r in tavily_extract(s, [h["url"] for h in hits if not h.get("raw_content")]):  # only what's missing
        hit = meta.get(r.get("url")) or {}
        pages.append({"url": r.get("url"), "title": hit.get("title"), "text": r.get("raw_content") or "",
                      "api": "tavily", "published": hit.get("published_date")})
    # Which pages actually mention this person: coverage only counts those.
    strong = person_patterns(name)[0]
    for p in pages:
        p["about"] = bool(strong.search(p["text"]))
    return pages


# Open Payments lists drug and device makers. Universities, agencies and programs never appear in it.
NOT_PAYERS = re.compile(r"\b(?:university|universit\w+|institutes?|hospital|clinic|college|school|foundation|"
                        r"initiative|program|health|service|center|centre|division|department|society|"
                        r"association|nih|nhs|nsf|fda|cdc|award|council|academy)\b", re.I)
MAX_BADGES = 5  # each Open Payments lookup can take 30 s, so check only the best-evidenced ties


def badge_targets(ties: list[dict]) -> list[dict]:
    """The ties worth an Open Payments lookup: company-like names, best-evidenced first."""
    if not datasets():
        return []
    return sorted((t for t in ties if not NOT_PAYERS.search(t["org"])),
                  key=lambda t: len(t["evidence"]), reverse=True)[:MAX_BADGES]


def add_badges(s: Session, name: str, ties: list[dict], on_badge: Callable[[], None] | None = None) -> None:
    """Fills each tie's Open Payments badge. `on_badge` runs (from a worker thread) after each badge that
    actually found something, so the UI can show it without waiting for the slowest lookup."""
    for t in ties:
        t["open_payments"] = None
    todo = badge_targets(ties)

    def badge(t: dict) -> None:
        try:
            t["open_payments"] = badge_for_tie(s, name, t["org"])
        except Exception as err:  # a slow or failed badge never blocks the result
            t["open_payments"] = {"status": "error", "note": str(err)[:200]}
        if on_badge and t["open_payments"]:
            on_badge()

    if todo:
        with ThreadPoolExecutor(max_workers=len(todo)) as pool:
            list(pool.map(badge, todo))


def check_expert(s: Session, expert: Expert, article_text: str, picked_orcid: str | None = None,
                 on_partial: Callable[[dict], None] | None = None) -> dict:
    """With `on_partial`, the ties are reported as soon as the searches finish (flagged `badges_pending`),
    then the slow Open Payments badges are added and the finished result is returned."""
    out = expert.to_dict()
    # Identity first: the searches cost API credits (two Exa, one advanced Tavily), and ORCID answers in about
    # 0.3 s, so searching in parallel saved almost no time and wasted credits on every unconfirmed expert.
    ident = (identity_from_pick(s, expert.name, picked_orcid) if picked_orcid
             else resolve_identity(s, expert.name, expert.affiliation))
    out["identity"] = ident
    if ident["status"] != "confirmed":
        out.update(status="identity_not_confirmed", ties=[], disclosed=[])
        return out
    try:
        pages = gather_pages(s, expert.name, expert.affiliation)
    except Exception as err:  # keep the confirmed identity visible even if the search fails
        out.update(status="error", error=str(err), ties=[], disclosed=[])
        return out
    last = surname(expert.name)  # skips suffixes: "John Smith Jr" -> Smith, matching how the article refers to him
    ties = [classify_tie(t, article_text, last)
            for t in find_ties(pages, expert.name, exclude_orgs=[expert.affiliation])]
    out["pages_checked"] = len(pages)
    out["ties"] = [t for t in ties if not t["disclosed_in_article"]]
    out["disclosed"] = [t for t in ties if t["disclosed_in_article"]]
    out["status"] = "connections_found" if out["ties"] else "no_confirmed_connections"
    # Scores every tie, re-orders out["ties"] / out["disclosed"] in place and adds out["coverage"]. With
    # on_partial, the ties go out first (badges pending); Open Payments then adds a bonus and we re-rate.
    if on_partial and badge_targets(ties):
        for t in ties:
            t["open_payments"] = None
        rate_expert(out, pages)
        on_partial(dict(copy.deepcopy(out), badges_pending=True))
    lock = threading.Lock()

    def badge_arrived() -> None:  # one badge is in: re-rate and show it now, others are still pending
        if on_partial:
            with lock:
                rate_expert(out, pages)
                on_partial(dict(copy.deepcopy(out), badges_pending=True))

    add_badges(s, expert.name, ties, badge_arrived)
    with lock:
        rate_expert(out, pages)
    return out


def check_article(s: Session, url: str | None = None, text: str | None = None,
                  experts: list[dict] | None = None, max_experts: int = MAX_EXPERTS,
                  on_event: Event | None = None) -> dict:
    """Step 2. `experts` is the reviewed list from the UI; if omitted, the extractor's top picks are used."""
    emit = on_event or (lambda ev: None)
    article = load_article(s, url, text)
    if experts is not None:
        todo = experts_from_request(experts)
        skipped = [e.name for e, _ in todo[max_experts:]]
    else:
        found = [e for e in extract_experts(article["text"]) if e.kind == "expert"]
        todo = [(e, None) for e in found]
        skipped = [e.name for e in found[max_experts:]]
    todo = todo[:max_experts]
    emit({"type": "start", "experts": [e.name for e, _ in todo]})

    def run_one(item: tuple[Expert, str | None]) -> dict:
        e, orcid = item
        early = []

        def partial(r: dict) -> None:
            emit({"type": "update" if early else "expert", "expert": r})  # only the first counts as "arrived"
            early.append(r)

        try:
            r = check_expert(s, e, article["text"], orcid, on_partial=partial)
        except Exception as err:  # keep going: one failed expert shouldn't sink the report
            r = e.to_dict()
            r.update(status="error", error=str(err), ties=[], disclosed=[])
        emit({"type": "update" if early else "expert", "expert": r})
        return r

    # Experts are independent, so check them side by side (results keep the reviewed order).
    if todo:
        with ThreadPoolExecutor(max_workers=len(todo)) as pool:
            results = list(pool.map(run_one, todo))
    else:
        results = []

    return {
        "article": {"url": article["url"], "source": article["source"], "chars": len(article["text"])},
        "experts": results,
        "skipped_experts": skipped,
        "scope_note": SCOPE_NOTE,
        "replay": s.replay,
        "calls": s.calls,
    }
