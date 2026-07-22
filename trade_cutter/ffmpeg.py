from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable

from .models import Operation
from .timecode import format_timecode


ProgressCallback = Callable[[int, int, Operation, Path], None]


def find_ffmpeg(explicit_path: str = "") -> str:
    if explicit_path:
        path = Path(explicit_path)
        if path.exists():
            return str(path)
        raise FileNotFoundError(f"FFmpeg não encontrado em: {explicit_path}")
    discovered = shutil.which("ffmpeg")
    if not discovered:
        raise FileNotFoundError("FFmpeg não está no PATH. Instale-o ou informe o caminho do ffmpeg.exe.")
    return discovered


def safe_filename(value: str) -> str:
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")
    return text[:80] or "operacao"


def capture_frame(
    video_path: str | Path,
    time_seconds: float,
    *,
    ffmpeg_path: str = "",
) -> bytes:
    """Return one JPEG frame without creating a temporary file."""
    ffmpeg = find_ffmpeg(ffmpeg_path)
    source = Path(video_path)
    if not source.exists():
        raise FileNotFoundError(f"Vídeo não encontrado: {source}")

    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-ss", format_timecode(max(0.0, time_seconds), milliseconds=True),
        "-i", str(source), "-frames:v", "1",
        "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
    ]
    completed = subprocess.run(command, capture_output=True, check=False)
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"FFmpeg não conseguiu capturar a prévia:\n{message}")
    return completed.stdout


def _crop_filter(operation: Operation) -> str:
    x = min(max(operation.crop_x, 0.0), 0.999)
    y = min(max(operation.crop_y, 0.0), 0.999)
    width = min(max(operation.crop_width, 0.001), 1.0 - x)
    height = min(max(operation.crop_height, 0.001), 1.0 - y)
    return (
        f"crop=trunc(iw*{width:.6f}/2)*2:trunc(ih*{height:.6f}/2)*2:"
        f"trunc(iw*{x:.6f}/2)*2:trunc(ih*{y:.6f}/2)*2"
    )


def cut_video(
    video_path: str | Path,
    operation: Operation,
    output_path: str | Path,
    *,
    mode: str = "exact",
    ffmpeg_path: str = "",
    output_format: str = "original",
    professor_video_path: str | Path = "",
    professor_sync_offset: float = 0.0,
    audio_source: str = "professor",
) -> Path:
    if output_format not in {"original", "vertical"}:
        raise ValueError(f"Formato de saída inválido: {output_format}")
    if audio_source not in {"professor", "screen"}:
        raise ValueError(f"Fonte de áudio inválida: {audio_source}")

    ffmpeg = find_ffmpeg(ffmpeg_path)
    source = Path(video_path)
    if not source.exists():
        raise FileNotFoundError(f"Vídeo não encontrado: {source}")
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    duration = max(0.2, operation.cut_end - operation.cut_start)
    start = format_timecode(operation.cut_start, milliseconds=True)
    duration_value = f"{duration:.3f}"
    should_crop = operation.crop_area != "full"

    if output_format == "vertical":
        professor = Path(professor_video_path)
        if not professor_video_path or not professor.exists():
            raise FileNotFoundError(f"Vídeo do professor não encontrado: {professor}")

        professor_start = format_timecode(
            max(0.0, operation.cut_start + professor_sync_offset), milliseconds=True
        )
        graph_filter = _crop_filter(operation) if should_crop else "null"
        filter_complex = (
            f"[0:v]{graph_filter},"
            "scale=1080:960:force_original_aspect_ratio=decrease,"
            "pad=1080:960:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[graph];"
            "[1:v]scale=1080:960:force_original_aspect_ratio=increase,"
            "crop=1080:960,setsar=1[professor];"
            "[professor][graph]vstack=inputs=2[v]"
        )
        audio_input = "0:a?" if audio_source == "screen" else "1:a?"
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-ss", start, "-i", str(source),
            "-ss", professor_start, "-i", str(professor),
            "-t", duration_value,
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", audio_input,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            str(target),
        ]
    elif mode == "fast" and not should_crop:
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-ss", start, "-i", str(source), "-t", duration_value,
            "-map", "0:v:0", "-map", "0:a?", "-c", "copy",
            "-reset_timestamps", "1", str(target),
        ]
    else:
        video_filter = ["-vf", _crop_filter(operation)] if should_crop else []
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-ss", start, "-i", str(source), "-t", duration_value,
            "-map", "0:v:0", "-map", "0:a?",
            *video_filter,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            str(target),
        ]

    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"FFmpeg falhou em {operation.title}:\n{completed.stderr.strip()}")
    return target


def cut_selected(
    video_path: str | Path,
    operations: list[Operation],
    output_dir: str | Path,
    *,
    mode: str = "exact",
    ffmpeg_path: str = "",
    progress: ProgressCallback | None = None,
    output_format: str = "original",
    professor_video_path: str | Path = "",
    professor_sync_offset: float = 0.0,
    audio_source: str = "professor",
) -> list[Path]:
    selected = [operation for operation in operations if operation.selected]
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    results: list[Path] = []

    for index, operation in enumerate(selected, 1):
        filename = f"{index:02d}_{format_timecode(operation.entry_time).replace(':', '-')}_{safe_filename(operation.title)}.mp4"
        target = output / filename
        result = cut_video(
            video_path,
            operation,
            target,
            mode=mode,
            ffmpeg_path=ffmpeg_path,
            output_format=output_format,
            professor_video_path=professor_video_path,
            professor_sync_offset=professor_sync_offset,
            audio_source=audio_source,
        )
        results.append(result)
        if progress:
            progress(index, len(selected), operation, result)
    return results
