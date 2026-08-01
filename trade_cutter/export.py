from __future__ import annotations

import json
from pathlib import Path

from .models import (
    OUTPUT_LAYOUT_LABELS,
    OUTPUT_ORIENTATION_LABELS,
    SCENE_AUDIO_LABELS,
    SCENE_LAYOUT_LABELS,
    Operation,
)
from .timecode import format_timecode


AREA_LABELS = {
    "full": "Vídeo completo",
    "flex_index": "Flex - Índice",
    "flex_dollar": "Flex - Dólar",
    "profit_index": "Profit - Índice",
    "profit_dollar": "Profit - Dólar",
}


def save_operations(path: str | Path, operations: list[Operation], transcript_path: str = "") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 6,
        "transcript": transcript_path,
        "operations": [operation.to_dict() for operation in operations],
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def load_operations(path: str | Path) -> list[Operation]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    raw = payload.get("operations", payload if isinstance(payload, list) else [])
    return [Operation.from_dict(item) for item in raw]


def create_html_report(path: str | Path, operations: list[Operation], video_path: str = "") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    rows: list[str] = []
    cards: list[str] = []
    for index, operation in enumerate(operations, 1):
        checked = "checked" if operation.selected else ""
        area = AREA_LABELS.get(operation.crop_area, operation.crop_area)
        layout = OUTPUT_LAYOUT_LABELS.get(operation.layout_mode, operation.layout_mode)
        switch_time = (
            format_timecode(operation.layout_switch_time)
            if operation.layout_switch_time is not None
            else "—"
        )
        scene_summary = " · ".join(
            f"{format_timecode(scene.start)}–{format_timecode(scene.end)} "
            f"{SCENE_LAYOUT_LABELS.get(scene.layout, scene.layout)} · "
            f"{scene.playback_speed:g}× · "
            f"{SCENE_AUDIO_LABELS.get(scene.audio_mode, scene.audio_mode)} · "
            f"legendas {'sim' if scene.subtitles_enabled else 'não'} · "
            f"{'salto removido' if scene.skip else 'incluída'}"
            for scene in operation.ensure_scenes()
        )
        orientation = OUTPUT_ORIENTATION_LABELS.get(
            operation.output_orientation, operation.output_orientation
        )
        rows.append(
            f"""<tr>
<td><input type=\"checkbox\" {checked} disabled></td>
<td>{index}</td><td>{_escape(operation.title)}</td>
<td>{format_timecode(operation.entry_time)}</td>
<td>{format_timecode(operation.cut_start)}</td>
<td>{format_timecode(operation.cut_end)}</td>
<td>{_escape(area)}</td>
<td>{_escape(layout)}</td>
<td>{operation.sequence_order}</td><td>{_escape(orientation)}</td><td>{len(operation.scenes)}</td>
<td>{operation.confidence:.0%}</td><td>{_escape(operation.result)}</td>
</tr>"""
        )
        evidence = "".join(f"<li>{_escape(item)}</li>" for item in operation.evidence)
        cards.append(
            f"""<section class=\"card\">
<h2>{index}. {_escape(operation.title)}</h2>
<p><b>Corte:</b> {format_timecode(operation.cut_start)} - {format_timecode(operation.cut_end)} · <b>Entrada:</b> {format_timecode(operation.entry_time)} · <b>Área:</b> {_escape(area)} · <b>Formato:</b> {_escape(layout)} · <b>Mudança:</b> {switch_time} · <b>Confiança:</b> {operation.confidence:.0%}</p>
<p><b>Resultado:</b> {_escape(operation.result)}</p>
<p><b>Cenas:</b> {_escape(scene_summary)}</p>
<ul>{evidence}</ul>
</section>"""
        )

    video_note = f"<p><b>Vídeo:</b> {_escape(video_path)}</p>" if video_path else ""
    html = f"""<!doctype html>
<html lang=\"pt-BR\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>Relatório de cortes</title>
<style>
body{{font-family:Arial,sans-serif;margin:0;background:#f5f6f8;color:#1d2530}}main{{max-width:1180px;margin:32px auto;padding:0 18px}}
table{{width:100%;border-collapse:collapse;background:#fff;box-shadow:0 2px 12px #0001}}th,td{{padding:10px;border-bottom:1px solid #e5e7eb;text-align:left}}th{{background:#111827;color:#fff;position:sticky;top:0}}.card{{background:#fff;margin:18px 0;padding:18px;border-radius:12px;box-shadow:0 2px 12px #0001}}code{{background:#eef2f7;padding:2px 5px;border-radius:5px}}
</style></head><body><main>
<h1>Operações detectadas</h1>{video_note}
<table><thead><tr><th>Usar</th><th>#</th><th>Operação</th><th>Entrada</th><th>Início</th><th>Fim</th><th>Área</th><th>Formato legado</th><th>Ordem</th><th>Orientação</th><th>Cenas</th><th>Confiança</th><th>Resultado</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
{''.join(cards)}
</main></body></html>"""
    target.write_text(html, encoding="utf-8")
    return target


def _escape(value: object) -> str:
    import html

    return html.escape(str(value), quote=True)
