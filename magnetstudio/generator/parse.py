"""Offline parsing of a free Hebrew event description: event type, names, date, colors, style."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ============================================================== 1. offline parsing

HE = r"֐-׿"
HEB_MONTHS = {"ינואר": 1, "פברואר": 2, "מרץ": 3, "מרס": 3, "אפריל": 4, "מאי": 5, "יוני": 6,
              "יולי": 7, "אוגוסט": 8, "ספטמבר": 9, "אוקטובר": 10, "נובמבר": 11, "דצמבר": 12}

EVENT_TYPES = [  # (pattern, display label) – longest first
    ("בת מצווה|בת מצוה|בת-מצווה", "בת מצווה"), ("בר מצווה|בר מצוה|בר-מצווה", "בר מצווה"),
    ("יום הולדת|יומולדת|יום-הולדת", "יום הולדת"), ("שבת חתן", "שבת חתן"), ("ברית מילה", "ברית"),
    ("חינה|חנה", "חינה"), ("חתונה|חתונת", "חתונה"), ("אירוסין|אירוסים|ארוסין", "אירוסין"),
    ("בריתה|זבד הבת|שמחת בת", "שמחת בת"), ("ברית", "ברית"), ("מסיבת רווקות", "מסיבת רווקות"),
    ("מסיבה", "מסיבה"), ("כנס", "כנס"),
]

COLORS = {  # Hebrew color words → hex (longest match wins)
    "ורוד עתיק": "#C98A8E", "ירוק זית": "#6B6B3A", "כחול נייבי": "#1B2A4A", "אפור פחם": "#3A3A3A",
    "בורדו": "#6D1A36", "זהב": "#C9A24A", "זהוב": "#C9A24A", "כסף": "#B8BCC2", "כסוף": "#B8BCC2",
    "רוזגולד": "#B76E79", "ורוד": "#E8A1B5", "נייבי": "#1B2A4A", "כחול": "#1F3A68", "תכלת": "#8EC5E8",
    "טורקיז": "#1C9C9C", "ירוק": "#2F6B4F", "זית": "#6B6B3A", "מנטה": "#A8DCC6", "שחור": "#1A1A1A",
    "לבן": "#FFFFFF", "קרם": "#F5EBDD", "שמנת": "#F5EBDD", "בז'": "#D9C3A5", "בז": "#D9C3A5",
    "אדום": "#B3261E", "סגול": "#5B3A7A", "לילך": "#B9A3D6", "כתום": "#E07A2E", "צהוב": "#E8C547",
    "חרדל": "#C9A227", "חום": "#6B4A34", "אפור": "#8A8A8A", "פודרה": "#EBCFCB", "אפרסק": "#F4B79A",
    "terracotta": "#C2603E", "טרקוטה": "#C2603E",
}

STYLES = {  # keyword → ornament style
    "מרוקאי": "moroccan", "מרוקאית": "moroccan", "מזרחי": "moroccan", "ערבסק": "moroccan",
    "בוהו": "corners", "כפרי": "corners", "רוסטיק": "corners",
    "מינימליסטי": "minimal", "מינימליסטית": "minimal", "מינימלי": "minimal", "מודרני": "minimal",
    "נקי": "minimal", "קלאסי": "classic", "קלאסית": "classic", "אלגנטי": "classic",
    "אלגנטית": "classic", "יוקרתי": "classic", "וינטג'": "classic", "רטרו": "classic",
}


@dataclass
class EventInfo:
    raw: str
    event: str = ""            # "חינה"
    names: str = ""            # "מורן ואביב"
    name_a: str = ""           # "מורן"
    name_b: str = ""           # "אביב"
    title: str = ""            # main line to print
    date: str = ""             # "18.09.2026"
    colors: list[str] = field(default_factory=list)
    style: str = "classic"


_DATE_NUM = re.compile(r"(?<!\d)(\d{1,2})[./\-](\d{1,2})(?:[./\-](\d{2,4}))?(?!\d)")
_DATE_HEB = re.compile(rf"(?<!\d)(\d{{1,2}})\s*(?:ב|ל)?\s*({'|'.join(HEB_MONTHS)})\s*,?\s*(\d{{4}})?")
_NAMES = re.compile(rf"(?:^|\s)(?:ל|של\s+|לכבוד\s+)?([{HE}][{HE}'\"]+)\s+ו-?([{HE}][{HE}'\"]+)")
_STYLE_SPLIT = re.compile(r",|\s(?:בסגנון|סגנון|בגווני|בגוון|בצבעי|צבעים|בצבע)\s")


def _fmt_date(d: int | str, m: int | str, y: str | None) -> str:
    """Keep the digits as the user typed them ("13.8.2026" stays, "18.09.2026" stays); '.' separators."""
    if not (1 <= int(d) <= 31 and 1 <= int(m) <= 12):
        return ""
    if y and len(y) == 2:
        y = "20" + y
    return f"{d}.{m}" + (f".{y}" if y else "")


def parse_event(text: str) -> EventInfo:
    """Extract event type, names, date, colors and style from a free Hebrew description."""
    info = EventInfo(raw=text.strip())
    t = " ".join(text.split())

    date_span = None
    m = _DATE_HEB.search(t)
    if m:
        info.date = _fmt_date(m.group(1), HEB_MONTHS[m.group(2)], m.group(3))
        date_span = m.span()
    else:
        for m in _DATE_NUM.finditer(t):
            info.date = _fmt_date(m.group(1), m.group(2), m.group(3))
            if info.date:
                date_span = m.span()
                break

    # the "title clause": text before the date, or before the first style/color marker
    head = t[:date_span[0]] if date_span else t
    head = _STYLE_SPLIT.split(head)[0]
    head = re.split(r"\s[-–]\s", head)[0]
    head = re.sub(r"\s+(?:ב|ביום|בתאריך|תאריך)\s*$", "", head).strip(" ,.-–:")
    tail = t.replace(head, " ", 1)

    # colors in the order written, longest words first ("ורוד עתיק" beats "ורוד").
    # Looked up outside the title clause first, so "ברית לבן" isn't read as white.
    def find_colors(text: str) -> list[str]:
        low, found = text.lower(), []
        for word in sorted(COLORS, key=len, reverse=True):
            for cm in list(re.finditer(rf"(?:(?<![{HE}])|(?<=(?<![{HE}])[ובלהכמש])){re.escape(word)}(?![{HE}])", low)):
                found.append((cm.start(), COLORS[word]))
                low = low[:cm.start()] + " " * len(word) + low[cm.end():]
        return list(dict.fromkeys(c for _, c in sorted(found)))
    info.colors = find_colors(tail)

    for word, style in STYLES.items():
        if word in t:
            info.style = style
            break

    for pat, label in EVENT_TYPES:
        if re.search(pat, head):
            info.event = label
            break
    nm = _NAMES.search(head)
    if nm:
        info.names = f"{nm.group(1)} ו{nm.group(2)}"
        info.name_a, info.name_b = nm.group(1), nm.group(2)
    if info.names:
        info.title = info.names
    else:  # e.g. "יום הולדת 40 לדני" → event "יום הולדת 40", title "דני"
        rest = head
        for pat, _ in EVENT_TYPES:
            rest = re.sub(pat, "", rest, count=1)
        rest = rest.strip(" ,.-–:")
        num = re.match(r"^(\d{1,3})\s+(.*)$", rest)
        if num and info.event:
            info.event, rest = f"{info.event} {num.group(1)}", num.group(2)
        rest = re.sub(rf"^(?:של\s+|לכבוד\s+|ל(?=[{HE}]))", "", rest).strip(" ,.-–:")
        info.title = rest or info.event
    return info
