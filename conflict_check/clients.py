"""Thin clients for Tavily, Exa and the ORCID public API. All calls go through Session."""
from __future__ import annotations

import urllib.parse

from .session import Session

TAVILY = "https://api.tavily.com"
EXA = "https://api.exa.ai"
ORCID = "https://pub.orcid.org/v3.0"


def tavily_search(s: Session, query: str, max_results: int = 5) -> list[dict]:
    data = s.request(
        "tavily", f"search: {query}", "POST", f"{TAVILY}/search",
        {"Authorization": f"Bearer {s.key('tavily')}"},
        {"query": query, "max_results": max_results, "search_depth": "basic"},
    )
    return data.get("results") or []


def tavily_extract(s: Session, urls: list[str]) -> list[dict]:
    """Returns [{url, raw_content}] for the pages Tavily could fetch."""
    if not urls:
        return []
    data = s.request(
        "tavily", f"extract: {len(urls)} url(s)", "POST", f"{TAVILY}/extract",
        {"Authorization": f"Bearer {s.key('tavily')}"},
        {"urls": urls},
    )
    return data.get("results") or []


def exa_search(s: Session, query: str, num_results: int = 5, category: str | None = None) -> list[dict]:
    """Exa search with page text included. category e.g. 'research paper'."""
    body = {
        "query": query,
        "type": "auto",
        "numResults": num_results,
        "contents": {"text": {"maxCharacters": 20000}},
    }
    if category:
        body["category"] = category
    data = s.request(
        "exa", f"search{' [' + category + ']' if category else ''}: {query}", "POST", f"{EXA}/search",
        {"x-api-key": s.key("exa")}, body,
    )
    return data.get("results") or []


def orcid_search(s: Session, given: str, family: str, affiliation: str | None = None) -> dict:
    q = f'given-names:"{given}" AND family-name:"{family}"'
    if affiliation:
        q += f' AND affiliation-org-name:"{affiliation}"'
    url = f"{ORCID}/expanded-search/?" + urllib.parse.urlencode({"q": q, "rows": 10})
    label = f"orcid: {given} {family}" + (f" @ {affiliation}" if affiliation else "")
    return s.request("orcid", label, "GET", url, {"Accept": "application/json"})
