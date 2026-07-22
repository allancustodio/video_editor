from __future__ import annotations

import base64
import os
import tempfile
from dataclasses import replace
from pathlib import Path

import pandas as pd
import streamlit as st

from trade_cutter.ai import refine_operations
from trade_cutter.detector import DetectionConfig, detect_operations
from trade_cutter.export import create_html_report, save_operations
from trade_cutter.ffmpeg import capture_frame, cut_selected, cut_video, find_ffmpeg
from trade_cutter.models import Operation
from trade_cutter.timecode import format_timecode, parse_timecode
from trade_cutter.vtt import parse_vtt, transcript_between


st.set_page_config(page_title="Trade Video Cutter", page_icon="🎬", layout="wide")
st.title("🎬 Trade Video Cutter")
st.caption("Analisa a transcrição, permite revisar os horários e gera os cortes com FFmpeg no seu computador.")


AREA_LABELS = {
    "full": "Vídeo completo",
    "flex_index": "Flex - Índice",
    "flex_dollar": "Flex - Dólar",
    "profit_index": "Profit - Índice",
    "profit_dollar": "Profit - Dólar",
}
LABEL_TO_AREA = {label: key for key, label in AREA_LABELS.items()}
DEFAULT_CROP_PRESETS = {
    "flex_index": {"x": 0.000, "y": 0.000, "width": 0.250, "height": 1.000},
    "flex_dollar": {"x": 0.250, "y": 0.000, "width": 0.250, "height": 1.000},
    "profit_index": {"x": 0.500, "y": 0.000, "width": 0.250, "height": 1.000},
    # Na disposição enviada, a faixa final do Zoom fica fora do gráfico.
    "profit_dollar": {"x": 0.750, "y": 0.000, "width": 0.190, "height": 1.000},
}
PREVIEW_COLORS = {
    "flex_index": "#22c55e",
    "flex_dollar": "#06b6d4",
    "profit_index": "#f59e0b",
    "profit_dollar": "#ef4444",
}


def get_crop_presets() -> dict[str, dict[str, float]]:
    if "crop_presets" not in st.session_state:
        st.session_state["crop_presets"] = {
            key: dict(value) for key, value in DEFAULT_CROP_PRESETS.items()
        }
    return st.session_state["crop_presets"]


def apply_crop_preset(operation: Operation, presets: dict[str, dict[str, float]]) -> None:
    if operation.crop_area == "full":
        operation.crop_x = 0.0
        operation.crop_y = 0.0
        operation.crop_width = 1.0
        operation.crop_height = 1.0
        return

    preset = presets.get(operation.crop_area)
    if preset is None:
        operation.crop_area = "full"
        apply_crop_preset(operation, presets)
        return
    operation.crop_x = preset["x"]
    operation.crop_y = preset["y"]
    operation.crop_width = preset["width"]
    operation.crop_height = preset["height"]


def crop_preview_html(image: bytes, presets: dict[str, dict[str, float]]) -> str:
    encoded = base64.b64encode(image).decode("ascii")
    overlays: list[str] = []
    for key, preset in presets.items():
        overlays.append(
            f'<div style="position:absolute;left:{preset["x"] * 100:.3f}%;'
            f'top:{preset["y"] * 100:.3f}%;width:{preset["width"] * 100:.3f}%;'
            f'height:{preset["height"] * 100:.3f}%;box-sizing:border-box;'
            f'border:3px solid {PREVIEW_COLORS[key]};color:white;font-weight:700;'
            'font:13px Arial,sans-serif;text-shadow:0 1px 3px #000;overflow:hidden">'
            f'<span style="background:#000a;padding:2px 4px">{AREA_LABELS[key]}</span></div>'
        )
    return (
        '<div style="position:relative;width:100%;line-height:0">'
        f'<img src="data:image/jpeg;base64,{encoded}" style="width:100%;display:block">'
        f'{"".join(overlays)}</div>'
    )


def operation_rows(operations: list[Operation]) -> list[dict]:
    return [
        {
            "Usar": operation.selected,
            "Operação": operation.title,
            "Área": AREA_LABELS.get(operation.crop_area, AREA_LABELS["full"]),
            "Entrada": format_timecode(operation.entry_time),
            "Início": format_timecode(operation.cut_start),
            "Fim": format_timecode(operation.cut_end),
            "Confiança": round(operation.confidence * 100),
            "Resultado": operation.result,
            "Fonte": operation.source,
        }
        for operation in operations
    ]


