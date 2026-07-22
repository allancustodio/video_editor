from __future__ import annotations

import html
import re
from pathlib import Path

from .models import Cue
from .timecode import parse_timecode


_TIME_LINE = re.compile(r"(?P<start>\d{1,3}:\d{2}:\d{2}[\.,]\d{3})\s+-->\s+(?P<end>\d{1,3}:\d{2}:\d{2}[\.,]\d{3})")
_TAGS = re.compile(r"<[^>]+>")
_SPEAKER = re.compile(r"^(?P<speaker>[^:]{2,80}):\s*(?P<text>.*)$")


def parse_vtt(path: str | Path) -> list[Cue]:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Transcrição não encontrada: {source}")

    lines = source.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    cues: list[Cue] = []
    i = 0
    cue_number = 0

    while i < len(lines):
        line = lines[i].strip()
        match = _TIME_LINE.search(line)
        if not match:
            i += 1
            continue

        cue_number += 1
        start = parse_timecode(match.group("start")) or 0.0
        end = parse_timecode(match.group("end")) or start
        i += 1
        text_lines: list[str] = []
        while i < len(lines) and lines[i].strip():
            text_lines.append(lines[i].strip())
            i += 1

        raw_text = " ".join(text_lines)
        cleaned = html.unescape(_TAGS.sub("", raw_text)).strip()
        speaker = ""
        spoken_text = cleaned
        speaker_match = _SPEAKER.match(cleaned)
        if speaker_match:
            speaker = speaker_match.group("speaker").strip()
            spoken_text = speaker_match.group("text").strip()

        if spoken_text:
            cues.append(
                Cue(
                    index=cue_number,
                    start=start,
                    end=end,
                    speaker=speaker,
                    text=spoken_text,
                )
            )
        i += 1

    if not cues:
        raise ValueError("Nenhuma legenda válida foi encontrada no VTT.")
    return cues


def transcript_between(cues: list[Cue], start: float, end: float, include_speakers: bool = True) -> str:
    rows: list[str] = []
    from .timecode import format_timecode

    for cue in cues:
        if cue.end < start or cue.start > end:
            continue
        prefix = f"{cue.speaker}: " if include_speakers and cue.speaker else ""
        rows.append(f"[{format_timecode(cue.start)}] {prefix}{cue.text}")
    return "\n".join(rows)
