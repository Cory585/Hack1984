"""Find funding / employment / consulting ties in fetched pages.

Hard rule: a tie exists only if a fetched page contains a statement that names
the person (or continues a sentence about them with he/she/they) and an
organization next to a tie keyword. The quote is copied from the page and
re-verified by verify_quote before it is shown. No model states a tie.

Disclosure statements often list several people in one sentence
("Dr Lee reports grants from A, and Dr Okafor reports fees from B"), so each
clause is cut into per-subject segments and only the person's own segments count.
"""
from __future__ import annotations

import re

TIE = re.compile(
    r"\b(consult(?:ant|ing|ancy|ed|s)?(?:\s+fees)?|advisory\s+(?:board|committee|council)s?|advis[eo]r|"
    r"speakers?['’]?\s+(?:bureau|fees)|speaking\s+fees|honorari(?:a|um)|lecture\s+fees|grants?|"
    r"research\s+(?:funding|support)|funded\s+by|funding\s+from|personal\s+fees|"
    r"received\s+(?:fees|funding|payments|support)|employee|employed\s+by|employment|"
    r"stock|shares|equity|stockholder|shareholder|board\s+of\s+directors|director\s+of|"
    r"patents?|royalt(?:y|ies)|co-?founder|founder|paid\s+by|sponsored\s+by|travel\s+(?:support|expenses))\b",
    re.I,
)
CATEGORIES = [
    ("consulting", r"consult"),
    ("advisory board", r"advis"),
    ("speaking", r"speak|honorari|lecture"),
    ("research funding", r"grant|research|fund|sponsor"),
    ("employment", r"employ|paid by"),
    ("equity", r"stock|share|equity"),
    ("board", r"board of directors|director of"),
    ("patents / royalties", r"patent|royalt"),
    ("founder", r"founder"),
    ("personal fees", r"personal fees|received|travel"),
]
NEGATION = re.compile(
    r"\b(?:no\s+(?:relevant\s+|potential\s+|other\s+|financial\s+|competing\s+|conflicts?\s+of\s+)*"
    r"(?:conflicts?|competing|financial|disclosures?|relationships?|interests?)|nothing\s+to\s+(?:disclose|declare)|"
    r"none\s+(?:declared|reported)|declares?\s+no|ha(?:s|ve)\s+no|did\s+not\s+receive|not\s+received)\b",
    re.I,
)
EXCEPTION = re.compile(r"\b(?:except|other\s+than|apart\s+from|besides|aside\s+from)\b", re.I)
PRONOUN_START = re.compile(r"^(?:He|She|They|His|Her|Their)\b")

ORG_RUN = re.compile(r"(?:[A-Z][\w&'’\-]*)(?:\s+(?:of|for|&|[A-Z][\w&'’\-]*)){0,6}")
ABBREV = re.compile(r"(?:\b(?:Dr|Prof|Mr|Ms|Mrs|St|Inc|Co|Corp|Ltd|al|vs|No)|\b[A-Z])\.$")
SUBJECT_VERB = (r"(?:reports?|reported|has|have|had|received|receives|is|was|serves?|served|declares?|"
                r"holds?|held|owns?|consults?|consulted|acts?|acted|discloses?|disclosed|works?|worked)")
INITIALS = r"(?:[A-Z]\.\s?){2,4}|[A-Z]{2,3}\b"
SUBJECT = rf"(?:(?:Drs?\.?|Prof\.?|Professor|Mr\.?|Ms\.?)\s+)?(?:{INITIALS}|[A-Z][a-z]+(?:\s+[A-Z]{{1,2}}\b)?)"
SEGMENT_SPLIT = re.compile(rf"(?:,\s*|\s+)(?:and\s+|while\s+|whereas\s+|but\s+)?(?={SUBJECT}\s+{SUBJECT_VERB}\b)")

# Capitalised words that start disclosure phrases rather than names of organizations.
LEAD_STOP = {
    "the", "he", "she", "they", "his", "her", "their", "dr", "drs", "prof", "professor", "mr", "ms",
    "disclosures", "disclosure", "competing", "conflict", "conflicts", "interests", "interest", "none",
    "funding", "author", "authors", "in", "this", "consulting", "consultant", "consultancy", "grants", "grant",
    "honoraria", "honorarium", "stock", "personal", "fees", "fee", "advisory", "board", "boards", "speaker",
    "speakers", "speaking", "research", "support", "travel", "payment", "payments", "employment", "royalties",
    "patent", "patents", "member", "chair", "declaration", "declarations", "all", "outside", "no", "other",
    "financial", "potential", "role", "acknowledgments", "acknowledgements", "reports", "received", "served",
    "serves", "has", "lecture", "lectures", "equity", "ownership", "scientific", "medical", "clinical",
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
    "november", "december", "md", "phd", "mph", "dphil", "frcp", "of", "for",
}
GENERIC = {
    "university", "institute", "institutes", "inc", "corp", "corporation", "company", "co", "ltd", "llc",
    "pharmaceuticals", "pharmaceutical", "pharma", "therapeutics", "health", "healthcare", "foundation",
    "association", "society", "group", "labs", "laboratories", "center", "centre", "national", "of",
    "for", "the", "and", "school", "college", "medical", "medicine", "hospital", "research", "sciences",
}
CONNECTORS = {"of", "for", "the", "and", "&"}


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


