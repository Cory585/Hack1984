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
# A sentence subject: initials, or a surname optionally led by a title and/or one initial ("M. Okafor").
SUBJECT = rf"(?:(?:Drs?\.?|Prof\.?|Professor|Mr\.?|Ms\.?)\s+)?(?:{INITIALS}|(?:[A-Z]\.\s?)?[A-Z][a-z]+(?:\s+[A-Z]{{1,2}}\b)?)"
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
    """Sentences as exact slices of `text`, so quotes taken from them always verify against the page
    (re-joining pieces with a space turned "Dr.Okafor" into "Dr. Okafor" and failed verification)."""
    spans, start = [], 0
    for m in SENT_SPLIT.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    out: list[list[int]] = []
    for s, e in spans:
        piece = text[s:e]
        if not piece.strip():
            continue
        s += len(piece) - len(piece.lstrip())
        e = s + len(piece.strip())
        # Keep "Dr. Okafor" together, and don't start a sentence in lowercase ("Dr. Oliva. has …").
        if out and (ABBREV.search(text[out[-1][0]:out[-1][1]]) or text[s].islower()):
            out[-1][1] = e
        else:
            out.append([s, e])
    return [text[s:e] for s, e in out]


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
        if re.search(r"(?:\b(?:Drs?|Prof|Professor|Mr|Ms|Mrs)\.?|\b[A-Z]\.)$", clause[:m.start()]):
            continue  # don't separate a title or an initial from its name ("Dr Lee", "M. Okafor")
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


# Legal-form words that don't change which company is meant ("Pfizer" = "Pfizer Inc").
LEGAL_FORMS = {"inc", "corp", "corporation", "co", "company", "ltd", "limited", "llc", "plc", "ag", "sa", "gmbh",
               "pharmaceuticals", "pharmaceutical", "pharma", "group", "holdings", "the", "and"}
# Words that mark a *different* company even though the rest matches: Merck KGaA / Merck Serono are not
# Merck & Co. (KGaA is a legal form, but here it's the distinguishing part.)
DISTINGUISHING = {"kgaa", "serono"}


