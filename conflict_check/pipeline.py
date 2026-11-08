"""Article -> experts -> identity check -> evidence search -> verified ties -> Open Payments badges."""
from __future__ import annotations

from typing import Callable

from .clients import exa_search, tavily_extract, tavily_search
from .extract import Expert, extract_experts
from .identity import identity_from_pick, resolve_identity
from .openpayments import badge_for_tie
from .session import Session
from .reliability import rate_expert
from .ties import classify_tie, find_ties

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
    out = []
    for it in items:
        name = " ".join((it.get("name") or "").split())
        if len(name.split()) < 2:
            continue  # need a first and last name to search safely
        e = Expert(name=name, role=(it.get("role") or None), affiliation=(it.get("affiliation") or "").strip() or None,
                   context=it.get("context") or "", signals=["user"] if it.get("added") else ["reviewed"])
        out.append((e, (it.get("orcid") or "").strip() or None))
    return out


def gather_pages(s: Session, name: str, affiliation: str | None) -> list[dict]:
    """Exa research-paper search (papers carry conflict statements) + Tavily web search/extract."""
    aff = affiliation or ""
    pages: list[dict] = []
    for r in exa_search(s, f'"{name}" {aff} competing interests disclosure', 5, "research paper"):
        pages.append({"url": r.get("url"), "title": r.get("title"), "text": r.get("text") or "", "api": "exa"})
    hits = tavily_search(s, f'"{name}" {aff} consultant OR "advisory board" OR "conflict of interest"', 5)
    seen = {p["url"] for p in pages}
    urls = [h["url"] for h in hits if h.get("url") and h["url"] not in seen][:5]
    titles = {h.get("url"): h.get("title") for h in hits}
    for r in tavily_extract(s, urls):
        pages.append({"url": r.get("url"), "title": titles.get(r.get("url")),
                      "text": r.get("raw_content") or "", "api": "tavily"})
    return pages


def add_badges(s: Session, name: str, ties: list[dict]) -> None:
    for t in ties:
        try:
            t["open_payments"] = badge_for_tie(s, name, t["org"])
        except Exception as err:  # a slow or failed badge never blocks the result
            t["open_payments"] = {"status": "error", "note": str(err)[:200]}


def check_expert(s: Session, expert: Expert, article_text: str, picked_orcid: str | None = None) -> dict:
    out = expert.to_dict()
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
    surname = expert.name.split()[-1]
    ties = [classify_tie(t, article_text, surname)
            for t in find_ties(pages, expert.name, exclude_orgs=[expert.affiliation])]
    add_badges(s, expert.name, ties)
    out["pages_checked"] = len(pages)
    out["ties"] = [t for t in ties if not t["disclosed_in_article"]]
    out["disclosed"] = [t for t in ties if t["disclosed_in_article"]]
    out["status"] = "connections_found" if out["ties"] else "no_confirmed_connections"
    rate_expert(out, pages)  # reliability score per tie, deterministic order, coverage rating
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

    results = []
    for e, orcid in todo:
        try:
            r = check_expert(s, e, article["text"], orcid)
        except Exception as err:  # keep going: one failed expert shouldn't sink the report
            r = e.to_dict()
            r.update(status="error", error=str(err), ties=[], disclosed=[])
        results.append(r)
        emit({"type": "expert", "expert": r})

    return {
        "article": {"url": article["url"], "source": article["source"], "chars": len(article["text"])},
        "experts": results,
        "skipped_experts": skipped,
        "scope_note": SCOPE_NOTE,
        "replay": s.replay,
        "calls": s.calls,
    }
