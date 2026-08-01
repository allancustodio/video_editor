from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Callable

from .models import Cue, Operation, Scene
from .sidecars import write_export_sidecars
from .timecode import format_timecode


ProgressCallback = Callable[[int, int, Operation, Path], None]

DEFAULT_FFMPEG_PATH = r"C:\Users\allan\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.2-full_build\bin\ffmpeg.exe"


def default_ffmpeg_path() -> str:
    """Return the project default when installed, otherwise an empty value."""
    return DEFAULT_FFMPEG_PATH if Path(DEFAULT_FFMPEG_PATH).exists() else ""


def find_ffmpeg(explicit_path: str = "") -> str:
    if explicit_path:
        path = Path(explicit_path)
        if path.exists():
            return str(path)
        raise FileNotFoundError(f"FFmpeg não encontrado em: {explicit_path}")
    project_default = default_ffmpeg_path()
    if project_default:
        return project_default
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


def create_preview_clip(
    video_path: str | Path,
    start_time: float,
    end_time: float,
    *,
    ffmpeg_path: str = "",
    cache_dir: str | Path | None = None,
    max_width: int = 1280,
) -> Path:
    """Create and cache a lightweight clip suitable for Streamlit playback."""
    ffmpeg = find_ffmpeg(ffmpeg_path)
    source = Path(video_path)
    if not source.exists():
        raise FileNotFoundError(f"Vídeo não encontrado: {source}")

    start = max(0.0, float(start_time))
    end = max(0.0, float(end_time))
    if end <= start:
        raise ValueError("O fim da prévia precisa ser posterior ao início.")
    if max_width < 2:
        raise ValueError("A largura máxima da prévia precisa ser maior que 1.")

    source_stat = source.stat()
    signature = "|".join(
        (
            "streamlit-preview-v2",
            str(source.resolve()),
            str(source_stat.st_size),
            str(source_stat.st_mtime_ns),
            f"{start:.3f}",
            f"{end:.3f}",
            str(max_width),
        )
    )
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:24]
    preview_dir = (
        Path(cache_dir)
        if cache_dir is not None
        else Path(tempfile.gettempdir()) / "trade-video-cutter" / "previews"
    )
    preview_dir.mkdir(parents=True, exist_ok=True)
    target = preview_dir / f"{digest}.mp4"
    if target.exists() and target.stat().st_size > 0:
        return target

    temporary_target = preview_dir / f"{digest}.building.mp4"
    duration = end - start
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        format_timecode(start, milliseconds=True),
        "-i",
        str(source),
        "-t",
        f"{duration:.3f}",
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        (
            f"scale={max_width}:-2:force_original_aspect_ratio=decrease,"
            "setpts=PTS-STARTPTS"
        ),
        "-af",
        "aresample=async=1:first_pts=0",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "28",
        "-c:a",
        "aac",
        "-ac",
        "2",
        "-ar",
        "48000",
        "-b:a",
        "128k",
        "-avoid_negative_ts",
        "make_zero",
        "-movflags",
        "+faststart",
        "-sn",
        "-dn",
        str(temporary_target),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        temporary_target.unlink(missing_ok=True)
        raise RuntimeError(
            "FFmpeg não conseguiu gerar a prévia leve:\n"
            f"{completed.stderr.strip()}"
        )
    if not temporary_target.exists() or temporary_target.stat().st_size == 0:
        temporary_target.unlink(missing_ok=True)
        raise RuntimeError("FFmpeg não gerou o arquivo da prévia leve.")

    temporary_target.replace(target)
    return target


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


def _graph_position(alignment: str, fine_position: float) -> float:
    """Combine a graph edge anchor with the scene's existing fine adjustment."""
    base_position = {
        "left": -100.0,
        "center": 0.0,
        "right": 100.0,
    }.get(alignment, 0.0)
    return min(max(base_position + float(fine_position), -100.0), 100.0)


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


def _professor_full_filter(
    *,
    width: int = 1080,
    height: int = 1920,
    zoom: float = 1.0,
    position_x: float = 0.0,
    position_y: float = 0.0,
) -> str:
    zoom = min(max(zoom, 1.0), 3.0)
    scaled_width = _even_size(width * zoom)
    scaled_height = _even_size(height * zoom)
    anchor_x = _position_anchor(position_x)
    anchor_y = _position_anchor(position_y)
    return (
        f"scale={scaled_width}:{scaled_height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}:(iw-ow)*{anchor_x:.6f}:(ih-oh)*{anchor_y:.6f},"
        "setsar=1,format=yuv420p"
    )


