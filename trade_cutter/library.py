from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


_BASE = r"(?P<key>GMT(?P<date>\d{8})-(?P<time>\d{6})_Recording)"
_TRANSCRIPT = re.compile(rf"^{_BASE}\.transcript\.vtt$", re.IGNORECASE)
_SCREEN = re.compile(rf"^{_BASE}_as_(?P<resolution>\d+x\d+)\.mp4$", re.IGNORECASE)
_PROFESSOR = re.compile(rf"^{_BASE}_avo_(?P<resolution>\d+x\d+)\.mp4$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RecordingGroup:
    key: str
    recorded_at: datetime
    screen_video: str = ""
    transcript: str = ""
    professor_video: str = ""

    @property
    def complete(self) -> bool:
        return bool(self.screen_video and self.transcript and self.professor_video)

    @property
    def missing(self) -> list[str]:
        values: list[str] = []
        if not self.screen_video:
            values.append("tela")
        if not self.transcript:
            values.append("transcrição")
        if not self.professor_video:
            values.append("professor")
        return values

    @property
    def label(self) -> str:
        status = "completa" if self.complete else f"falta {', '.join(self.missing)}"
        return f"{self.recorded_at:%d/%m/%Y %H:%M:%S} — {status}"


def scan_recordings(folder: str | Path, *, recursive: bool = True) -> list[RecordingGroup]:
    root = Path(folder)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Pasta de gravações não encontrada: {root}")

    grouped: dict[str, dict[str, object]] = {}
    paths = root.rglob("*") if recursive else root.iterdir()
    for path in sorted((item for item in paths if item.is_file()), key=lambda item: str(item).lower()):
        match = _TRANSCRIPT.match(path.name)
        role = "transcript"
        if match is None:
            match = _SCREEN.match(path.name)
            role = "screen_video"
        if match is None:
            match = _PROFESSOR.match(path.name)
            role = "professor_video"
        if match is None:
            continue

        key = match.group("key")
        values = grouped.setdefault(
            key,
            {
                "key": key,
                "recorded_at": datetime.strptime(
                    f"{match.group('date')}-{match.group('time')}", "%Y%m%d-%H%M%S"
                ),
                "screen_video": "",
                "transcript": "",
                "professor_video": "",
            },
        )
        if not values[role]:
            values[role] = str(path.resolve())

    recordings = [RecordingGroup(**values) for values in grouped.values()]
    return sorted(recordings, key=lambda item: item.recorded_at, reverse=True)


def load_user_config(path: str | Path = "user_config.json") -> dict[str, object]:
    source = Path(path)
    if not source.exists():
        return {}
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def save_user_config(value: dict[str, object], path: str | Path = "user_config.json") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