def apply_rows(
    operations: list[Operation],
    rows,
    presets: dict[str, dict[str, float]],
) -> list[Operation]:
    edited: list[Operation] = []
    for operation, row in zip(operations, rows.to_dict("records")):
        operation.selected = bool(row["Usar"])
        operation.title = str(row["Operação"])
        operation.crop_area = LABEL_TO_AREA.get(str(row["Área"]), "full")

        entry_time = parse_timecode(row["Entrada"])
        cut_start = parse_timecode(row["Início"])
        cut_end = parse_timecode(row["Fim"])
        if entry_time is not None:
            operation.entry_time = entry_time
        if cut_start is not None:
            operation.cut_start = cut_start
        if cut_end is not None:
            operation.cut_end = cut_end

        operation.result = str(row["Resultado"])
        apply_crop_preset(operation, presets)
        edited.append(operation)
    return edited


def render_preset_editor(presets: dict[str, dict[str, float]]) -> None:
    st.caption("Valores em porcentagem do vídeo original. X/Y indicam o início da área.")
    for key in ("flex_index", "flex_dollar", "profit_index", "profit_dollar"):
        preset = presets[key]
        st.markdown(f"**{AREA_LABELS[key]}**")
        col_x, col_y, col_w, col_h = st.columns(4)
        x = col_x.number_input(
            "X (%)", 0.0, 99.9, preset["x"] * 100, 0.1, key=f"crop_{key}_x"
        )
        y = col_y.number_input(
            "Y (%)", 0.0, 99.9, preset["y"] * 100, 0.1, key=f"crop_{key}_y"
        )
        width = col_w.number_input(
            "Largura (%)", 0.1, 100.0, preset["width"] * 100, 0.1, key=f"crop_{key}_width"
        )
        height = col_h.number_input(
            "Altura (%)", 0.1, 100.0, preset["height"] * 100, 0.1, key=f"crop_{key}_height"
        )
        clipped_width = min(width, 100.0 - x)
        clipped_height = min(height, 100.0 - y)
        if clipped_width != width or clipped_height != height:
            st.warning(f"{AREA_LABELS[key]} ultrapassava o vídeo e foi limitada à borda.")
        presets[key] = {
            "x": x / 100.0,
            "y": y / 100.0,
            "width": clipped_width / 100.0,
            "height": clipped_height / 100.0,
        }
    st.session_state["crop_presets"] = presets


with st.sidebar:
    st.header("Configuração")
    transcript_upload = st.file_uploader("Transcrição VTT", type=["vtt"])
    default_transcript = str(Path("examples/GMT20260717-114920_Recording.transcript.vtt"))
    transcript_path = st.text_input("Ou caminho local do VTT", value=default_transcript)
    video_path = st.text_input("Vídeo da tela", placeholder=r"C:\Videos\gravacao-tela.mp4")
    professor_video_path = st.text_input(
        "Vídeo do professor (opcional)", placeholder=r"C:\Videos\professor.mp4"
    )
    ffmpeg_path = st.text_input("Caminho do ffmpeg.exe (opcional)", value="")
    target_speaker = st.text_input("Apresentador a detectar", value="RAFAEL FOSSALUSSA")
    minimum_confidence = st.slider("Confiança mínima", 0.30, 0.95, 0.50, 0.05)

    provider_label = st.selectbox("Análise", ["Regras locais", "Ollama local", "Gemini API"])
    provider = {"Regras locais": "rules", "Ollama local": "ollama", "Gemini API": "gemini"}[provider_label]
    model = ""
    ollama_url = "http://localhost:11434"
    gemini_key = ""
    if provider == "ollama":
        model = st.text_input("Modelo Ollama", value="qwen3:8b")
        ollama_url = st.text_input("URL do Ollama", value="http://localhost:11434")
    elif provider == "gemini":
        model = st.text_input("Modelo Gemini", value="gemini-2.5-flash")
        gemini_key = st.text_input(
            "GEMINI_API_KEY", value=os.getenv("GEMINI_API_KEY", ""), type="password"
        )

    analyze_clicked = st.button("1. Analisar transcrição", type="primary", width="stretch")


def resolve_transcript() -> Path:
    if transcript_upload is not None:
        suffix = Path(transcript_upload.name).suffix or ".vtt"
        temporary = Path(tempfile.gettempdir()) / f"trade-cutter-upload{suffix}"
        temporary.write_bytes(transcript_upload.getvalue())
        return temporary
    path = Path(transcript_path)
    if not path.exists():
        raise FileNotFoundError(f"VTT não encontrado: {path.resolve()}")
    return path


