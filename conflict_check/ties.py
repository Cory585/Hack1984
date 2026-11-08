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
    r"patents?|royalt(?:y|ies)|co-?founder|founder|paid\s+by|sponsored\s+by|travel\s+(?:support|expenses)|"
    r"fees\s+(?:from|for)|payments?\s+from)\b",
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
    ("personal fees", r"personal fees|received|travel|fees|payment"),
]
NEGATION = re.compile(
    r"\b(?:no\s+(?:relevant\s+|potential\s+|other\s+|financial\s+|competing\s+|conflicts?\s+of\s+)*"
    r"(?:conflicts?|competing|financial|disclosures?|relationships?|interests?)|nothing\s+to\s+(?:disclose|declare)|"
    r"none\s+(?:declared|reported)|declares?\s+no|ha(?:s|ve)\s+no|did\s+not\s+receive|not\s+received)\b",
    re.I,
)
EXCEPTION = re.compile(r"\b(?:except|other\s+than|apart\s+from|besides|aside\s+from)\b", re.I)
PRONOUN_START = re.compile(r"^(?:He|She|They|His|Her|Their)\b")

ORG_RUN = re.compile(r"(?:[A-Z][\w&'’\-]*)(?:\s+(?:of|for|&|do|da|de|[A-Z][\w&'’\-]*)){0,6}")  # "Eli Lilly do Brasil"
ABBREV = re.compile(r"(?:\b(?:Dr|Prof|Mr|Ms|Mrs|St|Inc|Co|Corp|Ltd|al|vs|No)|\b[A-Z])\.$")
SUBJECT_VERB = (r"(?:reports?|reported|has|have|had|received|receives|is|was|serves?|served|declares?|"
                r"holds?|held|owns?|consults?|consulted|acts?|acted|discloses?|disclosed|works?|worked)")
# Author initials as used in disclosure statements: "J.L.", "JL", "JFKS", "SvLS" (with a lowercase particle).
INITIALS = r"(?:[A-Z]\.\s?){2,5}|[A-Z](?:[a-z]?[A-Z]){1,5}\b"
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
CONNECTORS = {"of", "for", "the", "and", "&", "do", "da", "de"}
PARTICLES = {"da", "de", "do", "dos", "das", "van", "von", "der", "den", "del", "della", "di", "du", "le", "la", "bin"}
SUFFIXES = {"jr", "junior", "júnior", "filho", "neto", "sobrinho", "ii", "iii", "iv", "sr"}


def norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def verify_quote(quote: str, page_text: str) -> bool:
    return bool(quote) and norm_ws(quote) in norm_ws(page_text)


# Sentence ends: punctuation + space, a newline, or punctuation glued straight onto the next
# sentence ("…Novo Nordisk.JFKS has received…"), which happens when page text is extracted.
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|(?<=[a-z0-9)\]][.!?])(?=[A-Z])|\n+"
                        rf"|(?<=[.!?])(?=(?:{INITIALS})\s+{SUBJECT_VERB}\b)")  # "…and MSD.FV has received…"


def split_sentences(text: str) -> list[str]:
    out: list[str] = []
    for piece in SENT_SPLIT.split(text):
        piece = piece.strip()
        if not piece:
            continue
        # Keep "Dr. Okafor" together, and don't start a sentence in lowercase ("Dr. Oliva. has …").
        if out and (ABBREV.search(out[-1]) or piece[0].islower()):
            out[-1] = f"{out[-1]} {piece}"
        else:
            out.append(piece)
    return out


def split_clauses(text: str) -> list[str]:
    """Sentences, further cut at semicolons."""
    return [p.strip() for s in split_sentences(text) for p in s.split(";") if p.strip()]


def starts_with_subject(part: str) -> bool:
    """True if the clause opens with its own subject: 'J.L. reports…', 'Dr Lee has…'."""
    return bool(re.match(rf"\s*(?:and\s+)?{SUBJECT}\s+{SUBJECT_VERB}\b", part))


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


def compact(org: str) -> str:
    """'Astra-Zeneca', 'Astra Zeneca', 'AstraZeneca' -> 'astrazeneca'."""
    return re.sub(r"[^a-z0-9]", "", " ".join(distinctive_tokens(org)).lower())


def same_company(a: str, b: str) -> bool:
    """Looser match used to merge spellings of one company: 'Lilly' / 'Eli Lilly',
    'Novo Nordisk' / 'NovoNordisk'. Short names (< 4 letters) must match exactly."""
    ca, cb = compact(a), compact(b)
    if not ca or not cb:
        return False
    if ca == cb or same_org(a, b):
        return True
    short, long_ = sorted((ca, cb), key=len)
    return len(short) >= 4 and short in long_


def category(keyword: str) -> str:
    k = keyword.lower()
    return next((name for name, pat in CATEGORIES if re.search(pat, k)), "other")


def name_parts(name: str) -> tuple[str, str, list[str]]:
    """(first, surname, initials-parts). Initials skip particles ("Ruy Lyra da Silva Filho" -> RLSF);
    the surname skips suffixes too (Filho, Júnior, Jr)."""
    parts = name.split()
    core = [p for p in parts if p.lower() not in PARTICLES]
    named = [p for p in core if p.lower().rstrip(".") not in SUFFIXES]
    return parts[0], (named[-1] if len(named) > 1 else parts[-1]), core