def _mixed_vertical_filter(
    operation: Operation,
    *,
    switch_time: float,
    professor_zoom: float = 1.0,
    professor_position_x: float = 0.0,
    professor_position_y: float = 0.0,
    graph_zoom: float = 1.0,
    graph_position_x: float = 0.0,
    graph_position_y: float = 0.0,
    full_professor_zoom: float = 1.0,
    full_professor_position_x: float = 0.0,
    full_professor_position_y: float = 0.0,
) -> str:
    professor_zoom = min(max(professor_zoom, 1.0), 3.0)
    graph_zoom = min(max(graph_zoom, 1.0), 3.0)
    professor_width = _even_size(1080 * professor_zoom)
    professor_height = _even_size(960 * professor_zoom)
    graph_width = _even_size(1080 * graph_zoom)
    graph_height = _even_size(960 * graph_zoom)
    professor_x = _position_anchor(professor_position_x)
    professor_y = _position_anchor(professor_position_y)
    graph_x = _even_offset(
        max(0, graph_width - 1080) * _position_anchor(graph_position_x)
    )
    graph_y = _even_offset(
        max(0, graph_height - 960) * _position_anchor(graph_position_y)
    )
    graph_filter = _crop_filter(operation) if operation.crop_area != "full" else "null"
    full_filter = _professor_full_filter(
        zoom=full_professor_zoom,
        position_x=full_professor_position_x,
        position_y=full_professor_position_y,
    )
    return (
        "[0:v]setpts=PTS-STARTPTS[screen_source];"
        "[1:v]setpts=PTS-STARTPTS,split=2[professor_split_source][professor_full_source];"
        f"[screen_source]{graph_filter},"
        f"scale={graph_width}:{graph_height}:force_original_aspect_ratio=decrease,"
        f"pad={graph_width}:{graph_height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"crop=1080:960:{graph_x}:{graph_y},setsar=1[graph];"
        f"[professor_split_source]scale={professor_width}:{professor_height}:"
        "force_original_aspect_ratio=increase,"
        f"crop=1080:960:(iw-ow)*{professor_x:.6f}:(ih-oh)*{professor_y:.6f},"
        "setsar=1[professor_split];"
        "[professor_split][graph]vstack=inputs=2,format=yuv420p[split_layout];"
        f"[professor_full_source]{full_filter}[full_layout];"
        f"[split_layout][full_layout]overlay=0:0:"
        f"enable='gte(t,{switch_time:.3f})',format=yuv420p[v]"
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


def capture_professor_frame(
    professor_video_path: str | Path,
    time_seconds: float,
    *,
    ffmpeg_path: str = "",
    zoom: float = 1.0,
    position_x: float = 0.0,
    position_y: float = 0.0,
) -> bytes:
    """Return one 1080x1920 professor-only JPEG using the final framing."""
    ffmpeg = find_ffmpeg(ffmpeg_path)
    professor = Path(professor_video_path)
    if not professor_video_path or not professor.exists():
        raise FileNotFoundError(f"Vídeo do professor não encontrado: {professor}")
    video_filter = _professor_full_filter(
        zoom=zoom,
        position_x=position_x,
        position_y=position_y,
    )
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-ss", format_timecode(max(0.0, time_seconds), milliseconds=True),
        "-i", str(professor),
        "-vf", video_filter,
        "-frames:v", "1",
        "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
    ]
    completed = subprocess.run(command, capture_output=True, check=False)
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            "FFmpeg não conseguiu gerar a prévia do professor:\n"
            f"{message}"
        )
    return completed.stdout


