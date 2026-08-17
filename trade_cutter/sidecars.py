from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Cue, Operation, Scene


def sidecar_paths(output_path: str | Path) -> dict[str, Path]:
    video = Path(output_path)
    return {
        "transcript": video.with_name(f"{video.stem}.transcript.vtt"),
        "captions": video.with_name(f"{video.stem}.srt"),
        "edit_map": video.with_name(f"{video.stem}.edit.json"),
    }


def _speed(scene: Scene) -> float:
    return min(max(float(scene.playback_speed or 1.0), 0.1), 100.0)


def _resolved_audio(scene: Scene, project_audio: str) -> str:
    if scene.audio_mode in {"professor", "screen", "mute"}:
        return scene.audio_mode
    return project_audio


def _ordered_timeline(operations: list[Operation]) -> list[tuple[Operation, Scene]]:
    selected = [
        (index, operation)
        for index, operation in enumerate(operations)
        if operation.selected
    ]
    selected.sort(
        key=lambda item: (
            item[1].sequence_order if item[1].sequence_order > 0 else item[0] + 1,
            item[0],
        )
    )
    return [
        (operation, scene)
        for _, operation in selected
        for scene in sorted(operation.ensure_scenes(), key=lambda item: (item.start, item.end))
    ]


def _timeline_segments(
    operations: list[Operation],
    *,
    orientation: str,
    project_audio: str,
    professor_sync_offset: float,
    captions_enabled: bool,
    opening_duration: float = 0.0,
) -> tuple[list[tuple[Operation, Scene, float, float]], list[dict[str, Any]]]:
    timeline: list[tuple[Operation, Scene, float, float]] = []
    records: list[dict[str, Any]] = []
    cursor = max(0.0, float(opening_duration))
    for operation, scene in _ordered_timeline(operations):
        speed = _speed(scene)
        output_duration = 0.0 if scene.skip else max(0.0, scene.end - scene.start) / speed
        output_start = cursor
        output_end = cursor + output_duration
        resolved_audio = _resolved_audio(scene, project_audio)
        effects = [
            {
                "id": effect.id,
                "kind": effect.kind,
                "keyword": effect.keyword,
                "text": effect.text,
                "source": {
                    "start": max(effect.start, scene.start),
                    "end": min(effect.end, scene.end),
                },
                "output": {
                    "start": output_start
                    + (max(effect.start, scene.start) - scene.start) / speed,
                    "end": output_start
                    + (min(effect.end, scene.end) - scene.start) / speed,
                },
            }
            for effect in operation.effects
            if not scene.skip and effect.end > scene.start and effect.start < scene.end
        ]
        if not scene.skip:
            timeline.append((operation, scene, output_start, output_end))
        records.append(
            {
                "operation_id": operation.id,
                "operation_title": operation.title,
                "scene_id": scene.id,
                "layout": scene.layout,
                "orientation": orientation,
                "source": {
                    "screen_start": scene.start,
                    "screen_end": scene.end,
                    "professor_start": max(0.0, scene.start + professor_sync_offset),
                    "professor_end": max(0.0, scene.end + professor_sync_offset),
                },
                "output": {
                    "start": output_start,
                    "end": output_end,
                    "duration": output_duration,
                },
                "speed": speed,
                "skipped": bool(scene.skip),
                "audio": resolved_audio,
                "captions_enabled": bool(
                    captions_enabled and scene.subtitles_enabled and not scene.skip
                ),
                "effects": effects,
                "crop": {
                    "area": operation.crop_area,
                    "x": operation.crop_x,
                    "y": operation.crop_y,
                    "width": operation.crop_width,
                    "height": operation.crop_height,
                },
                "framing": {
                    "professor_zoom": scene.professor_zoom,
                    "professor_x": scene.professor_x,
                    "professor_y": scene.professor_y,
                    "graph_zoom": scene.graph_zoom,
                    "graph_x": scene.graph_x,
                    "graph_y": scene.graph_y,
                    "graph_alignment": scene.graph_alignment,
                },
            }
        )
        cursor = output_end
    return timeline, records


