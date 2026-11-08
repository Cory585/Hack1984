"""Built-in demo: the real pipeline, run against fictional data with realistic delays.

Every person, company and paper here is made up. Nothing goes over the network,
so a stage demo works with no API keys and no Wi-Fi. The scripted cases cover
each result state:
  * Maren Okafor  - confirmed by ORCID; ties found in a paper's disclosure and a
                    bio page; one tie confirmed by an Open Payments badge
  * Tobias Wren   - no ORCID match at his affiliation; two name-only candidates
                    to pick from ("This is them" -> confirmed, one small tie)
  * Anna Price    - a company spokesperson, set aside as not independent
"""
from __future__ import annotations

import json
import random
import time
import urllib.parse

from .session import Session

ARTICLE = """New pill cuts heart attack risk in trial, but experts urge caution

A once-daily pill made by Veltrix Pharmaceuticals lowered the risk of heart attack by 18 percent in a two-year trial of 9,400 adults, researchers reported Tuesday in the Lakeside Medical Journal.

"This is a meaningful step for patients who can't tolerate statins," said Maren Okafor, a cardiologist at Lakeside University. Okafor added that the results still need to be replicated in more diverse groups.

Dr. Tobias Wren, an epidemiologist at the Northfield Institute of Public Health, was more cautious. "The absolute benefit is small, about one heart attack prevented for every 120 people treated," Wren said.

Anna Price, a spokesperson for Veltrix Pharmaceuticals, said the company would apply for approval next year.

The trial was funded by Veltrix Pharmaceuticals.
"""

OKAFOR_ORCID = "0000-0002-1825-0097"
WREN_ORCIDS = ("0000-0003-4200-1001", "0000-0003-4200-1002")

PAPER = {
    "url": "https://journals.example.org/jcc/okafor-2025-pcsk9",
    "title": "Long-term outcomes of oral PCSK9 inhibition: a cohort study · Journal of Cardiac Care",
    "text": ("Okafor M, Lee J, Haddad O. Long-term outcomes of oral PCSK9 inhibition: a cohort study. "
             "Journal of Cardiac Care. 2025. doi:10.5555/jcc.2025.0142\n"
             "Competing interests: M.O. reports consulting fees from Veltrix Pharmaceuticals and serves on a "
             "scientific advisory board for Halden Biotech; J.L. reports grants from Corvane Biologics. "
             "O.H. declares no competing interests."),
}
BIO = {
    "url": "https://lakeside.example.edu/people/maren-okafor",
    "title": "Maren Okafor, MD · Lakeside University Heart Center",
    "text": ("Maren Okafor, MD, is a cardiologist at Lakeside University. Her research focuses on lipid-lowering "
             "therapy. She has received speaker fees from Veltrix Pharmaceuticals and holds stock in Orbis Labs."),
}
WREN_BIO = {
    "url": "https://northfield.example.org/staff/tobias-wren",
    "title": "Tobias Wren, PhD · Northfield Institute",
    "text": ("Tobias Wren is an epidemiologist at the Northfield Institute. "
             "Wren has received research funding from the Brightwater Health Trust."),
}
PAGES = {p["url"]: p for p in (PAPER, BIO, WREN_BIO)}


def _orcid(url: str) -> dict:
    if url.endswith("/personal-details"):
        oid = url.rsplit("/", 2)[-2]
        name = ("Maren", "Okafor") if oid == OKAFOR_ORCID else ("Tobias", "Wren") if oid in WREN_ORCIDS else ("Ada", "Lin")
        return {"name": {"given-names": {"value": name[0]}, "family-name": {"value": name[1]}}}
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("q", [""])[0]
    if "Okafor" in q:
        return {"num-found": 1, "expanded-result": [
            {"orcid-id": OKAFOR_ORCID, "given-names": "Maren", "family-names": "Okafor",
             "institution-name": ["Lakeside University"]}]}
    if "Wren" in q and "affiliation-org-name" not in q:
        return {"num-found": 2, "expanded-result": [
            {"orcid-id": WREN_ORCIDS[0], "given-names": "Tobias", "family-names": "Wren",
             "institution-name": ["Northfield Institute"]},
            {"orcid-id": WREN_ORCIDS[1], "given-names": "Tobias", "family-names": "Wren",
             "institution-name": ["University of Elsewhere"]}]}
    return {"num-found": 0, "expanded-result": None}


