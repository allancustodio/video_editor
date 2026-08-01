from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_FILENAME = "project.json"


def create_project_directory(
    output_directory: str | Path,
    video_filename: str,
    *,
    created_at: datetime | None = None,
) -> Path:
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    timestamp = (created_at or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    name = _safe_name(Path(video_filename).stem) or "video-final"
    base = root / f"{timestamp}_{name}"
    candidate = base
    suffix = 2
    while candidate.exists():
        candidate = root / f"{base.name}-{suffix:02d}"
        suffix += 1
    candidate.mkdir()
    return candidate


def project_video_path(project_directory: str | Path) -> Path:
    directory = Path(project_directory)
    return directory / f"{directory.name}.mp4"


def copy_source_transcript(
    transcript_path: str | Path,
    project_directory: str | Path,
) -> Path | None:
    if not transcript_path:
        return None
    source = Path(transcript_path)
    if not source.exists() or not source.is_file():
        return None
    target = Path(project_directory) / "source.transcript.vtt"
    shutil.copy2(source, target)
    return target


def write_project_manifest(
    project_directory: str | Path,
    *,
    name: str,
    files: dict[str, str | Path | None],
    source_video: str | Path,
    professor_video: str | Path,
    source_transcript: str | Path,
    settings: dict[str, Any],
    created_at: datetime | None = None,
) -> Path:
    directory = Path(project_directory).resolve()
    payload = {
        "version": 1,
        "name": name,
        "created_at": (created_at or datetime.now().astimezone()).isoformat(),
        "files": {
            key: _relative_file(directory, value)
            for key, value in files.items()
            if value
        },
        "sources": {
            "screen_video": _absolute_or_empty(source_video),
            "professor_video": _absolute_or_empty(professor_video),
            "transcript": _absolute_or_empty(source_transcript),
        },
        "settings": settings,
    }
    target = directory / PROJECT_FILENAME
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def load_project_manifest(path: str | Path) -> tuple[Path, dict[str, Any]]:
    source = Path(path)
    if source.is_dir():
        source = source / PROJECT_FILENAME
    if not source.exists():
        raise FileNotFoundError(f"Projeto não encontrado: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"project.json inválido: {error}") from error
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("Versão de projeto não reconhecida.")
    if not isinstance(payload.get("files"), dict):
        raise ValueError("O projeto não possui a lista de arquivos.")
    return source.resolve(), payload


def resolve_project_file(
    manifest_path: str | Path,
    value: str | Path | None,
) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = Path(manifest_path).resolve().parent / path
    return path.resolve()


def write_export_error(project_directory: str | Path, error: Exception) -> Path:
    target = Path(project_directory) / "export-error.txt"
    target.write_text(
        f"A exportação não foi concluída.\n\n{type(error).__name__}: {error}\n",
        encoding="utf-8",
    )
    return target


def _safe_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", value.strip())
    cleaned = re.sub(r"\s+", "-", cleaned)
    return cleaned.strip(" .-_")[:80]


def _relative_file(directory: Path, value: str | Path | None) -> str:
    if not value:
        return ""
    path = Path(value).resolve()
    try:
        return str(path.relative_to(directory))
    except ValueError:
        return str(path)


def _absolute_or_empty(value: str | Path) -> str:
    return str(Path(value).resolve()) if value else ""
