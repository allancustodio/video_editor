from __future__ import annotations

import re


_SECONDS_RE = re.compile(r"^\d+(?:[\.,]\d{1,3})?$")


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

    parts = raw.split(":")
    if len(parts) == 2:
        hours_text = "0"
        minutes_text, seconds_text = parts
    elif len(parts) == 3:
        hours_text, minutes_text, seconds_text = parts
    else:
        raise ValueError(f"Horário inválido: {value!r}. Use HH:MM:SS.")

    hours_text = hours_text or "0"
    minutes_text = minutes_text or "0"
    seconds_text = seconds_text or "0"
    if not hours_text.isdigit() or not minutes_text.isdigit() or not _SECONDS_RE.match(seconds_text):
        raise ValueError(f"Horário inválido: {value!r}. Use apenas números e dois-pontos.")

    hours = int(hours_text)
    minutes = int(minutes_text)
    seconds = float(seconds_text.replace(",", "."))
    return max(0.0, hours * 3600 + minutes * 60 + seconds)


def normalize_timecode(value: str | int | float | None) -> str:
    """Return a permissive user value in canonical HH:MM:SS form."""
    parsed = parse_timecode(value)
    if parsed is None:
        return ""
    return format_timecode(parsed, milliseconds=not float(parsed).is_integer())


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
