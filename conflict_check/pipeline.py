"""Article -> experts -> identity check -> evidence search -> verified ties."""
from __future__ import annotations

from .clients import exa_search, tavily_extract, tavily_search
from .extract import extract_experts
from .identity import resolve_identity
from .session import Session
from .ties import classify_tie, find_ties

MAX_EXPERTS = 5
SCOPE_NOTE = ("Shows connections disclosed elsewhere (papers, bios, filings) that this article didn't "
              "mention. It can't find ties that were never disclosed anywhere, and 'no confirmed "
              "connections' is a normal result.")


def load_article(s: Session, url: str | None, text: str | None) -> dict:
    if text and text.strip():
        return {"url": url, "text": text.strip(), "source": "pasted"}
    if not url:
        raise ValueError("Provide an article URL or paste its text.")
    results = tavily_extract(s, [url])
    if not results or not results[0].get("raw_content"):
        raise ValueError("Tavily couldn't extract that article; paste the text instead.")
    return {"url": url, "text": results[0]["raw_content"], "source": "tavily extract"}


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


def check_expert(s: Session, expert, article_text: str) -> dict:
    out = expert.to_dict()
    ident = resolve_identity(s, expert.name, expert.affiliation)
    out["identity"] = ident
    if ident["status"] != "confirmed":
        out.update(status="identity_not_confirmed", ties=[], disclosed=[])
        return out
    pages = gather_pages(s, expert.name, expert.affiliation)
    surname = expert.name.split()[-1]
    ties = [classify_tie(t, article_text, surname)
            for t in find_ties(pages, expert.name, exclude_orgs=[expert.affiliation])]
    out["pages_checked"] = len(pages)
    out["ties"] = [t for t in ties if not t["disclosed_in_article"]]
    out["disclosed"] = [t for t in ties if t["disclosed_in_article"]]
    out["ties"].sort(key=lambda t: (not t["related_to_story"], t["org"]))
    out["status"] = "connections_found" if out["ties"] else "no_confirmed_connections"
    return out


def check_article(s: Session, url: str | None = None, text: str | None = None,
                  max_experts: int = MAX_EXPERTS) -> dict:
    article = load_article(s, url, text)
    all_experts = extract_experts(article["text"])
    results = []
    for e in all_experts[:max_experts]:
        try:
            results.append(check_expert(s, e, article["text"]))
        except Exception as err:  # keep going: one failed expert shouldn't sink the report
            r = e.to_dict()
            r.update(status="error", error=str(err), ties=[], disclosed=[])
            results.append(r)
    return {
        "article": {"url": article["url"], "source": article["source"], "chars": len(article["text"])},
        "experts": results,
        "skipped_experts": [e.name for e in all_experts[max_experts:]],
        "scope_note": SCOPE_NOTE,
        "replay": s.replay,
        "calls": s.calls,
    }
