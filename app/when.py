"""When a shipment should happen, read from the operator's words.

  find("... arriving by Friday 5pm ...")  -> ({"kind": "arrive_by", "text": "Friday 5pm"}, (start, end))
  resolve({"kind": "arrive_by", "text": "Friday 5pm"}, now) -> {"kind", "text", "at": "2026-11-20T17:00:00Z"}

Four kinds: arrive_by (a deadline at the destination; the route is planned backwards from it), depart_at (when it
leaves), asap (leave as soon as it can) and no_deadline. The phrase is kept as written and turned into a time in
code; a phrase that cannot be read, or a time already past, is reported, never guessed.
"""
import re
from datetime import datetime, timedelta

KINDS = ("arrive_by", "depart_at", "asap", "no_deadline")
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DAY = (r"(?:today|tonight|tomorrow|(?:next |this )?(?:mon|tues|wednes|thurs|fri|satur|sun)day|(?:the )?end of (?:the |this )?week|"
        r"in \d+ (?:days?|hours?|weeks?)|\d{1,2}(?:st|nd|rd|th)?(?: of)? " + _MON + r"|" + _MON + r" \d{1,2}(?:st|nd|rd|th)?|\d{4}-\d\d-\d\d)")
_TIME = r"(?:\d{1,2}(?::\d\d)?\s?(?:am|pm)|\d{1,2}:\d\d|noon|midday|midnight|(?:first thing|early|late)?\s?(?:morning|afternoon|evening|night)|first thing|close of business|cob)"
_WHEN = rf"(?:{_DAY}(?:,?\s+(?:at\s+|by\s+)?{_TIME})?|{_TIME}(?:\s+(?:on\s+)?{_DAY})?)"
_ARRIVE = re.compile(rf"\b(?:(?:arriv\w*|deliver\w*|there|due|needed|land\w*|get(?:ting)? there|reach\w*|in|with (?:the )?customer)\s+)?"
                     rf"(?:by|before|no later than|not later than|on or before)\s+({_WHEN})|\b(?:arriv\w*|deliver\w*|due|land\w*)\s+(?:on\s+|at\s+)?({_WHEN})", re.I)
_DEPART = re.compile(rf"\b(?:leav\w*|depart\w*|ship(?:s|ping|ped)?|go(?:ing|es)? out|collect\w*|pick(?:ed|ing)? up|pickup|dispatch\w*|set(?:ting|s)? off|start\w*|out)\s+"
                     rf"(?:on\s+|at\s+|from\s+)?({_WHEN})", re.I)
_ASAP = re.compile(r"\b(?:asap|a\.s\.a\.p\.?|as soon as (?:possible|you can|it can)|urgent(?:ly)?|right away|immediately|straight away|as fast as (?:possible|you can)|"
                   r"fastest(?: (?:possible|way|route))?|soonest|without delay|rush(?:ed)?)\b", re.I)
_NONE = re.compile(r"\b(?:no (?:deadline|rush|hurry)|whenever(?: suits| works| is cheapest)?|any ?time|not urgent|not time[- ]critical|no fixed date|flexible(?: on (?:date|time|timing)s?)?)\b", re.I)


def find(text: str) -> tuple[dict | None, tuple[int, int] | None]:
    """The first timing phrase in the text and where it is, or (None, None)."""
    for kind, pattern in (("arrive_by", _ARRIVE), ("depart_at", _DEPART)):
        m = pattern.search(text)
        if m:
            return {"kind": kind, "text": next(g for g in m.groups() if g).strip()}, m.span()
    for kind, pattern in (("no_deadline", _NONE), ("asap", _ASAP)):  # "no rush" before "rush"
        m = pattern.search(text)
        if m:
            return {"kind": kind, "text": m.group(0).strip()}, m.span()
    return None, None


def _clock(text: str, default_hour: int) -> tuple[int, int]:
    low = text.lower()
    m = re.search(r"\b(\d{1,2})(?::(\d\d))?\s?(am|pm)\b", low) or re.search(r"\b(\d{1,2}):(\d\d)\b()", low)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if m.group(3) == "pm" and hour < 12:
            hour += 12
        if m.group(3) == "am" and hour == 12:
            hour = 0
        return (hour, minute) if hour < 24 and minute < 60 else (default_hour, 0)
    for word, hour in (("midnight", 0), ("first thing", 7), ("early", 7), ("noon", 12), ("midday", 12), ("morning", 9), ("afternoon", 15),
                       ("close of business", 17), ("cob", 17), ("evening", 19), ("tonight", 21), ("night", 21)):
        if re.search(rf"\b{word}\b", low):
            return hour, 0
    return default_hour, 0


def moment(text: str, now: datetime, default_hour: int) -> datetime | None:
    """The time a phrase names, after `now`. None when it cannot be read."""
    low = text.lower()
    day = None
    if m := re.search(r"\bin (\d+) (day|hour|week)s?\b", low):
        n = int(m.group(1))
        if m.group(2) == "hour":
            return now + timedelta(hours=n)
        day = (now + timedelta(days=n * (7 if m.group(2) == "week" else 1))).date()
    elif m := re.search(r"\b(\d{4})-(\d\d)-(\d\d)\b", low):
        day = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
    elif m := (re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?(?: of)? ({_MON})", low) or re.search(rf"\b({_MON}) (\d{{1,2}})(?:st|nd|rd|th)?\b", low)):
        a, b = m.group(1), m.group(2)
        num, mon = (int(a), b) if a.isdigit() else (int(b), a)
        month = _MONTHS.index(mon[:3]) + 1
        try:
            day = datetime(now.year, month, num).date()
            if day < now.date():
                day = datetime(now.year + 1, month, num).date()
        except ValueError:
            return None
    elif "tomorrow" in low:
        day = (now + timedelta(days=1)).date()
    elif re.search(r"\b(today|tonight)\b", low):
        day = now.date()
    elif re.search(r"end of (the |this )?week", low):
        day = (now + timedelta(days=(4 - now.weekday()) % 7)).date()
        default_hour = 17
    elif m := re.search(r"\b(next |this )?(mon|tues|wednes|thurs|fri|satur|sun)day\b", low):
        ahead = (_DAYS.index(m.group(2) + "day") - now.weekday()) % 7
        if ahead == 0 or (m.group(1) == "next " and ahead < 7 and now.weekday() < _DAYS.index(m.group(2) + "day") and False):
            ahead = 7 if ahead == 0 and _clock(low, default_hour) <= (now.hour, now.minute) else ahead
        day = (now + timedelta(days=ahead)).date()
    hour, minute = _clock(low, default_hour)
    if day is None:  # a time alone ("by 5pm"): today, or tomorrow if that has passed
        if not re.search(_TIME, low, re.I):
            return None
        at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return at if at > now else at + timedelta(days=1)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=now.tzinfo)


def resolve(when: dict | None, now: datetime) -> dict | None:
    """The timing with its time worked out: adds "at" (ISO, or None for asap / no_deadline) and "problem"."""
    if not when or when.get("kind") not in KINDS:
        return None
    out = {"kind": when["kind"], "text": str(when.get("text") or ""), "at": None, "problem": None}
    if when["kind"] in ("asap", "no_deadline"):
        return out
    at = moment(out["text"], now, 17 if when["kind"] == "arrive_by" else 8)
    if at is None:
        out["problem"] = f'I could not read "{out["text"]}" as a date or time.'
    elif at <= now:
        out["problem"] = f'"{out["text"]}" is already past.'
    else:
        out["at"] = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    return out
