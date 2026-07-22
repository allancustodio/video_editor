from __future__ import annotations

import re


_TIMESTAMP_RE = re.compile(
    r"^(?:(?P<h>\d{1,3}):)?(?P<m>\d{1,2}):(?P<s>\d{1,2})(?:[\.,](?P<ms>\d{1,3}))?$"
)


def parse_timecode(value: str | int | float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0.0, float(value))

    raw = str(value).strip()
    if not raw:
        return None
    if raw.replace(".", "", 1).isdigit():
        return max(0.0, float(raw))

    match = _TIMESTAMP_RE.match(raw)
    if not match:
        raise ValueError(f"Timestamp inválido: {value!r}")

    hours = int(match.group("h") or 0)
    minutes = int(match.group("m") or 0)
    seconds = int(match.group("s") or 0)
    milliseconds = (match.group("ms") or "0").ljust(3, "0")[:3]
    return max(0.0, hours * 3600 + minutes * 60 + seconds + int(milliseconds) / 1000)


def format_timecode(seconds: float | int | None, milliseconds: bool = False) -> str:
    total = max(0.0, float(seconds or 0))
    whole = int(total)
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    if milliseconds:
        ms = int(round((total - whole) * 1000))
        if ms == 1000:
            whole += 1
            hours, remainder = divmod(whole, 3600)
            minutes, secs = divmod(remainder, 60)
            ms = 0
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"
