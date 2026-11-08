"""Pull the quoted experts (name, role, affiliation) out of article text.

Rule-based on purpose: every expert it returns can be traced to a pattern in the
text (see `signals`). People are labelled kind="expert" or kind="other"
(spokespeople, officials, patients); only experts are checked by default, and
the UI lets a person review the list before anything is searched.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

WORD = r"[A-Z](?:['’][A-Z])?[a-z]+(?:[A-Z][a-z]+)?(?:-[A-Z][a-z]+)?"
NAME = rf"{WORD}(?:\s+[A-Z]\.)?(?:\s+{WORD}){{1,2}}"
ORG = r"[A-Z][\w&'’\-]*(?:\s+(?:of|for|and|&|the|on|[A-Z][\w&'’\-]*))*"
SPEECH = r"said|says|told|added|explained|noted|cautioned|warned|argued|wrote|stressed|cautions|warns|notes|adds"
TITLE = (r"(?:Dr\.?|Prof\.?|Professor|Mr\.?|Ms\.?|Mrs\.?|President|Sen\.?|Senator|Rep\.?|Gov\.?|Governor|"
         r"Secretary|Mayor|Commissioner|Chairman|Chairwoman)")
CRED = r"(?:MD|M\.D\.|PhD|Ph\.D\.|MPH|DO|RN|NP|PharmD|DrPH|MBBS|ScD|MSc|MS|FACC|FACP|FRCP|MBA|JD|DPhil)"
CREDS = rf"(?:,?\s+{CRED}(?![A-Za-z]))+"
ROLE_WORD = (r"(?:\w*olog(?:ist)|researcher|scientist|professor|physician|epidemiologist|economist|surgeon|"
             r"investigator|expert|doctor|statistician|pharmacologist|pediatrician|psychiatrist|oncologist|"
             r"(?:co-?|lead\s+|senior\s+|first\s+)?author)")
WHO_VERB = r"(?:directs|leads|led|heads|headed|runs|chairs|co-?led|oversees|studies|researches|teaches|works|worked)"

QUOTED_AFTER = re.compile(rf"\b(?:{SPEECH})(?:\s+\w+)?\s*,?\s+(?:({TITLE})\s+)?({NAME})")
QUOTED_BEFORE = re.compile(rf"(?:({TITLE})\s+)?\b({NAME})(?:{CREDS})?\s+(?:{SPEECH})\b")
ACCORDING = re.compile(rf"\baccording\s+to\s+(?:({TITLE})\s+)?({NAME})")
TITLED = re.compile(rf"\b(Dr\.?|Prof\.?|Professor)\s+({NAME})")
APPOS = re.compile(rf"\b({NAME})({CREDS})?,\s+(?:an?\s+|the\s+)?([^,.;\n“”\"]{{2,90}}?)\s+(?:at|of|with|from|for|in)\s+(?:the\s+)?({ORG})")
# "Harlan Krumholz, a Yale University cardiologist": the institution comes before the role.
APPOS_PRE = re.compile(rf"\b({NAME})({CREDS})?,\s+(?:an?\s+|the\s+)({ORG})\s+({ROLE_WORD})\b")
APPOS_OF = re.compile(rf"\b({NAME})({CREDS})?,\s+of\s+(?:the\s+)?({ORG})")
WHO = re.compile(rf"\b({NAME})({CREDS})?,\s+who\s+({WHO_VERB}\b[^,.;\n]{{0,80}}?)\s+(?:at|of|for)\s+(?:the\s+)?({ORG})")
# "…of the Heart, Vascular & Thoracic Institute at Cleveland Clinic": the ORG pattern stops at the first comma
# ("Heart"), so look past a comma-separated unit name for the institution after its "at".
UNIT_TAIL = re.compile(rf"((?:,\s*[A-Z][\w&'’\-]*(?:\s+(?:of|for|and|&|the|[A-Z][\w&'’\-]*))*)+)\s+(?:at|of|in)\s+(?:the\s+)?({ORG})")
PRE_ROLE = re.compile(rf"(?:\b({ORG})\s+)?\b((?:study\s+|the\s+study['’]s\s+)?{ROLE_WORD})\s+(?:({TITLE})\s+)?({NAME})"
                      rf"(?:\s+of\s+(?:the\s+)?({ORG}))?")
PRE_ROLE_OTHER = re.compile(rf"\b(CEO|chief executive|president|spokes(?:person|woman|man)|executive director|"
                            rf"founder|chairman|chairwoman|lobbyist)\s+({NAME})")
LATER_ROLE = re.compile(rf"\b(?:is|was)\s+(?:an?\s+|the\s+)?([a-z][\w\s\-]{{2,60}}?)\s+(?:at|with|of|for)\s+(?:the\s+)?({ORG})")
NAME_OF = re.compile(rf"\b({NAME})\s+of\s+(?:the\s+)?({ORG})")
CREDENTIALED = re.compile(rf"\b({NAME}){CREDS}")

EXPERT_ROLE = re.compile(rf"\b(?:{ROLE_WORD}|research\w*|scien\w*|physician|director|chief|fellow|dean|lecturer|"
                         r"specialist|clinician|nurse|pharmacist|analyst|chair\w*|head of|led the|\w*ethicist|"
                         r"veterinarian|virologist|dietitian|psychologist|faculty)\b", re.I)
NONEXPERT_ROLE = re.compile(r"spokes(?:person|woman|man)|press|communications|\bceo\b|chief executive|executive|"
                            r"official|senator|representative|governor|mayor|secretary|lawmaker|patient|mother|"
                            r"father|resident|student|customer|lobbyist|founder|owner", re.I)
OFFICIAL_TITLE = re.compile(r"^(?:President|Sen\.?|Senator|Rep\.?|Gov\.?|Governor|Secretary|Mayor|Commissioner|"
                            r"Chairman|Chairwoman)$")
# Roles that always mean "not an independent expert", even alongside expert-sounding words.
LEADER_ROLE = re.compile(r"\b(?:spokes(?:person|woman|man)|ceo|chief executive|president|executive director|"
                         r"lobbyist|founder|press secretary)\b", re.I)
ORG_WORD = re.compile(r"\b(?:University|Institute|Institutes|College|Hospital|Center|Centre|Clinic|School|"
                      r"Foundation|Association|Society|Laboratory|Laboratories|Labs|Agency|Department|Inc|Corp|"
                      r"Pharmaceuticals?|Therapeutics|Health|Medicine|Council|Academy|Organization|Trust|"
                      r"Network|Company|Group|Journal|Times|Post|News|Reuters)\b")

LEAD_STOP = {"Not", "The", "A", "An", "In", "But", "And", "He", "She", "They", "It", "This", "That", "When", "While",
             "If", "According", "Researchers", "Experts", "Officials", "Scientists", "Doctors", "Study", "New",
             "Dr", "Dr.", "Prof", "Prof.", "Professor", "Mr", "Mr.", "Ms", "Ms.", "Mrs", "Mrs."}
TRAIL_STOP = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "January",
              "February", "March", "April", "May", "June", "July", "August", "September", "October",
              "November", "December", "In", "The", "On", "At"}
ORG_TRAIL = {"of", "for", "and", "&", "the", "on"}


@dataclass
class Expert:
    name: str
    role: str | None = None
    affiliation: str | None = None
    credentials: str | None = None
    kind: str = "expert"  # expert | other
    mentions: int = 0
    first_pos: int = 0
    context: str = ""
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in
                ("name", "role", "affiliation", "credentials", "kind", "mentions", "context", "signals")}


def clean_name(raw: str) -> str | None:
    toks = raw.split()
    while toks and (toks[0] in LEAD_STOP or OFFICIAL_TITLE.match(toks[0])):
        toks.pop(0)
    while toks and toks[-1] in TRAIL_STOP:
        toks.pop()
    full = [t for t in toks if not re.fullmatch(r"[A-Z]\.", t)]
    if len(full) < 2:
        return None
    name = " ".join(toks)
    if ORG_WORD.search(name):
        return None  # "Lakeside University", "Veltrix Pharmaceuticals"
    return name


def clean_org(raw: str | None) -> str | None:
    if not raw:
        return None
    toks = raw.split()
    while toks and toks[-1].lower() in ORG_TRAIL:
        toks.pop()
    org = " ".join(toks).rstrip(".")
    return org or None


def clean_creds(raw: str | None) -> str | None:
    if not raw:
        return None
    return ", ".join(re.findall(CRED, raw)) or None


def sentence_around(text: str, pos: int) -> str:
    start = max(text.rfind(". ", 0, pos), text.rfind("\n", 0, pos)) + 1
    end_candidates = [i for i in (text.find(". ", pos), text.find("\n", pos)) if i != -1]
    end = min(end_candidates) + 1 if end_candidates else len(text)
    return text[start:end].strip()


MD_IMAGE = re.compile(r"!\[[^\]]*\]\((?:[^()\s]|\([^)]*\))*(?:\s+\"[^\"]*\")?\)")
MD_LINK = re.compile(r"\[([^\]]+)\]\((?:[^()\s]|\([^)]*\))*(?:\s+\"[^\"]*\")?\)")


def strip_markdown_links(text: str) -> str:
    """Tavily returns pages as markdown: 'says [Steven Nissen](https://...), a cardiologist at ...'. Keep the
    link text and drop the URL, or no name pattern can match."""
    return MD_LINK.sub(r"\1", MD_IMAGE.sub("", text))


def extract_experts(text: str, limit: int | None = None) -> list[Expert]:
    text = strip_markdown_links(text)
    found: dict[str, Expert] = {}
    official: set[str] = set()

    def key_of(raw: str) -> tuple[str | None, str | None]:
        name = clean_name(raw)
        if not name:
            return None, None
        parts = name.split()
        return name, f"{parts[0]} {parts[-1]}"

    def add(raw, pos, signal, title=None, role=None, aff=None, creds=None, cue=True):
        name, key = key_of(raw)
        if not name:
            return
        if re.search(r"\b[Tt]he(?:\s+[a-z\-]+){0,3}\s*$", text[max(0, pos - 40):pos]):
            return  # "the nonprofit Public Citizen": people aren't "the X"
        if re.search(r"\b(?:at|of|for|from|with)\s*$", text[max(0, pos - 6):pos]):
            return  # "Director at Public Citizen wrote": people aren't "at X"
        e = found.get(key)
        if e is None:
            if not cue:
                return  # affiliation-only patterns never create a person
            e = found[key] = Expert(name=name, first_pos=pos, context=sentence_around(text, pos))
        if len(name) > len(e.name):
            e.name = name  # keep the fullest form, e.g. with a middle initial
        if signal not in e.signals:
            e.signals.append(signal)
        if title and OFFICIAL_TITLE.match(title.strip()):
            official.add(key)
        if role and not e.role:
            e.role = " ".join(role.split())
        if aff and not e.affiliation:
            org = clean_org(aff)
            if org and org.split()[0] not in LEAD_STOP:
                e.affiliation = org
        if creds and not e.credentials:
            e.credentials = clean_creds(creds)

    # Expert cues: these can introduce a person.
    for m in APPOS_PRE.finditer(text):
        if ORG_WORD.search(m.group(3)):
            add(m.group(1), m.start(1), "role", role=m.group(4), aff=m.group(3), creds=m.group(2))
    for m in APPOS.finditer(text):
        role_ok = EXPERT_ROLE.search(m.group(3)) or NONEXPERT_ROLE.search(m.group(3))
        if role_ok or ORG_WORD.search(m.group(4)):
            aff = m.group(4)
            tail = UNIT_TAIL.match(text, m.end(4))
            if tail and ORG_WORD.search(tail.group(1)):  # the first org was just the start of a unit's name
                aff = tail.group(2)
            add(m.group(1), m.start(1), "role", role=m.group(3), aff=aff, creds=m.group(2))
    for m in WHO.finditer(text):
        add(m.group(1), m.start(1), "role", role=f"who {m.group(3)}", aff=m.group(4), creds=m.group(2))
    for m in PRE_ROLE.finditer(text):
        aff = m.group(5) or (m.group(1) if m.group(1) and ORG_WORD.search(m.group(1)) else None)
        add(m.group(4), m.start(4), "role", title=m.group(3), role=m.group(2), aff=aff)
    for m in CREDENTIALED.finditer(text):
        add(m.group(1), m.start(1), "credentials", creds=m.group(0)[len(m.group(1)):])
    for m in TITLED.finditer(text):
        add(m.group(2), m.start(2), "title")
    for pat in (QUOTED_AFTER, QUOTED_BEFORE, ACCORDING):
        for m in pat.finditer(text):
            add(m.group(2), m.start(2), "quoted", title=m.group(1))
    for m in PRE_ROLE_OTHER.finditer(text):
        add(m.group(2), m.start(2), "role", role=m.group(1))
    # Attribute-only patterns: fill in affiliations for people already found.
    for m in APPOS_OF.finditer(text):
        add(m.group(1), m.start(1), "affiliation", aff=m.group(3), creds=m.group(2), cue=False)
    for m in NAME_OF.finditer(text):
        if ORG_WORD.search(m.group(2)):
            add(m.group(1), m.start(1), "affiliation", aff=m.group(2), cue=False)

    # "Vanstreels ... is a wildlife veterinarian with the University of California": a later
    # sentence that starts with the surname can supply a missing role and affiliation.
    for e in found.values():
        if e.affiliation:
            continue
        surname = e.name.split()[-1]
        for sent in re.split(r"(?<=[.!?])\s+", text):
            i = sent.find(surname)
            m = LATER_ROLE.search(sent, i) if i != -1 else None
            if m and ORG_WORD.search(m.group(2)) and m.start() - i < 160:
                role = re.split(r"\b(?:is|was)\s+(?:an?\s+|the\s+)?", m.group(1))[-1]
                e.role = e.role or " ".join(role.split())
                e.affiliation = clean_org(m.group(2))
                e.signals.append("affiliation")
                break

    experts = list(found.values())
    for key, e in found.items():
        surname = e.name.split()[-1]
        e.mentions = len(re.findall(rf"\b{re.escape(surname)}\b", text))
        if key in official or (e.role and (LEADER_ROLE.search(e.role) or
                                           (NONEXPERT_ROLE.search(e.role) and not EXPERT_ROLE.search(e.role)))):
            e.kind = "other"
    experts.sort(key=lambda e: (e.kind != "expert", -e.mentions, e.first_pos))
    return experts[:limit] if limit else experts
