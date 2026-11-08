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


def open_payments_query(s: Session, dataset_id: str, year: str, first: str, last: str,
                        manufacturer_contains: str, limit: int = 500) -> list[dict]:
    """CMS Open Payments general payments for one physician name from one manufacturer."""
    cond = [
        {"property": "covered_recipient_last_name", "value": last.upper(), "operator": "="},
        {"property": "covered_recipient_first_name", "value": first.upper(), "operator": "="},
        {"property": "applicable_manufacturer_or_applicable_gpo_making_payment_name",
         "value": manufacturer_contains.upper(), "operator": "contains"},
    ]
    data = s.request(
        "openpayments", f"open payments {year}: {first} {last} <- {manufacturer_contains}", "POST",
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