def _exa(body: dict) -> dict:
    q = body.get("query", "")
    hits = [PAPER] if "Okafor" in q else []
    return {"results": [{"url": p["url"], "title": p["title"], "text": p["text"],
                         "publishedDate": "2025-06-12T00:00:00.000Z"} for p in hits]}


def _tavily_search(body: dict) -> dict:
    q = body.get("query", "")
    hits = [BIO] if "Okafor" in q else [WREN_BIO] if "Wren" in q else []
    return {"results": [{"url": p["url"], "title": p["title"]} for p in hits]}


def _tavily_extract(body: dict) -> dict:
    return {"results": [{"url": u, "raw_content": PAGES[u]["text"]} for u in body.get("urls", []) if u in PAGES]}


def _open_payments(body: dict) -> dict:
    cond = {c["property"]: c["value"] for c in body.get("conditions", [])}
    payer = cond.get("applicable_manufacturer_or_applicable_gpo_making_payment_name", "")
    if cond.get("covered_recipient_last_name") != "OKAFOR" or "VELTRIX" not in payer:
        return {"results": []}
    rows = []
    for amount, nature, date in (("12500.00", "Consulting Fee", "03/14/2025"), ("8750.00", "Consulting Fee", "09/02/2025"),
                                 ("4200.00", "Compensation for services other than consulting", "05/20/2025"),
                                 ("86.40", "Food and Beverage", "05/20/2025")):
        rows.append({"covered_recipient_npi": "1999999999", "covered_recipient_first_name": "MAREN",
                     "covered_recipient_last_name": "OKAFOR", "recipient_city": "LAKESIDE", "recipient_state": "MN",
                     "covered_recipient_specialty_1": "Allopathic & Osteopathic Physicians|Cardiovascular Disease",
                     "applicable_manufacturer_or_applicable_gpo_making_payment_name": "VELTRIX PHARMACEUTICALS INC.",
                     "total_amount_of_payment_usdollars": amount, "nature_of_payment_or_transfer_of_value": nature,
                     "date_of_payment": date})
    return {"results": rows}


def make_fetcher(delay: tuple[float, float] = (0.25, 0.9)):
    """A Session fetcher that answers from the fictional data above, after a short pause."""
    def fetch(method: str, url: str, headers: dict, body):
        if delay[1] > 0:
            time.sleep(random.uniform(*delay))
        if "orcid.org" in url:
            data = _orcid(url)
        elif "api.exa.ai" in url:
            data = _exa(body or {})
        elif url.endswith("/search"):
            data = _tavily_search(body or {})
        elif url.endswith("/extract"):
            if any(u not in PAGES for u in (body or {}).get("urls", [])):
                return {"results": [{"url": u, "raw_content": ARTICLE} for u in body["urls"]]}  # the article itself
            data = _tavily_extract(body or {})
        elif "openpaymentsdata.cms.gov" in url:
            data = _open_payments(body or {})
        else:
            raise RuntimeError(f"demo has no data for {url}")
        return json.loads(json.dumps(data))  # fresh copy per call
    return fetch


def demo_session(delay: tuple[float, float] = (0.25, 0.9), on_call=None) -> Session:
    """A throwaway session: fictional answers, no disk cache (nothing left behind), never replay mode."""
    return Session(cache_dir=None, replay=False, fetcher=make_fetcher(delay),
                   tavily_key="demo", exa_key="demo", on_call=on_call)
