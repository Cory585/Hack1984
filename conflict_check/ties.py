"""Find funding / employment / consulting ties in fetched pages.

Hard rule: a tie exists only if a fetched page contains a clause that names both
the person and the organization next to a tie keyword. The quote is copied from
the page and re-verified by verify_quote before it is shown. No model states a tie.
"""
from __future__ import annotations

import re

TIE = re.compile(
    r"\b(consult(?:ant|ing|ancy)?(?:\s+fees)?|advisory\s+(?:board|committee)s?|advis[eo]r|"
    r"speakers?['’]?\s+(?:bureau|fees)|honorari(?:a|um)|grants?|research\s+(?:funding|support)|"
    r"funded\s+by|funding\s+from|received\s+(?:fees|funding|payments|support)|employee|employed\s+by|"
    r"stock|shares|equity|board\s+of\s+directors|patents?|royalt(?:y|ies)|co-?founder|founder|"
    r"paid\s+by|sponsored\s+by)\b",
    re.I,
)
ORG_RUN = re.compile(r"(?:[A-Z][\w&'’\-]*)(?:\s+(?:of|for|&|[A-Z][\w&'’\-]*)){0,6}")
ABBREV = re.compile(r"(?:\b(?:Dr|Prof|Mr|Ms|Mrs|St|Inc|Co|Corp|Ltd|al|vs|No)|\b[A-Z])\.$")
ORG_STOP = {
    "the", "he", "she", "they", "dr", "prof", "professor", "disclosures", "disclosure", "competing",
    "conflict", "conflicts", "interests", "interest", "none", "funding", "author", "authors", "in", "this",
    "consulting", "grants", "grant", "honoraria", "stock", "she has", "he has", "declaration", "all",
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
    "november", "december", "outside", "no", "other", "financial", "potential",
}
GENERIC = {
    "university", "institute", "institutes", "inc", "corp", "corporation", "company", "co", "ltd", "llc",
    "pharmaceuticals", "pharmaceutical", "pharma", "therapeutics", "health", "healthcare", "foundation",
    "association", "society", "group", "labs", "laboratories", "center", "centre", "national", "of",
    "for", "the", "and", "school", "college", "medical", "medicine", "hospital", "research", "sciences",
}


def norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def verify_quote(quote: str, page_text: str) -> bool:
    return bool(quote) and norm_ws(quote) in norm_ws(page_text)


def split_clauses(text: str) -> list[str]:
    raw = re.split(r"(?<=[.!?;])\s+|\n+", text)
    out: list[str] = []
    for piece in raw:
        if out and ABBREV.search(out[-1]):
            out[-1] = f"{out[-1]} {piece}"
        elif piece.strip():
            out.append(piece)
    return [c.strip() for c in out if c.strip()]


def distinctive_tokens(org: str) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z][\w'’\-]+", org) if w.lower() not in GENERIC and len(w) >= 3]


def mentions_org(org: str, text: str) -> bool:
    toks = distinctive_tokens(org)
    return bool(toks) and all(re.search(rf"\b{re.escape(t)}\b", text, re.I) for t in toks)


def same_org(a: str, b: str) -> bool:
    ta, tb = {t.lower() for t in distinctive_tokens(a)}, {t.lower() for t in distinctive_tokens(b)}
    return bool(ta and tb) and (ta <= tb or tb <= ta)


def person_patterns(name: str) -> tuple[re.Pattern, re.Pattern]:
    """(strong, clause): strong proves the page is about this person; clause attributes a clause."""
    parts = name.split()
    first, last = parts[0], parts[-1]
    L = re.escape(last)
    strong = re.compile(rf"\b{re.escape(first)}\s+(?:[A-Z]\.?\s+)?{L}\b|\b{first[0]}\.\s*(?:[A-Z]\.\s*)?{L}\b|\b{L},\s+{re.escape(first)}\b|\b{L},?\s+{first[0]}\.?(?:[A-Z]\.?)?(?![a-z])")
    initials = r"\.?\s?".join(p[0] for p in parts)
    clause = re.compile(rf"\b{L}\b|(?<![A-Za-z]){initials}\.?(?![A-Za-z])")
    return strong, clause


def orgs_in(clause: str, person: str) -> list[str]:
    person_toks = {t.lower() for t in person.split()}
    out = []
    for m in ORG_RUN.finditer(clause):
        org = m.group(0).strip(" .,")
        org = re.sub(r"\s+(?:of|for|&)$", "", org)
        org = re.sub(r"^The\s+", "", org)
        toks = org.split()
        if not toks or org.lower() in ORG_STOP or toks[0].lower().rstrip(".") in ORG_STOP and len(toks) == 1:
            continue
        if any(t.lower().strip(".,") in person_toks for t in toks):
            continue
        if re.fullmatch(r"(?:[A-Z]\.?){1,4}", org):  # bare initials
            continue
        if not distinctive_tokens(org):
            continue
        out.append(org)
    return out


def find_ties(pages: list[dict], name: str, exclude_orgs: list[str] | None = None) -> list[dict]:
    """pages: [{url, title, text, api}] -> deduped ties, each with verified evidence."""
    exclude_orgs = [o for o in (exclude_orgs or []) if o]
    strong, clause_pat = person_patterns(name)
    ties: dict[str, dict] = {}
    for page in pages:
        text = page.get("text") or ""
        if not strong.search(text):
            continue  # page isn't demonstrably about this person
        for clause in split_clauses(text):
            kw = TIE.search(clause)
            if not kw or not clause_pat.search(clause):
                continue
            for org in orgs_in(clause, name):
                if any(same_org(org, ex) for ex in exclude_orgs):
                    continue
                quote = clause[:600]
                if not verify_quote(quote, text):
                    continue
                key = " ".join(t.lower() for t in distinctive_tokens(org))
                tie = ties.setdefault(key, {"org": org, "relation": kw.group(1).lower(), "evidence": []})
                if not any(ev["url"] == page.get("url") for ev in tie["evidence"]):
                    tie["evidence"].append({"url": page.get("url"), "title": page.get("title"),
                                            "api": page.get("api"), "quote": quote, "verified": True})
    return list(ties.values())


def classify_tie(tie: dict, article: str, surname: str) -> dict:
    """disclosed: the article names the org in a paragraph that mentions the expert.
    related: the article names the org anywhere (it's part of this story)."""
    paras = [p for p in re.split(r"\n\s*\n|\n", article) if re.search(rf"\b{re.escape(surname)}\b", p)]
    tie["disclosed_in_article"] = any(mentions_org(tie["org"], p) for p in paras)
    tie["related_to_story"] = mentions_org(tie["org"], article)
    return tie
