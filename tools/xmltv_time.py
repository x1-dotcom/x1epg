from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

XMLTV_TIME_RE = re.compile(r"^(\d{14})\s([+-])(\d{2})(\d{2})$")


def parse_xmltv_time(raw: str | None) -> datetime:
    if not raw:
        raise ValueError("missing XMLTV timestamp")
    match = XMLTV_TIME_RE.fullmatch(raw.strip())
    if not match:
        raise ValueError(f"XMLTV timestamp must include numeric UTC offset: {raw!r}")
    stamp, sign, hour_text, minute_text = match.groups()
    hours = int(hour_text)
    minutes = int(minute_text)
    if minutes > 59 or hours > 14 or (hours == 14 and minutes != 0):
        raise ValueError(f"invalid XMLTV UTC offset: {raw!r}")
    offset = timedelta(hours=hours, minutes=minutes)
    if sign == "-":
        offset = -offset
    try:
        local = datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone(offset))
    except ValueError as exc:
        raise ValueError(f"invalid XMLTV calendar timestamp: {raw!r}") from exc
    return local.astimezone(timezone.utc)
