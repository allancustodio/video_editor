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


def _even_size(value: float) -> int:
    return max(2, int(round(value)) // 2 * 2)


def _even_offset(value: float) -> int:
    return max(0, int(round(value)) // 2 * 2)


def _position_anchor(value: float) -> float:
    """Convert a -100..100 UI position into a 0..1 crop anchor."""
    return (min(max(value, -100.0), 100.0) + 100.0) / 200.0


def _vertical_filter(
    operation: Operation,
    *,
    professor_zoom: float = 1.0,
    professor_position_x: float = 0.0,
    professor_position_y: float = 0.0,
    graph_zoom: float = 1.0,
    graph_position_x: float = 0.0,
    graph_position_y: float = 0.0,
) -> str:
    professor_zoom = min(max(professor_zoom, 1.0), 3.0)
    graph_zoom = min(max(graph_zoom, 1.0), 3.0)
    professor_width = _even_size(1080 * professor_zoom)
    professor_height = _even_size(960 * professor_zoom)
    graph_width = _even_size(1080 * graph_zoom)
    graph_height = _even_size(960 * graph_zoom)

    professor_x = _position_anchor(professor_position_x)
    professor_y = _position_anchor(professor_position_y)
    graph_x = _even_offset(max(0, graph_width - 1080) * _position_anchor(graph_position_x))
    graph_y = _even_offset(max(0, graph_height - 960) * _position_anchor(graph_position_y))
    graph_filter = _crop_filter(operation) if operation.crop_area != "full" else "null"

    return (
        f"[0:v]{graph_filter},"
        f"scale={graph_width}:{graph_height}:force_original_aspect_ratio=decrease,"
        f"pad={graph_width}:{graph_height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"crop=1080:960:{graph_x}:{graph_y},setsar=1[graph];"
        f"[1:v]scale={professor_width}:{professor_height}:force_original_aspect_ratio=increase,"
        f"crop=1080:960:(iw-ow)*{professor_x:.6f}:(ih-oh)*{professor_y:.6f},"
        "setsar=1[professor];"
        "[professor][graph]vstack=inputs=2,format=yuv420p[v]"
    )


def capture_vertical_frame(
    video_path: str | Path,
    professor_video_path: str | Path,
    operation: Operation,
    *,
    ffmpeg_path: str = "",
    professor_sync_offset: float = 0.0,
    professor_zoom: float = 1.0,
    professor_position_x: float = 0.0,
    professor_position_y: float = 0.0,
    graph_zoom: float = 1.0,
    graph_position_x: float = 0.0,
    graph_position_y: float = 0.0,
) -> bytes:
    """Return one composed 1080x1920 JPEG using the final render filter."""
    ffmpeg = find_ffmpeg(ffmpeg_path)
    source = Path(video_path)
    professor = Path(professor_video_path)
    if not source.exists():
        raise FileNotFoundError(f"Vídeo não encontrado: {source}")
    if not professor_video_path or not professor.exists():
        raise FileNotFoundError(f"Vídeo do professor não encontrado: {professor}")

    start = format_timecode(max(0.0, operation.cut_start), milliseconds=True)
    professor_start = format_timecode(
        max(0.0, operation.cut_start + professor_sync_offset), milliseconds=True
    )
    filter_complex = _vertical_filter(
        operation,
        professor_zoom=professor_zoom,
        professor_position_x=professor_position_x,
        professor_position_y=professor_position_y,
        graph_zoom=graph_zoom,
        graph_position_x=graph_position_x,
        graph_position_y=graph_position_y,
    )
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-ss", start, "-i", str(source),
        "-ss", professor_start, "-i", str(professor),
        "-filter_complex", filter_complex,
        "-map", "[v]", "-frames:v", "1",
        "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
    ]
    completed = subprocess.run(command, capture_output=True, check=False)
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"FFmpeg não conseguiu gerar a prévia vertical:\n{message}")
    return completed.stdout


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
    professor_zoom: float = 1.0,
    professor_position_x: float = 0.0,
    professor_position_y: float = 0.0,
    graph_zoom: float = 1.0,
    graph_position_x: float = 0.0,
    graph_position_y: float = 0.0,
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
        filter_complex = _vertical_filter(
            operation,
            professor_zoom=professor_zoom,
            professor_position_x=professor_position_x,
            professor_position_y=professor_position_y,
            graph_zoom=graph_zoom,
            graph_position_x=graph_position_x,
            graph_position_y=graph_position_y,
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
    professor_zoom: float = 1.0,
    professor_position_x: float = 0.0,
    professor_position_y: float = 0.0,
    graph_zoom: float = 1.0,
    graph_position_x: float = 0.0,
    graph_position_y: float = 0.0,
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
            professor_zoom=professor_zoom,
            professor_position_x=professor_position_x,
            professor_position_y=professor_position_y,
            graph_zoom=graph_zoom,
            graph_position_x=graph_position_x,
            graph_position_y=graph_position_y,
        )
        results.append(result)
        if progress:
            progress(index, len(selected), operation, result)
    return results