def cut_video(
    video_path: str | Path,
    operation: Operation,
    output_path: str | Path,
    *,
    mode: str = "exact",
    ffmpeg_path: str = "",
    output_format: str | None = None,
    professor_video_path: str | Path = "",
    professor_sync_offset: float = 0.0,
    audio_source: str = "professor",
    professor_zoom: float = 1.0,
    professor_position_x: float = 0.0,
    professor_position_y: float = 0.0,
    graph_zoom: float = 1.0,
    graph_position_x: float = 0.0,
    graph_position_y: float = 0.0,
    full_professor_zoom: float = 1.0,
    full_professor_position_x: float = 0.0,
    full_professor_position_y: float = 0.0,
) -> Path:
    resolved_format = output_format or operation.layout_mode
    if resolved_format == "vertical":
        resolved_format = "split_vertical"
    allowed_formats = {
        "original",
        "split_vertical",
        "professor_vertical",
        "professor_horizontal",
        "split_then_professor",
    }
    if resolved_format not in allowed_formats:
        raise ValueError(f"Formato de saída inválido: {resolved_format}")
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

    if resolved_format != "original":
        professor = Path(professor_video_path)
        if not professor_video_path or not professor.exists():
            raise FileNotFoundError(f"Vídeo do professor não encontrado: {professor}")

        professor_start = format_timecode(
            max(0.0, operation.cut_start + professor_sync_offset), milliseconds=True
        )
        if resolved_format == "split_vertical":
            filter_complex = _vertical_filter(
                operation,
                professor_zoom=professor_zoom,
                professor_position_x=professor_position_x,
                professor_position_y=professor_position_y,
                graph_zoom=graph_zoom,
                graph_position_x=graph_position_x,
                graph_position_y=graph_position_y,
            )
        elif resolved_format == "professor_vertical":
            filter_complex = (
                f"[1:v]setpts=PTS-STARTPTS,"
                f"{_professor_full_filter(zoom=full_professor_zoom, position_x=full_professor_position_x, position_y=full_professor_position_y)}[v]"
            )
        elif resolved_format == "professor_horizontal":
            filter_complex = "[1:v]setpts=PTS-STARTPTS,setsar=1,format=yuv420p[v]"
        else:
            switch_at = operation.layout_switch_time
            if (
                switch_at is None
                or switch_at <= operation.cut_start
                or switch_at >= operation.cut_end
            ):
                raise ValueError(
                    f'O corte "{operation.title}" precisa de um horário de mudança '
                    "entre o início e o fim."
                )
            filter_complex = _mixed_vertical_filter(
                operation,
                switch_time=switch_at - operation.cut_start,
                professor_zoom=professor_zoom,
                professor_position_x=professor_position_x,
                professor_position_y=professor_position_y,
                graph_zoom=graph_zoom,
                graph_position_x=graph_position_x,
                graph_position_y=graph_position_y,
                full_professor_zoom=full_professor_zoom,
                full_professor_position_x=full_professor_position_x,
                full_professor_position_y=full_professor_position_y,
            )
        audio_input = "0:a:0?" if audio_source == "screen" else "1:a:0?"
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
    output_format: str | None = None,
    professor_video_path: str | Path = "",
    professor_sync_offset: float = 0.0,
    audio_source: str = "professor",
    professor_zoom: float = 1.0,
    professor_position_x: float = 0.0,
    professor_position_y: float = 0.0,
    graph_zoom: float = 1.0,
    graph_position_x: float = 0.0,
    graph_position_y: float = 0.0,
    full_professor_zoom: float = 1.0,
    full_professor_position_x: float = 0.0,
    full_professor_position_y: float = 0.0,
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
            full_professor_zoom=full_professor_zoom,
            full_professor_position_x=full_professor_position_x,
            full_professor_position_y=full_professor_position_y,
        )
        results.append(result)
        if progress:
            progress(index, len(selected), operation, result)
    return results


def _scene_box_filter(
    input_label: str,
    output_label: str,
    *,
    width: int,
    height: int,
    zoom: float,
    position_x: float,
    position_y: float,
    source_filter: str = "null",
) -> str:
    zoom = min(max(float(zoom), 1.0), 3.0)
    scaled_width = _even_size(width * zoom)
    scaled_height = _even_size(height * zoom)
    anchor_x = _position_anchor(position_x)
    anchor_y = _position_anchor(position_y)
    return (
        f"{input_label}setpts=PTS-STARTPTS,{source_filter},"
        f"scale={scaled_width}:{scaled_height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}:(iw-ow)*{anchor_x:.6f}:(ih-oh)*{anchor_y:.6f},"
        f"setsar=1[{output_label}]"
    )


def _scene_speed(scene: Scene) -> float:
    return min(max(float(scene.playback_speed or 1.0), 0.1), 100.0)