def _mapped_cues(
    timeline: list[tuple[Operation, Scene, float, float]],
    cues: list[Cue],
    *,
    captions_only: bool,
    speaker: str,
) -> list[dict[str, Any]]:
    selected_speaker = speaker.strip().casefold()
    mapped: list[dict[str, Any]] = []
    for _operation, scene, output_start, _output_end in timeline:
        speed = _speed(scene)
        for cue in cues:
            if cue.end <= scene.start or cue.start >= scene.end:
                continue
            if (
                captions_only
                and selected_speaker
                and cue.speaker.strip().casefold() != selected_speaker
            ):
                continue
            start = output_start + (max(cue.start, scene.start) - scene.start) / speed
            end = output_start + (min(cue.end, scene.end) - scene.start) / speed
            if end <= start:
                continue
            text = " ".join(cue.text.split())
            if not text:
                continue
            if cue.speaker and (not captions_only or not selected_speaker):
                text = f"{cue.speaker}: {text}"
            mapped.append(
                {
                    "start": start,
                    "end": end,
                    "speaker": cue.speaker,
                    "text": text,
                    "source_start": cue.start,
                    "source_end": cue.end,
                }
            )
    mapped.sort(key=lambda item: (item["start"], item["end"], item["text"]))
    return mapped


def _timestamp(seconds: float, *, decimal_separator: str) -> str:
    total_ms = max(0, int(round(float(seconds) * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, milliseconds = divmod(remainder, 1000)
    return (
        f"{hours:02d}:{minutes:02d}:{secs:02d}"
        f"{decimal_separator}{milliseconds:03d}"
    )


def build_vtt(cues: list[dict[str, Any]]) -> str:
    rows = ["WEBVTT", ""]
    for index, cue in enumerate(cues, 1):
        rows.extend(
            (
                str(index),
                f"{_timestamp(cue['start'], decimal_separator='.')} --> "
                f"{_timestamp(cue['end'], decimal_separator='.')}",
                cue["text"],
                "",
            )
        )
    return "\n".join(rows)


def build_srt(cues: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for index, cue in enumerate(cues, 1):
        rows.extend(
            (
                str(index),
                f"{_timestamp(cue['start'], decimal_separator=',')} --> "
                f"{_timestamp(cue['end'], decimal_separator=',')}",
                cue["text"],
                "",
            )
        )
    return "\n".join(rows)


def write_export_sidecars(
    output_path: str | Path,
    operations: list[Operation],
    *,
    video_path: str | Path,
    professor_video_path: str | Path,
    cues: list[Cue] | None,
    transcript_path: str | Path = "",
    orientation: str,
    project_audio: str,
    professor_sync_offset: float,
    captions_enabled: bool,
    caption_speaker: str,
    caption_style: str = "normal",
    opening_duration: float = 0.0,
    closing_duration: float = 0.0,
) -> dict[str, Path]:
    opening_duration = max(0.0, float(opening_duration))
    closing_duration = max(0.0, float(closing_duration))
    paths = sidecar_paths(output_path)
    timeline, segments = _timeline_segments(
        operations,
        orientation=orientation,
        project_audio=project_audio,
        professor_sync_offset=professor_sync_offset,
        captions_enabled=captions_enabled,
        opening_duration=opening_duration,
    )
    content_end = segments[-1]["output"]["end"] if segments else opening_duration
    total_duration = content_end + closing_duration
    title_cards: list[dict[str, Any]] = []
    if opening_duration:
        title_cards.append(
            {
                "kind": "opening",
                "output": {
                    "start": 0.0,
                    "end": opening_duration,
                    "duration": opening_duration,
                },
            }
        )
    if closing_duration:
        title_cards.append(
            {
                "kind": "closing",
                "output": {
                    "start": content_end,
                    "end": total_duration,
                    "duration": closing_duration,
                },
            }
        )
    edit_map = {
        "version": 1,
        "video": str(Path(output_path).resolve()),
        "source_video": str(Path(video_path).resolve()),
        "professor_video": str(Path(professor_video_path).resolve()),
        "transcript_source": str(Path(transcript_path).resolve()) if transcript_path else "",
        "orientation": orientation,
        "project_audio": project_audio,
        "professor_sync_offset": professor_sync_offset,
        "caption_speaker": caption_speaker,
        "caption_style": caption_style,
        "captions_enabled": captions_enabled,
        "output_duration": total_duration,
        "title_cards": title_cards,
        "segments": segments,
    }
    paths["edit_map"].write_text(
        json.dumps(edit_map, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if cues is not None:
        transcript_cues = _mapped_cues(
            timeline,
            cues,
            captions_only=False,
            speaker="",
        )
        caption_cues = _mapped_cues(
            timeline,
            cues,
            captions_only=True,
            speaker=caption_speaker,
        )
        if not caption_cues and caption_speaker:
            caption_cues = _mapped_cues(
                timeline,
                cues,
                captions_only=True,
                speaker="",
            )
        paths["transcript"].write_text(build_vtt(transcript_cues), encoding="utf-8")
        paths["captions"].write_text(build_srt(caption_cues), encoding="utf-8-sig")
    return paths