def person_patterns(name: str) -> tuple[re.Pattern, re.Pattern]:
    """(strong, clause): strong proves the page is about this person; clause attributes a statement."""
    first, last, core = name_parts(name)
    L, F = re.escape(last), re.escape(first)
    strong = re.compile(
        rf"\b{F}\s+(?:\S+\s+){{0,3}}{L}\b|\b{first[0]}\.\s*(?:[A-Z]\.\s*){{0,3}}{L}\b|\b{L},\s+{F}\b"
        rf"|\b{L},?\s+{first[0]}\.?(?:[A-Z]\.?){{0,3}}(?![a-z])"
    )
    initials = r"\.?\s?".join(p[0] for p in core)
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
        if re.fullmatch(r"(?:[A-Z]\.\s?){1,5}|[A-Z]", org):  # dotted initials: "J.L."
            continue
        if re.fullmatch(r"[A-Z]+[a-z][A-Z]+", org):  # mixed-case initials: "SvLS"
            continue
        if re.fullmatch(INITIALS, org) and re.match(rf"\s+{SUBJECT_VERB}\b", text[m.end():]):
            continue  # "JFKS has received": a person, not a company (GSK in a list is kept)
        if not distinctive_tokens(org):
            continue
        out.append((org, m.start()))
    return out


def keyword_for(seg: str, pos: int) -> str:
    """The tie keyword closest before the organization (else the first one in the statement)."""
    before = [m for m in TIE.finditer(seg) if m.start() < pos]
    m = before[-1] if before else TIE.search(seg)
    return m.group(1).lower()


ATTRIBUTION = ("full name", "surname", "initials", "continuation", "pronoun")  # strongest first


def person_statements(text: str, name: str) -> list[tuple[str, str, str]]:
    """(statement, quote, matched_by) triples about this person. A statement counts when it:
      * names the person in its own segment ("full name", "surname" or "initials"), or
      * continues their sentence after a semicolon without a new subject
        ("Dr X has received fees from A; personal fees from B") -> "continuation", or
      * starts with he/she/they right after a sentence about them -> "pronoun".
    The quote is the whole sentence when short enough, else the clause."""
    strong, clause_pat = person_patterns(name)
    surname = re.compile(rf"\b{re.escape(name_parts(name)[1])}\b")

    def matched_by(seg: str) -> str:
        if strong.search(seg):
            return "full name"
        if clause_pat.search(seg):
            return "surname" if surname.search(seg) else "initials"
        return "pronoun" if PRONOUN_START.match(seg) else "continuation"

    out, prev_about = [], False
    for sent in split_sentences(text):
        sent_about = False
        carry = prev_about and bool(PRONOUN_START.match(sent))  # "She serves on …" after a sentence about them
        for part in (p.strip() for p in sent.split(";")):
            if not part:
                continue
            quote = sent if len(sent) <= 600 else part[:600]
            # A pronoun continues the current person; any other opening subject starts someone new.
            new_subject = starts_with_subject(part) and not PRONOUN_START.match(part)
            ours = False
            for i, seg in enumerate(segments(part)):
                if clause_pat.search(seg):
                    ours = True
                elif i == 0:
                    ours = carry and not new_subject
                else:
                    ours = False  # a later segment introduced someone else
                if ours:
                    out.append((seg, quote, matched_by(seg)))
                    sent_about = True
            carry = ours  # the next semicolon part continues whoever this part ended on
        prev_about = sent_about
    return out


def find_ties(pages: list[dict], name: str, exclude_orgs: list[str] | None = None) -> list[dict]:
    """pages: [{url, title, text, api}] -> deduped ties, each with verified evidence."""
    exclude_orgs = [o for o in (exclude_orgs or []) if o]
    strong, _ = person_patterns(name)
    ties: list[dict] = []
    for page in pages:
        text = page.get("text") or ""
        if not strong.search(text):
            continue  # page isn't demonstrably about this person
        for seg, quote, how in person_statements(text, name):
            kw = TIE.search(seg)
            if not kw or (NEGATION.search(seg) and not EXCEPTION.search(seg)):
                continue
            if not verify_quote(quote, text):
                continue
            for org, pos in orgs_in(seg, name):
                if any(same_org(org, ex) for ex in exclude_orgs):
                    continue
                rel = keyword_for(seg, pos)
                # Merge spellings of one company ("AstraZeneca" / "Astra Zeneca", "Lilly" / "Eli Lilly").
                tie = next((t for t in ties if same_company(t["org"], org)), None)
                if tie is None:
                    tie = {"org": org, "relation": rel, "category": category(rel), "categories": [],
                           "evidence": [], "aliases": []}
                    ties.append(tie)
                if category(rel) not in tie["categories"]:
                    tie["categories"].append(category(rel))
                elif org != tie["org"] and org not in tie["aliases"]:
                    tie["aliases"].append(org)
                    if len(org) > len(tie["org"]):  # show the fullest spelling
                        tie["aliases"].append(tie["org"])
                        tie["aliases"].remove(org)
                        tie["org"] = org
                ev = next((e for e in tie["evidence"] if e["url"] == page.get("url")), None)
                if ev is None:
                    tie["evidence"].append({"url": page.get("url"), "title": page.get("title"), "api": page.get("api"),
                                            "quote": quote, "verified": True, "matched_by": how})
                elif ATTRIBUTION.index(how) < ATTRIBUTION.index(ev["matched_by"]):
                    ev.update(quote=quote, matched_by=how)  # same page, stronger attribution: keep that one
    return ties


def classify_tie(tie: dict, article: str, surname: str) -> dict:
    """disclosed: the article names the org in a paragraph that mentions the expert.
    related: the article names the org anywhere (it's part of this story)."""
    paras = [p for p in re.split(r"\n\s*\n|\n", article) if re.search(rf"\b{re.escape(surname)}\b", p)]
    tie["disclosed_in_article"] = any(mentions_org(tie["org"], p) for p in paras)
    tie["related_to_story"] = mentions_org(tie["org"], article)
    return tie
