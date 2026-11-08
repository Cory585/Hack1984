"""Thin clients for Tavily, Exa and the ORCID public API. All calls go through Session."""
from __future__ import annotations

import urllib.parse

from .session import Session

TAVILY = "https://api.tavily.com"
EXA = "https://api.exa.ai"
ORCID = "https://pub.orcid.org/v3.0"


def tavily_search(s: Session, query: str, max_results: int = 5, raw_content: bool = False,
                  depth: str = "basic") -> list[dict]:
    """raw_content=True returns each page's text with the hits, saving a separate extract call.
    depth="advanced" costs 2 credits instead of 1 but ranks pages by relevance to the whole query."""
    body = {"query": query, "max_results": max_results, "search_depth": depth}
    if raw_content:
        body["include_raw_content"] = True
    data = s.request(
        "tavily", f"search: {query}", "POST", f"{TAVILY}/search",
        {"Authorization": f"Bearer {s.key('tavily')}"},
        body,
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


HIGHLIGHT_QUERY = ("competing interests, conflicts of interest, disclosures: consulting fees, advisory board, "
                   "grants, honoraria, stock, employee")


def exa_search(s: Session, query: str, num_results: int = 5, category: str | None = None,
               include_text: str | None = None, since: str | None = None) -> list[dict]:
    """Exa search with page text included. category e.g. 'research paper'."""
    body = {
        "query": query,
        "type": "auto",
        "numResults": num_results,
        # Text is cut at 20,000 characters, which drops the disclosure section at the end of long papers
        # (half of cached results were cut). Highlights are Exa's best-matching sentences from the whole page.
        "contents": {"text": {"maxCharacters": 20000},
                     "highlights": {"query": HIGHLIGHT_QUERY, "numSentences": 4, "highlightsPerUrl": 3}},
    }
    if category:
        body["category"] = category
    if include_text:  # only pages that contain this exact string (e.g. the expert's name)
        body["includeText"] = [include_text]
    if since:  # ISO date: only pages published on or after it
        body["startPublishedDate"] = since
    data = s.request(
        "exa", f"search{' [' + category + ']' if category else ''}{' recent' if since else ''}: {query}", "POST", f"{EXA}/search",
        {"x-api-key": s.key("exa")}, body,
    )
    return data.get("results") or []


def orcid_person(s: Session, orcid: str) -> dict:
    """Public personal-details record, used to check a user-picked ORCID iD."""
    return s.request("orcid", f"orcid record: {orcid}", "GET",
                     f"{ORCID}/{urllib.parse.quote(orcid)}/personal-details", {"Accept": "application/json"})


OPEN_PAYMENTS = "https://openpaymentsdata.cms.gov/api/1/datastore/query"
OP_FIELDS = [
    "covered_recipient_npi", "covered_recipient_first_name", "covered_recipient_last_name",
    "recipient_city", "recipient_state", "covered_recipient_specialty_1",
    "applicable_manufacturer_or_applicable_gpo_making_payment_name",
    "total_amount_of_payment_usdollars", "nature_of_payment_or_transfer_of_value", "date_of_payment",
]


NPPES = "https://npiregistry.cms.hhs.gov/api/"


def nppes_npis(s: Session, first: str, last: str, limit: int = 11) -> dict:
    """US clinicians with this exact name from the NPI registry (about 0.2 s). `count` is capped at `limit`,
    so ask for one more than you will accept.
    Open Payments is only fast when queried by NPI: name filters scan millions of rows (20-80 s)."""
    url = f"{NPPES}?" + urllib.parse.urlencode({
        "version": "2.1", "first_name": first, "last_name": last,
        "enumeration_type": "NPI-1", "limit": limit})
    data = s.request("nppes", f"npi registry: {first} {last}", "GET", url, {})
    found = []
    for r in data.get("results") or []:
        tax = next((t for t in r.get("taxonomies") or [] if t.get("primary")), None) or {}
        found.append({"npi": str(r.get("number")), "state": tax.get("state"), "specialty": tax.get("desc")})
    return {"count": data.get("result_count") or 0, "npis": found}


def open_payments_query(s: Session, dataset_id: str, year: str, npis: list[str],
                        manufacturer_contains: str, limit: int = 500) -> list[dict]:
    """CMS Open Payments general payments to these NPIs from one manufacturer (about 1-2 s)."""
    cond = [
        {"property": "covered_recipient_npi", "value": npis if len(npis) > 1 else npis[0],
         "operator": "in" if len(npis) > 1 else "="},
        {"property": "applicable_manufacturer_or_applicable_gpo_making_payment_name",
         "value": manufacturer_contains.upper(), "operator": "contains"},
    ]
    data = s.request(
        "openpayments", f"open payments {year}: NPI {','.join(npis)} <- {manufacturer_contains}", "POST",
        f"{OPEN_PAYMENTS}/{dataset_id}/0", {},
        {"conditions": cond, "limit": limit, "results": True, "count": False, "properties": OP_FIELDS},
    )
    return data.get("results") or []


def orcid_search(s: Session, given: str, family: str, affiliation: str | None = None) -> dict:
    q = f'given-names:"{given}" AND family-name:"{family}"'
    if affiliation:
        q += f' AND affiliation-org-name:"{affiliation}"'
    url = f"{ORCID}/expanded-search/?" + urllib.parse.urlencode({"q": q, "rows": 10})
    label = f"orcid: {given} {family}" + (f" @ {affiliation}" if affiliation else "")
    return s.request("orcid", label, "GET", url, {"Accept": "application/json"})