def _ass_time(seconds: float) -> str:
    total_centiseconds = max(0, int(round(float(seconds) * 100)))
    hours, remainder = divmod(total_centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def _subtitle_text(value: str, *, width: int) -> str:
    cleaned = " ".join(value.replace("{", "").replace("}", "").split())
    lines = textwrap.wrap(cleaned, width=width, break_long_words=False, break_on_hyphens=False)
    if not lines:
        return ""
    if len(lines) > 2:
        remainder = " ".join(lines[1:])
        lines = [lines[0], textwrap.shorten(remainder, width=width, placeholder="…")]
    return r"\N".join(lines[:2])


def _subtitle_words(value: str) -> list[str]:
    cleaned = value.replace("{", "").replace("}", "").replace("\\", "")
    return " ".join(cleaned.split()).split()


def _highlight_subtitle_text(words: list[str], active_index: int, *, width: int) -> str:
    indexed = list(enumerate(words))
    lines: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    current_length = 0
    for item in indexed:
        word_length = len(item[1])
        projected = current_length + (1 if current else 0) + word_length
        if current and projected > width:
            lines.append(current)
            current = [item]
            current_length = word_length
        else:
            current.append(item)
            current_length = projected
    if current:
        lines.append(current)
    active_line = next(
        (index for index, line in enumerate(lines) if any(i == active_index for i, _ in line)),
        0,
    )
    page_start = (active_line // 2) * 2
    visible_lines = lines[page_start:page_start + 2]
    rendered: list[str] = []
    for line in visible_lines:
        values: list[str] = []
        for index, word in line:
            if index == active_index:
                values.append(
                    r"{\c&H0023A6F5&\3c&H00040608&\bord3}" + word
                    + r"{\c&H00DDEBF3&\bord2}"
                )
            else:
                values.append(word)
        rendered.append(" ".join(values))
    return r"\N".join(rendered)


def build_scene_ass(
    cues: list[Cue],
    scene: Scene,
    orientation: str,
    *,
    speaker: str = "",
    subtitle_style: str = "normal",
) -> str:
    """Build burned-in captions retimed to one scene's output clock."""
    if subtitle_style not in {"normal", "highlight"}:
        raise ValueError(f"Estilo de legenda inválido: {subtitle_style}")
    if orientation == "vertical":
        width, height, font_size = 1080, 1920, 54
        margin_v = 1040 if scene.layout == "professor_top" else 120
        line_width = 34
    elif orientation == "horizontal":
        width, height, font_size = 1920, 1080, 42
        margin_v = 590 if scene.layout == "professor_top" else 70
        line_width = 54
    else:
        raise ValueError(f"Orientação inválida: {orientation}")

    speed = _scene_speed(scene)
    selected_speaker = speaker.strip().casefold()
    dialogue: list[str] = []
    for cue in cues:
        if cue.end <= scene.start or cue.start >= scene.end:
            continue
        if selected_speaker and cue.speaker.strip().casefold() != selected_speaker:
            continue
        if subtitle_style == "normal":
            text = _subtitle_text(cue.text, width=line_width)
            if not text:
                continue
            start = (max(cue.start, scene.start) - scene.start) / speed
            end = (min(cue.end, scene.end) - scene.start) / speed
            if end <= start:
                continue
            dialogue.append(
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{text}"
            )
            continue

        words = _subtitle_words(cue.text)
        if not words:
            continue
        weights = [max(1, len(re.sub(r"\W+", "", word))) for word in words]
        total_weight = sum(weights)
        cue_duration = max(0.0, cue.end - cue.start)
        elapsed_weight = 0
        for word_index, weight in enumerate(weights):
            word_start = cue.start + cue_duration * elapsed_weight / total_weight
            elapsed_weight += weight
            word_end = cue.start + cue_duration * elapsed_weight / total_weight
            clipped_start = max(word_start, scene.start)
            clipped_end = min(word_end, scene.end)
            if clipped_end <= clipped_start:
                continue
            start = (clipped_start - scene.start) / speed
            end = (clipped_end - scene.start) / speed
            text = _highlight_subtitle_text(words, word_index, width=line_width)
            dialogue.append(
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{text}"
            )

    if subtitle_style == "highlight":
        primary = "&H00DDEBF3"
        secondary = "&H0023A6F5"
        outline = "&H00040608"
    else:
        primary = "&H00FFFFFF"
        secondary = "&H000000FF"
        outline = "&H00000000"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},{primary},{secondary},{outline},&H90000000,-1,0,0,0,100,100,0,0,3,2,0,2,55,55,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    return header + "\n".join(dialogue) + ("\n" if dialogue else "")


def _subtitle_filter(path: Path) -> str:
    escaped = path.resolve().as_posix().replace(":", r"\:").replace("'", r"\'")
    return f"subtitles=filename='{escaped}'"


def _atempo_filters(speed: float) -> list[str]:
    """Use factors up to 2x so this also works with older FFmpeg builds."""
    remaining = speed
    factors: list[float] = []
    while remaining > 2.0 + 1e-6:
        factors.append(2.0)
        remaining /= 2.0
    if abs(remaining - 1.0) > 1e-6:
        factors.append(remaining)
    return [f"atempo={factor:.6f}" for factor in factors]


def _scene_audio_filter(source_label: str | None, speed: float, duration: float) -> str:
    if source_label is None:
        return (
            "anullsrc=channel_layout=stereo:sample_rate=48000,"
            f"atrim=duration={duration:.6f},asetpts=PTS-STARTPTS[a]"
        )

    filters = [
        f"[{source_label}]aresample=async=1:first_pts=0",
        "asetpts=PTS-STARTPTS",
        *_atempo_filters(speed),
        f"atrim=duration={duration:.6f}",
        "asetpts=PTS-STARTPTS",
    ]
    fade_duration = min(0.05, duration / 4)
    if fade_duration > 0.005:
        filters.extend(
            (
                f"afade=t=in:st=0:d={fade_duration:.6f}",
                f"afade=t=out:st={max(0.0, duration - fade_duration):.6f}:"
                f"d={fade_duration:.6f}",
            )
        )
    return ",".join(filters) + "[a]"


def scene_filter(
    operation: Operation,
    scene: Scene,
    orientation: str,
    *,
    subtitle_path: Path | None = None,
) -> str:
    """Build one normalized scene layout for either 9:16 or 16:9 output."""
    if orientation == "vertical":
        width, height = 1080, 1920
    elif orientation == "horizontal":
        width, height = 1920, 1080
    else:
        raise ValueError(f"Orientação inválida: {orientation}")
    if scene.layout not in {
        "graph_full",
        "professor_full",
        "professor_top",
        "graph_top",
        "side_by_side",
    }:
        raise ValueError(f"Composição de cena inválida: {scene.layout}")

    graph_source_filter = _crop_filter(operation) if operation.crop_area != "full" else "null"
    graph_position_x = _graph_position(scene.graph_alignment, scene.graph_x)
    if scene.layout == "graph_full":
        filters = _scene_box_filter(
            "[0:v]", "scene",
            width=width, height=height,
            zoom=scene.graph_zoom,
            position_x=graph_position_x,
            position_y=scene.graph_y,
            source_filter=graph_source_filter,
        )
    elif scene.layout == "professor_full":
        filters = _scene_box_filter(
            "[1:v]", "scene",
            width=width, height=height,
            zoom=scene.professor_zoom,
            position_x=scene.professor_x,
            position_y=scene.professor_y,
        )
    elif scene.layout in {"professor_top", "graph_top"}:
        slot_height = height // 2
        professor = _scene_box_filter(
            "[1:v]", "professor",
            width=width, height=slot_height,
            zoom=scene.professor_zoom,
            position_x=scene.professor_x,
            position_y=scene.professor_y,
        )
        graph = _scene_box_filter(
            "[0:v]", "graph",
            width=width, height=slot_height,
            zoom=scene.graph_zoom,
            position_x=graph_position_x,
            position_y=scene.graph_y,
            source_filter=graph_source_filter,
        )
        inputs = "[professor][graph]" if scene.layout == "professor_top" else "[graph][professor]"
        filters = f"{professor};{graph};{inputs}vstack=inputs=2[scene]"
    else:
        slot_width = width // 2
        professor = _scene_box_filter(
            "[1:v]", "professor",
            width=slot_width, height=height,
            zoom=scene.professor_zoom,
            position_x=scene.professor_x,
            position_y=scene.professor_y,
        )
        graph = _scene_box_filter(
            "[0:v]", "graph",
            width=slot_width, height=height,
            zoom=scene.graph_zoom,
            position_x=graph_position_x,
            position_y=scene.graph_y,
            source_filter=graph_source_filter,
        )
        filters = f"{professor};{graph};[professor][graph]hstack=inputs=2[scene]"
    speed = _scene_speed(scene)
    final_filters = (
        f"[scene]setpts=(PTS-STARTPTS)/{speed:.6f},fps=30,format=yuv420p"
    )
    if subtitle_path is not None:
        final_filters += f",{_subtitle_filter(subtitle_path)}"
    return f"{filters};{final_filters}[v]"


def capture_scene_frame(
    video_path: str | Path,
    professor_video_path: str | Path,
    operation: Operation,
    scene: Scene,
    *,
    orientation: str = "vertical",
    ffmpeg_path: str = "",
    professor_sync_offset: float = 0.0,
) -> bytes:
    """Return a JPEG preview using exactly the selected scene composition."""
    ffmpeg = find_ffmpeg(ffmpeg_path)
    source = Path(video_path)
    professor = Path(professor_video_path)
    if not source.exists():
        raise FileNotFoundError(f"Vídeo não encontrado: {source}")
    if not professor_video_path or not professor.exists():
        raise FileNotFoundError(f"Vídeo do professor não encontrado: {professor}")
    filter_complex = scene_filter(operation, scene, orientation)
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-ss", format_timecode(max(0.0, scene.start), milliseconds=True),
        "-i", str(source),
        "-ss", format_timecode(max(0.0, scene.start + professor_sync_offset), milliseconds=True),
        "-i", str(professor),
        "-filter_complex", filter_complex,
        "-map", "[v]", "-frames:v", "1",
        "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
    ]
    completed = subprocess.run(command, capture_output=True, check=False)
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"FFmpeg não conseguiu gerar a prévia da cena:\n{message}")
    return completed.stdout