def _company_words(org: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", org.lower()) if w not in LEGAL_FORMS]


def same_company(a: str, b: str) -> bool:
    """Spellings of one company: 'Astra Zeneca' / 'AstraZeneca' / 'Astra-Zeneca', 'Pfizer' / 'Pfizer Inc',
    'Lilly' / 'Eli Lilly', 'Boehringer' / 'Boehringer Ingelheim'.
    Matches whole words only (never 'Amgen' inside 'Amgenta'): the shorter name must equal the longer
    one's leading or trailing words, be at least 4 letters, and the extra words can't mark a different
    company ('Merck' vs 'Merck KGaA')."""
    wa, wb = _company_words(a), _company_words(b)
    if not wa or not wb:
        return False
    if "".join(wa) == "".join(wb):  # spacing, hyphens, legal forms
        return True
    short, long_ = sorted((wa, wb), key=len)
    if len("".join(short)) < 4 or len(short) == len(long_):
        return False
    n = len(short)
    extra = long_[n:] if long_[:n] == short else long_[:-n] if long_[-n:] == short else None
    return extra is not None and not (set(extra) & DISTINGUISHING)


def category(keyword: str) -> str:
    k = keyword.lower()
    return next((name for name, pat in CATEGORIES if re.search(pat, k)), "other")


def name_parts(name: str) -> tuple[str, str, list[str]]:
    """(first, surname, initials-parts).
    Particles (da, van, le, di, bin…) are skipped only between the first and last names, because they
    are also real given and family names ("Le Wang" -> LW, not W). Suffixes (Filho, Júnior, Jr) are part
    of the initials but not the surname: "Ruy Lyra da Silva Filho" -> RLSF, surname Silva."""
    parts = name.split()
    if len(parts) <= 2:
        core = parts
    else:
        core = [parts[0]] + [p for p in parts[1:-1] if p.lower() not in PARTICLES] + [parts[-1]]
    named = [p for p in core if p.lower().rstrip(".") not in SUFFIXES]
    return parts[0], (named[-1] if len(named) > 1 else core[-1]), core


def surname(name: str) -> str:
    return name_parts(name)[1]


# A middle part of a name: an initial, a capitalised name, or a particle. Never an ordinary word,
# so "Maren thanked Dr. Okafor" doesn't prove a page is about Maren Okafor.
_MIDDLE = r"(?:[A-Z][\w'’\-]*\.?|da|de|do|dos|das|van|von|der|den|del|della|di|du|le|la|bin)"


def person_patterns(name: str) -> tuple[re.Pattern, re.Pattern]:
    """(strong, clause): strong proves the page is about this person; clause attributes a statement."""
    first, last, core = name_parts(name)
    L, F = re.escape(last), re.escape(first)
    strong = re.compile(
        rf"\b{F}[ \t]+(?:{_MIDDLE}[ \t]+){{0,3}}{L}\b|\b{first[0]}\.[ \t]*(?:[A-Z]\.[ \t]*){{0,3}}{L}\b"
        rf"|\b{L},[ \t]+{F}\b|\b{L},?[ \t]+{first[0]}\.?(?:[A-Z]\.?){{0,3}}(?![a-z])"
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


ATTRIBUTION = ("full name", "surname + initial", "surname", "initials", "continuation", "pronoun")  # strongest first


def person_statements(text: str, name: str) -> list[tuple[str, str, str]]:
    """(statement, quote, matched_by) triples about this person. A statement counts when it:
      * names the person in its own segment ("full name", "surname" or "initials"), or
      * continues their sentence after a semicolon without a new subject
        ("Dr X has received fees from A; personal fees from B") -> "continuation", or
      * starts with he/she/they right after a sentence about them -> "pronoun".
    matched_by records how the statement named the person: "full name", "surname + initial"
    ("Okafor M", "M. Okafor"), "surname", "initials", "continuation" or "pronoun".
    The quote covers only this person's own words: from where their run of clauses starts in the
    sentence to the end of the current clause, or just their segment when someone else shares the
    clause. It is always an exact slice of the page (at most 600 characters), so it verifies."""
    strong, clause_pat = person_patterns(name)
    first, last, _ = name_parts(name)
    full_re = re.compile(rf"\b{re.escape(first)}[ \t]+(?:{_MIDDLE}[ \t]+){{0,3}}{re.escape(last)}\b"
                         rf"|\b{re.escape(last)},[ \t]+{re.escape(first)}\b")
    surname_re = re.compile(rf"\b{re.escape(last)}\b")

    def matched_by(seg: str) -> str:
        if full_re.search(seg):
            return "full name"
        if strong.search(seg):
            return "surname + initial"
        if clause_pat.search(seg):
            return "surname" if surname_re.search(seg) else "initials"
        return "pronoun" if PRONOUN_START.match(seg) else "continuation"

    out, prev_about = [], False
    for sent in split_sentences(text):
        sent_about = False
        carry = prev_about and bool(PRONOUN_START.match(sent))  # "She serves on …" after a sentence about them
        run_start = 0 if carry else None  # where this person's current run of clauses begins
        for m in re.finditer(r"[^;]+;?", sent):
            ps, pe = m.start(), m.end()
            part = sent[ps:pe].strip(" ;")
            if not part:
                continue
            ps += sent[ps:pe].index(part)
            # A pronoun continues the current person; any other opening subject starts someone new.
            new_subject = starts_with_subject(part) and not PRONOUN_START.match(part)
            segs = segments(part)
            ours = False
            for i, seg in enumerate(segs):
                if clause_pat.search(seg):
                    ours = True
                elif i == 0:
                    ours = carry and not new_subject
                else:
                    ours = False  # a later segment introduced someone else
                if not ours:
                    run_start = None
                    continue
                seg_start = ps + part.find(seg)
                if len(segs) > 1 or run_start is None:
                    run_start = seg_start  # someone else shares this clause: quote only our part of it
                quote = sent[run_start:seg_start + len(seg)][:600]
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
