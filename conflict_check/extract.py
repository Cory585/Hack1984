"""Pull the quoted experts (name, role, affiliation) out of article text.

Rule-based on purpose: every expert it returns can be traced to a pattern in the
text. An LLM extractor can be swapped in later, but its output should still be
checked against the article (see ties.verify_quote).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

WORD = r"[A-Z](?:['’][A-Z])?[a-z]+(?:[A-Z][a-z]+)?(?:-[A-Z][a-z]+)?"
NAME = rf"{WORD}(?:\s+[A-Z]\.)?(?:\s+{WORD}){{1,2}}"
ORG = r"[A-Z][\w&'’\-]*(?:\s+(?:of|for|and|&|the|on|[A-Z][\w&'’\-]*))*"
SPEECH = r"said|says|told|added|explained|noted|cautioned|warned|argued|wrote"

TITLED = re.compile(rf"\b(?:Dr\.|Prof\.|Professor)\s+({NAME})")
APPOS = re.compile(rf"\b({NAME}),\s+(?:an?\s+|the\s+)?([^,.;\n]{{2,90}}?)\s+(?:at|of|with|from)\s+(?:the\s+)?({ORG})")
SAID_AFTER = re.compile(rf"\b(?:{SPEECH})(?:\s+\w+)?\s*,?\s+(?:Dr\.\s+|Prof\.\s+)?({NAME})")
SAID_BEFORE = re.compile(rf"\b({NAME})\s+(?:{SPEECH})\b")
ACCORDING = re.compile(rf"\baccording to\s+(?:Dr\.\s+|Prof\.\s+)?({NAME})")

EXPERT_ROLE = re.compile(
    r"\w*olog(?:ist|y)|professor|research|scien|physician|doctor|director|chief|fellow|dean|"
    r"lecturer|investigator|specialist|author|clinician|expert|surgeon|nurse|pharmacist|economist|analyst",
    re.I,
)
LEAD_STOP = {"The", "A", "An", "In", "But", "And", "He", "She", "They", "It", "This", "That", "When",
             "While", "If", "According", "Researchers", "Experts", "Mr", "Ms", "Mrs", "Dr", "Prof",
             "Professor", "Officials", "Scientists", "Doctors"}
TRAIL_STOP = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "January",
              "February", "March", "April", "May", "June", "July", "August", "September", "October",
              "November", "December", "In", "The", "On", "At"}
ORG_TRAIL = {"of", "for", "and", "&", "the", "on"}


@dataclass
class Expert:
    name: str
    role: str | None = None
    affiliation: str | None = None
    mentions: int = 0
    first_pos: int = 0
    context: str = ""
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("name", "role", "affiliation", "mentions", "context", "signals")}


def clean_name(raw: str) -> str | None:
    toks = raw.split()
    while toks and toks[0].rstrip(".") in LEAD_STOP:
        toks.pop(0)
    while toks and toks[-1] in TRAIL_STOP:
        toks.pop()
    full = [t for t in toks if not re.fullmatch(r"[A-Z]\.", t)]
    if len(full) < 2:
        return None
    return " ".join(toks)


def clean_org(raw: str) -> str:
    toks = raw.split()
    while toks and toks[-1].lower() in ORG_TRAIL:
        toks.pop()
    return " ".join(toks).rstrip(".")


def sentence_around(text: str, pos: int) -> str:
    start = max(text.rfind(". ", 0, pos), text.rfind("\n", 0, pos)) + 1
    end_candidates = [i for i in (text.find(". ", pos), text.find("\n", pos)) if i != -1]
    end = min(end_candidates) + 1 if end_candidates else len(text)
    return text[start:end].strip()


def extract_experts(text: str, limit: int | None = None) -> list[Expert]:
    found: dict[str, Expert] = {}

    def add(raw: str, pos: int, signal: str, role: str | None = None, aff: str | None = None):
        name = clean_name(raw)
        if not name:
            return
        parts = name.split()
        key = f"{parts[0]} {parts[-1]}"
        e = found.get(key)
        if e is None:
            e = found[key] = Expert(name=name, first_pos=pos, context=sentence_around(text, pos))
        if signal not in e.signals:
            e.signals.append(signal)
        if role and not e.role:
            e.role = role.strip()
        if aff and not e.affiliation:
            e.affiliation = clean_org(aff)

    for m in APPOS.finditer(text):
        if EXPERT_ROLE.search(m.group(2)):
            add(m.group(1), m.start(1), "role", m.group(2), m.group(3))
    for pat, sig in ((TITLED, "title"), (SAID_AFTER, "quoted"), (SAID_BEFORE, "quoted"), (ACCORDING, "quoted")):
        for m in pat.finditer(text):
            add(m.group(1), m.start(1), sig)

    experts = list(found.values())
    for e in experts:
        surname = e.name.split()[-1]
        e.mentions = len(re.findall(rf"\b{re.escape(surname)}\b", text))
    experts.sort(key=lambda e: (-e.mentions, e.first_pos))
    return experts[:limit] if limit else experts