def render_scene_video(
    video_path: str | Path,
    professor_video_path: str | Path,
    operation: Operation,
    scene: Scene,
    output_path: str | Path,
    *,
    orientation: str = "vertical",
    ffmpeg_path: str = "",
    professor_sync_offset: float = 0.0,
    audio_source: str = "professor",
    cues: list[Cue] | None = None,
    subtitle_speaker: str = "",
    subtitle_style: str = "normal",
) -> Path:
    """Render one timeline scene to a normalized MP4 segment."""
    if scene.end <= scene.start:
        raise ValueError("O fim da cena precisa ser posterior ao início.")
    if audio_source not in {"professor", "screen"}:
        raise ValueError(f"Fonte de áudio inválida: {audio_source}")
    ffmpeg = find_ffmpeg(ffmpeg_path)
    source = Path(video_path)
    professor = Path(professor_video_path)
    if not source.exists():
        raise FileNotFoundError(f"Vídeo não encontrado: {source}")
    if not professor_video_path or not professor.exists():
        raise FileNotFoundError(f"Vídeo do professor não encontrado: {professor}")
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    speed = _scene_speed(scene)
    duration = (scene.end - scene.start) / speed
    resolved_audio = scene.audio_mode if scene.audio_mode != "project" else audio_source
    if resolved_audio not in {"professor", "screen", "mute"}:
        resolved_audio = audio_source
    audio_input = {
        "screen": "0:a:0",
        "professor": "1:a:0",
        "mute": None,
    }[resolved_audio]

    subtitle_path: Path | None = None
    if scene.subtitles_enabled and cues:
        subtitle_content = build_scene_ass(
            cues,
            scene,
            orientation,
            speaker=subtitle_speaker,
            subtitle_style=subtitle_style,
        )
        if "Dialogue:" in subtitle_content:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8-sig",
                suffix=".ass",
                prefix="trade-cutter-captions-",
                dir=target.parent,
                delete=False,
            ) as subtitle_file:
                subtitle_file.write(subtitle_content)
                subtitle_path = Path(subtitle_file.name)

    filter_complex = (
        scene_filter(
            operation,
            scene,
            orientation,
            subtitle_path=subtitle_path,
        )
        + ";"
        + _scene_audio_filter(audio_input, speed, duration)
    )
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", format_timecode(max(0.0, scene.start), milliseconds=True),
        "-i", str(source),
        "-ss", format_timecode(max(0.0, scene.start + professor_sync_offset), milliseconds=True),
        "-i", str(professor),
        "-t", f"{duration:.3f}",
        "-filter_complex_threads", "1",
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-threads:v", "2",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", str(target),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    finally:
        if subtitle_path is not None:
            subtitle_path.unlink(missing_ok=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"FFmpeg falhou na cena {scene.id} de {operation.title}:\n"
            f"{completed.stderr.strip()}"
        )
    return target