if analyze_clicked:
    try:
        source = resolve_transcript()
        cues = parse_vtt(source)
        config = DetectionConfig(target_speaker=target_speaker, minimum_confidence=minimum_confidence)
        operations = detect_operations(cues, config)
        if provider in {"ollama", "gemini"}:
            with st.spinner("Refinando candidatos com IA..."):
                operations = refine_operations(
                    cues,
                    operations,
                    provider=provider,
                    model=model,
                    ollama_url=ollama_url,
                    gemini_api_key=gemini_key,
                    keep_rejected=True,
                )
        st.session_state["source"] = str(source)
        st.session_state["cues"] = cues
        st.session_state["operations"] = operations
        st.session_state.pop("operations_editor", None)
        st.success(f"{len(operations)} candidatos encontrados.")
    except Exception as error:
        st.error(str(error))


operations: list[Operation] = st.session_state.get("operations", [])
cues = st.session_state.get("cues", [])
presets = get_crop_presets()

if operations:
    st.subheader("2. Revise os cortes e escolha a área")
    st.info("Edite início, fim, título, seleção e área diretamente na tabela. Use HH:MM:SS.")
    edited_df = st.data_editor(
        pd.DataFrame(operation_rows(operations)),
        hide_index=True,
        width="stretch",
        column_config={
            "Usar": st.column_config.CheckboxColumn(),
            "Área": st.column_config.SelectboxColumn(options=list(AREA_LABELS.values()), required=True),
            "Confiança": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d%%"),
        },
        disabled=["Confiança", "Fonte"],
        key="operations_editor",
    )
    operations = apply_rows(operations, edited_df, presets)
    st.session_state["operations"] = operations

    left, right = st.columns([1, 1])
    with left:
        selected_index = st.selectbox(
            "Detalhes do candidato",
            range(len(operations)),
            format_func=lambda index: (
                f"{index + 1:02d} - {operations[index].title} "
                f"({format_timecode(operations[index].entry_time)})"
            ),
        )
        operation = operations[selected_index]
        st.write(f"**Área:** {AREA_LABELS.get(operation.crop_area, AREA_LABELS['full'])}")
        st.write(f"**Resultado:** {operation.result}")
        st.write(f"**Confiança:** {operation.confidence:.0%} · **Fonte:** {operation.source}")
        for item in operation.evidence:
            st.markdown(f"- {item}")
        if cues:
            with st.expander("Ver transcrição ao redor do corte"):
                st.code(
                    transcript_between(cues, max(0, operation.cut_start - 20), operation.cut_end + 20),
                    language=None,
                )

    with right:
        if video_path and Path(video_path).exists():
            st.video(video_path, start_time=int(operation.cut_start), end_time=int(operation.cut_end))
        else:
            st.warning("Informe um caminho de vídeo da tela válido para visualizar e cortar.")

    with st.expander("Configurar e conferir as quatro áreas", expanded=False):
        render_preset_editor(presets)
        for item in operations:
            apply_crop_preset(item, presets)

        preview_time = st.number_input(
            "Instante usado na prévia (segundos)",
            min_value=0.0,
            value=float(operation.cut_start),
            step=1.0,
        )
        if st.button("Capturar/atualizar imagem das áreas"):
            try:
                if not video_path:
                    raise ValueError("Informe o vídeo da tela.")
                with st.spinner("Capturando frame..."):
                    st.session_state["crop_preview_image"] = capture_frame(
                        video_path, preview_time, ffmpeg_path=ffmpeg_path
                    )
            except Exception as error:
                st.error(str(error))
        preview_image = st.session_state.get("crop_preview_image")
        if preview_image:
            st.markdown(crop_preview_html(preview_image, presets), unsafe_allow_html=True)
            st.caption("As molduras coloridas mostram exatamente o que cada opção da tabela recortará.")
        else:
            st.caption("Capture uma imagem para conferir e ajustar as áreas sobre o vídeo real.")

    st.session_state["operations"] = operations
    output_dir = st.text_input("Pasta de saída", value=str(Path("output").resolve()))
    output_format_label = st.radio(
        "Formato de saída",
        ["Corte original", "Vertical 1080x1920 com professor"],
        horizontal=True,
    )
    output_format = "vertical" if output_format_label.startswith("Vertical") else "original"

    professor_sync_offset = 0.0
    audio_source = "professor"
    if output_format == "vertical":
        settings_left, settings_right = st.columns(2)
        professor_sync_offset = settings_left.number_input(
            "Ajuste do professor em segundos",
            value=0.0,
            step=0.1,
            help="Use apenas se perceber diferença de sincronização. Positivo avança o vídeo do professor.",
        )
        audio_label = settings_right.radio(
            "Áudio da saída", ["Vídeo do professor", "Vídeo da tela"], horizontal=True
        )
        audio_source = "professor" if audio_label == "Vídeo do professor" else "screen"
        st.caption("Professor na metade superior e gráfico selecionado na metade inferior.")
        if not professor_video_path or not Path(professor_video_path).exists():
            st.warning("Informe um vídeo do professor válido na barra lateral para gerar a saída vertical.")

        if st.button("Gerar prévia vertical de 10 segundos"):
            try:
                find_ffmpeg(ffmpeg_path)
                preview_operation = replace(
                    operation,
                    cut_end=min(operation.cut_end, operation.cut_start + 10.0),
                )
                preview_target = Path(tempfile.gettempdir()) / "trade-cutter-vertical-preview.mp4"
                with st.spinner("Gerando prévia vertical..."):
                    cut_video(
                        video_path,
                        preview_operation,
                        preview_target,
                        mode="exact",
                        ffmpeg_path=ffmpeg_path,
                        output_format="vertical",
                        professor_video_path=professor_video_path,
                        professor_sync_offset=professor_sync_offset,
                        audio_source=audio_source,
                    )
                st.session_state["vertical_preview_path"] = str(preview_target)
            except Exception as error:
                st.error(str(error))
        vertical_preview_path = st.session_state.get("vertical_preview_path")
        if vertical_preview_path and Path(vertical_preview_path).exists():
            st.video(vertical_preview_path)

    cut_mode_label = st.radio(
        "Modo de corte", ["Exato (recodifica)", "Rápido (sem recodificar)"], horizontal=True
    )
    cut_mode = "exact" if cut_mode_label.startswith("Exato") else "fast"
    if output_format == "vertical" or any(
        item.selected and item.crop_area != "full" for item in operations
    ):
        st.caption("Recortes de área e vídeos verticais são recodificados mesmo com o modo rápido selecionado.")

    col_json, col_report, col_cut = st.columns(3)
    with col_json:
        if st.button("Salvar cuts.json", width="stretch"):
            target = save_operations(
                Path(output_dir) / "cuts.json", operations, st.session_state.get("source", "")
            )
            st.success(f"Salvo em {target}")
    with col_report:
        if st.button("Gerar relatório HTML", width="stretch"):
            target = create_html_report(
                Path(output_dir) / "report.html", operations, video_path=video_path
            )
            st.success(f"Salvo em {target}")
    with col_cut:
        if st.button("3. Gerar cortes", type="primary", width="stretch"):
            try:
                if not video_path:
                    raise ValueError("Informe o caminho do vídeo da tela.")
                if output_format == "vertical" and not professor_video_path:
                    raise ValueError("Informe o caminho do vídeo do professor.")
                find_ffmpeg(ffmpeg_path)
                progress = st.progress(0, text="Preparando...")

                def update(index, total, op, target):
                    progress.progress(index / max(total, 1), text=f"{index}/{total}: {op.title}")

                targets = cut_selected(
                    video_path,
                    operations,
                    Path(output_dir) / "clips",
                    mode=cut_mode,
                    ffmpeg_path=ffmpeg_path,
                    progress=update,
                    output_format=output_format,
                    professor_video_path=professor_video_path,
                    professor_sync_offset=professor_sync_offset,
                    audio_source=audio_source,
                )
                save_operations(
                    Path(output_dir) / "cuts.json", operations, st.session_state.get("source", "")
                )
                create_html_report(
                    Path(output_dir) / "report.html", operations, video_path=video_path
                )
                st.success(f"{len(targets)} clipes gerados em {Path(output_dir) / 'clips'}")
            except Exception as error:
                st.error(str(error))
else:
    st.markdown(
        """
### Como testar

1. Mantenha a transcrição de exemplo ou escolha outro `.vtt`.
2. Clique em **Analisar transcrição**.
3. Revise os horários e escolha a área de cada corte.
4. Informe o vídeo da tela e, para saída vertical, o vídeo do professor.
5. Confira as áreas e clique em **Gerar cortes**.

O modo **Regras locais** não usa internet nem API. O modo **Ollama** mantém toda a análise no computador. O modo **Gemini** envia somente os trechos de texto candidatos.
"""
    )