def segments(clause: str) -> list[str]:
    """Cut a clause wherever a new subject starts: '…, and Dr Okafor reports …'."""
    parts, last = [], 0
    for m in SEGMENT_SPLIT.finditer(clause):
        if re.search(r"\b(?:Drs?|Prof|Professor|Mr|Ms|Mrs)\.?$", clause[:m.start()]):
            continue  # don't separate a title from its name
        if m.start() > last:
            parts.append(clause[last:m.start()])
            last = m.end()
    parts.append(clause[last:])
    return [p.strip(" ,") for p in parts if p.strip(" ,")]


def distinctive_tokens(org: str) -> list[str]:
    words = re.findall(r"[A-Za-z][\w'’\-]+", org)
    toks = [w for w in words if w.lower() not in GENERIC and len(w) >= 3]
    if toks:
        return toks
    # All-generic names like "National Institutes of Health" are still specific as a whole.
    content = [w for w in words if w.lower() not in CONNECTORS]
    return content if len(content) >= 2 else []


def mentions_org(org: str, text: str) -> bool:
    toks = distinctive_tokens(org)
    return bool(toks) and all(re.search(rf"\b{re.escape(t)}\b", text, re.I) for t in toks)


def same_org(a: str, b: str) -> bool:
    ta, tb = {t.lower() for t in distinctive_tokens(a)}, {t.lower() for t in distinctive_tokens(b)}
    return bool(ta and tb) and (ta <= tb or tb <= ta)


def category(keyword: str) -> str:
    k = keyword.lower()
    return next((name for name, pat in CATEGORIES if re.search(pat, k)), "other")


def person_patterns(name: str) -> tuple[re.Pattern, re.Pattern]:
    """(strong, clause): strong proves the page is about this person; clause attributes a statement."""
    parts = name.split()
    first, last = parts[0], parts[-1]
    L, F = re.escape(last), re.escape(first)
    strong = re.compile(
        rf"\b{F}\s+(?:[A-Z]\.?\s+)?{L}\b|\b{first[0]}\.\s*(?:[A-Z]\.\s*)?{L}\b|\b{L},\s+{F}\b"
        rf"|\b{L},?\s+{first[0]}\.?(?:[A-Z]\.?)?(?![a-z])"
    )
    initials = r"\.?\s?".join(p[0] for p in parts)
    clause = re.compile(rf"\b{L}\b|(?<![A-Za-z]){initials}\.?(?![A-Za-z])")
    return strong, clause


def clean_org(raw: str) -> str:
    toks = raw.strip(" .,").split()
    while toks and toks[0].lower().strip(".,:") in LEAD_STOP:
        toks.pop(0)
    while toks and toks[-1].lower() in CONNECTORS:
        toks.pop()
    return " ".join(toks)


def orgs_in(text: str, person: str) -> list[tuple[str, int]]:
    """Organization names in a statement, with their positions."""
    person_toks = {t.lower() for t in person.split()}
    out = []
    for m in ORG_RUN.finditer(text):
        org = clean_org(m.group(0))
        toks = org.split()
        if not toks or all(t.lower() in LEAD_STOP for t in toks):
            continue
        if any(t.lower().strip(".,") in person_toks for t in toks):
            continue
        if re.fullmatch(INITIALS, org) or re.fullmatch(r"(?:[A-Z]\.?){1,4}", org):  # someone's initials
            continue
        if not distinctive_tokens(org):
            continue
        out.append((org, m.start()))
    return out


def keyword_for(seg: str, pos: int) -> str:
    """The tie keyword closest before the organization (else the first one in the statement)."""
    before = [m for m in TIE.finditer(seg) if m.start() < pos]
    m = before[-1] if before else TIE.search(seg)
    return m.group(1).lower()


def person_statements(text: str, name: str) -> list[tuple[str, str]]:
    """(statement, clause) pairs about this person: their own segments, plus he/she/they
    sentences that directly follow a sentence naming them."""
    _, clause_pat = person_patterns(name)
    out, prev_about = [], False
    for clause in split_clauses(text):
        about = False
        for seg in segments(clause):
            if clause_pat.search(seg) or (prev_about and PRONOUN_START.match(seg)):
                out.append((seg, clause))
                about = True
        prev_about = about or (prev_about and bool(PRONOUN_START.match(clause)))
    return out


def find_ties(pages: list[dict], name: str, exclude_orgs: list[str] | None = None) -> list[dict]:
    """pages: [{url, title, text, api}] -> deduped ties, each with verified evidence."""
    exclude_orgs = [o for o in (exclude_orgs or []) if o]
    strong, _ = person_patterns(name)
    ties: dict[str, dict] = {}
    for page in pages:
        text = page.get("text") or ""
        if not strong.search(text):
            continue  # page isn't demonstrably about this person
        for seg, clause in person_statements(text, name):
            kw = TIE.search(seg)
            if not kw or (NEGATION.search(seg) and not EXCEPTION.search(seg)):
                continue
            quote = clause[:600]
            if not verify_quote(quote, text):
                continue
            for org, pos in orgs_in(seg, name):
                if any(same_org(org, ex) for ex in exclude_orgs):
                    continue
                key = " ".join(t.lower() for t in distinctive_tokens(org))
                rel = keyword_for(seg, pos)
                tie = ties.setdefault(key, {"org": org, "relation": rel, "category": category(rel), "evidence": []})
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