def validate_scene_timeline(operation: Operation) -> list[Scene]:
    scenes = sorted(operation.ensure_scenes(), key=lambda item: (item.start, item.end))
    if not scenes:
        raise ValueError(f'O trecho "{operation.title}" não possui cenas.')
    tolerance = 0.05
    if abs(scenes[0].start - operation.cut_start) > tolerance:
        raise ValueError(f'A primeira cena de "{operation.title}" precisa começar no início do trecho.')
    if abs(scenes[-1].end - operation.cut_end) > tolerance:
        raise ValueError(f'A última cena de "{operation.title}" precisa terminar no fim do trecho.')
    for index, scene in enumerate(scenes):
        if scene.end <= scene.start:
            raise ValueError(f'A cena {index + 1} de "{operation.title}" tem duração inválida.')
        if index and abs(scene.start - scenes[index - 1].end) > tolerance:
            raise ValueError(f'As cenas de "{operation.title}" têm um espaço ou sobreposição.')
    return scenes


def export_final_video(
    video_path: str | Path,
    professor_video_path: str | Path,
    operations: list[Operation],
    output_path: str | Path,
    *,
    orientation: str = "vertical",
    ffmpeg_path: str = "",
    professor_sync_offset: float = 0.0,
    audio_source: str = "professor",
    cues: list[Cue] | None = None,
    burn_subtitles: bool = False,
    subtitle_speaker: str = "",
    subtitle_style: str = "normal",
    transcript_path: str | Path = "",
    progress: Callable[[int, int, str], None] | None = None,
) -> Path:
    """Render all selected cuts/scenes and concatenate them into one final MP4."""
    selected_with_index = [
        (index, operation)
        for index, operation in enumerate(operations)
        if operation.selected
    ]
    selected_with_index.sort(
        key=lambda item: (
            item[1].sequence_order if item[1].sequence_order > 0 else item[0] + 1,
            item[0],
        )
    )
    selected = [operation for _, operation in selected_with_index]
    if not selected:
        raise ValueError("Selecione pelo menos um trecho para exportar.")
    timeline = [
        (operation, scene)
        for operation in selected
        for scene in validate_scene_timeline(operation)
        if not scene.skip
    ]
    if not timeline:
        raise ValueError("Todas as cenas selecionadas estão marcadas como salto.")
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg(ffmpeg_path)

    with tempfile.TemporaryDirectory(prefix="trade-cutter-final-") as temporary:
        work = Path(temporary)
        segments: list[Path] = []
        total = len(timeline) + 1
        for index, (operation, scene) in enumerate(timeline, 1):
            segment = work / f"scene-{index:04d}.mp4"
            render_scene_video(
                video_path,
                professor_video_path,
                operation,
                scene,
                segment,
                orientation=orientation,
                ffmpeg_path=ffmpeg,
                professor_sync_offset=professor_sync_offset,
                audio_source=audio_source,
                cues=cues if burn_subtitles else None,
                subtitle_speaker=subtitle_speaker,
                subtitle_style=subtitle_style,
            )
            segments.append(segment)
            if progress:
                progress(index, total, f"Cena {index}/{len(timeline)} · {operation.title}")

        concat_file = work / "concat.txt"
        concat_file.write_text(
            "\n".join(f"file '{path.as_posix()}'" for path in segments),
            encoding="utf-8",
        )
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-c", "copy", "-movflags", "+faststart", str(target),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"FFmpeg não conseguiu montar o vídeo final:\n{completed.stderr.strip()}")
        write_export_sidecars(
            target,
            operations,
            video_path=video_path,
            professor_video_path=professor_video_path,
            cues=cues,
            transcript_path=transcript_path,
            orientation=orientation,
            project_audio=audio_source,
            professor_sync_offset=professor_sync_offset,
            captions_enabled=burn_subtitles,
            caption_speaker=subtitle_speaker,
            caption_style=subtitle_style,
        )
        if progress:
            progress(total, total, "Vídeo final e arquivos auxiliares concluídos")
    return target
