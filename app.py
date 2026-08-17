from __future__ import annotations

import base64
import hashlib
import os
import tempfile
from dataclasses import replace
from pathlib import Path

import pandas as pd
import streamlit as st

from trade_cutter.ai import refine_operations
from trade_cutter.detector import DetectionConfig, detect_operations
from trade_cutter.export import create_html_report, load_operations, save_operations
from trade_cutter.ffmpeg import (
    capture_frame,
    capture_scene_frame,
    create_preview_clip,
    default_ffmpeg_path,
    export_final_video,
    find_ffmpeg,
    render_scene_video,
)
from trade_cutter.models import (
    GRAPH_ALIGNMENT_LABELS,
    OUTPUT_ORIENTATION_LABELS,
    SCENE_AUDIO_LABELS,
    SCENE_LAYOUT_LABELS,
    SCENE_SPEED_OPTIONS,
    Operation,
    Scene,
)
from trade_cutter.project import (
    copy_source_transcript,
    create_project_directory,
    load_project_manifest,
    project_video_path,
    resolve_project_file,
    write_export_error,
    write_project_manifest,
)
from trade_cutter.library import load_user_config, save_user_config, scan_recordings
from trade_cutter.rules import (
    RuleDefinition,
    compile_rules,
    default_rules,
    load_rules,
    rules_from_records,
    save_rules,
)
from trade_cutter.scene_suggestions import (
    DEFAULT_SCENE_KEYWORDS,
    build_scene_suggestion_plan,
    materialize_suggestions,
    suggest_scenes,
)
from trade_cutter.sidecars import sidecar_paths
from trade_cutter.timecode import (
    clock_time_to_video_time,
    format_timecode,
    normalize_timecode,
    parse_clock_time,
    parse_timecode,
)
from trade_cutter.vtt import parse_vtt, search_cues, transcript_between


st.set_page_config(page_title="Trade Video Cutter", page_icon="🎬", layout="wide")
st.title("🎬 Trade Video Cutter")
st.caption("Analisa a transcrição, monta cenas com professor e gráfico e exporta um único vídeo com FFmpeg.")

DEFAULT_RECORDINGS_FOLDER = r"C:\Users\allan\OneDrive\Vídeos\Aulas"
RULES_PATH = Path(os.getenv("TRADE_CUTTER_RULES_PATH", "user_rules.json"))

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
    "profit_dollar": {"x": 0.750, "y": 0.000, "width": 0.250, "height": 1.000},
}
PREVIEW_COLORS = {
    "flex_index": "#22c55e",
    "flex_dollar": "#06b6d4",
    "profit_index": "#f59e0b",
    "profit_dollar": "#ef4444",
}
RULE_CATEGORY_LABELS = {
    "setup": "Preparação",
    "entry": "Entrada",
    "outcome": "Resultado",
    "negation": "Negação",
}
LABEL_TO_RULE_CATEGORY = {label: key for key, label in RULE_CATEGORY_LABELS.items()}
RULE_MODE_LABELS = {"literal": "Texto simples", "regex": "Regex"}
LABEL_TO_RULE_MODE = {label: key for key, label in RULE_MODE_LABELS.items()}
SUBTITLE_STYLE_LABELS = {
    "normal": "Normal",
    "highlight": "Highlight dourado",
}
SOURCE_PREVIEW_MAX_SECONDS = 120.0


def _scene_widget_key(operation: Operation, scene: Scene, field: str) -> str:
    return f"scene_{operation.id}_{scene.id}_{field}"


def _set_scene_widget_values(operation: Operation, scene: Scene) -> None:
    values = {
        "professor_zoom": int(round(scene.professor_zoom * 100)),
        "professor_x": int(round(scene.professor_x)),
        "professor_y": int(round(scene.professor_y)),
        "graph_zoom": int(round(scene.graph_zoom * 100)),
        "graph_x": int(round(scene.graph_x)),
        "graph_y": int(round(scene.graph_y)),
        "graph_alignment": scene.graph_alignment,
        "playback_speed": float(scene.playback_speed),
        "audio_mode": scene.audio_mode,
        "subtitles_enabled": bool(scene.subtitles_enabled),
        "skip": bool(scene.skip),
    }
    for field, value in values.items():
        st.session_state[_scene_widget_key(operation, scene, field)] = value


def _reset_graph_horizontal_adjustment(operation: Operation, scene: Scene) -> None:
    """Start a newly selected graph anchor without a stale fine adjustment."""
    scene.graph_x = 0.0
    st.session_state[_scene_widget_key(operation, scene, "graph_x")] = 0


def _normalize_timecode_widget(key: str) -> None:
    """Canonicalize a time field on blur/Enter without surfacing parser errors."""
    try:
        normalized = normalize_timecode(st.session_state.get(key, ""))
        if normalized:
            st.session_state[key] = normalized
    except ValueError:
        pass


def _invalidate_clock_sync() -> None:
    st.session_state.pop("clock_sync", None)
    for key in list(st.session_state):
        if key.startswith("source_frame_preview_annotated_clock_"):
            st.session_state.pop(key, None)


def _clock_sync_video_time_changed(key: str) -> None:
    _normalize_timecode_widget(key)
    _invalidate_clock_sync()


def _clock_sync_clock_time_changed() -> None:
    _invalidate_clock_sync()


def _scene_signature(
    operation: Operation,
    scene: Scene,
    orientation: str,
    professor_sync_offset: float,
    audio_source: str,
    subtitles_enabled: bool,
    subtitle_speaker: str,
    subtitle_style: str,
) -> tuple:
    return (
        operation.id,
        scene.id,
        scene.start,
        scene.end,
        scene.layout,
        scene.professor_zoom,
        scene.professor_x,
        scene.professor_y,
        scene.graph_zoom,
        scene.graph_x,
        scene.graph_y,
        scene.graph_alignment,
        scene.playback_speed,
        scene.audio_mode,
        scene.subtitles_enabled,
        scene.skip,
        operation.crop_area,
        operation.crop_x,
        operation.crop_y,
        operation.crop_width,
        operation.crop_height,
        orientation,
        professor_sync_offset,
        audio_source,
        subtitles_enabled,
        subtitle_speaker,
        subtitle_style,
    )


def _render_scene_suggestion_panel(
    operation: Operation,
    *,
    cues,
    target_speaker: str,
) -> None:
    state_key = f"scene_suggestion_plan_{operation.id}"
    flash_key = f"scene_suggestion_flash_{operation.id}"
    if st.session_state.pop(flash_key, False):
        st.success("A proposta foi aplicada. Todas as cenas continuam editáveis.")

    with st.expander("Sugerir cenas pela transcrição", expanded=False):
        st.caption(
            "A análise só roda quando você clicar no botão e fica limitada ao início e fim "
            "deste corte. Nada é alterado até você revisar e aplicar a proposta."
        )
        first, second, third, fourth, fifth = st.columns(5)
        before = first.number_input(
            "Contexto antes (s)", 0.0, 30.0, 3.0, 0.5,
            key=f"suggestion_before_{operation.id}",
        )
        after = second.number_input(
            "Contexto depois (s)", 0.0, 30.0, 3.0, 0.5,
            key=f"suggestion_after_{operation.id}",
        )
        target_duration = third.number_input(
            "Alvo acelerado (s)", 1.0, 30.0, 5.0, 0.5,
            key=f"suggestion_target_{operation.id}",
        )
        minimum_gap = fourth.number_input(
            "Intervalo mínimo (s)", 1.0, 120.0, 12.0, 1.0,
            key=f"suggestion_min_gap_{operation.id}",
        )
        max_speed = fifth.number_input(
            "Velocidade máxima", 2.0, 100.0, 100.0, 1.0,
            key=f"suggestion_max_speed_v2_{operation.id}",
        )

        if st.button(
            "Analisar somente este corte",
            key=f"analyze_scene_suggestions_{operation.id}",
            type="primary",
        ):
            if not cues:
                st.warning("Carregue uma transcrição VTT antes de analisar as falas.")
            else:
                try:
                    plan = suggest_scenes(
                        operation,
                        cues,
                        target_speaker=target_speaker,
                        context_before=before,
                        context_after=after,
                        target_fast_duration=target_duration,
                        minimum_gap=minimum_gap,
                        max_speed=max_speed,
                    )
                    st.session_state[state_key] = {
                        "bounds": (operation.cut_start, operation.cut_end),
                        "analysis": plan,
                        "target_duration": float(target_duration),
                        "minimum_gap": float(minimum_gap),
                        "max_speed": float(max_speed),
                    }
                    for key in list(st.session_state):
                        if key.startswith(f"keep_keyword_occurrence_{operation.id}_"):
                            st.session_state.pop(key, None)
                except ValueError as error:
                    st.error(str(error))

        proposal = st.session_state.get(state_key)
        if proposal and proposal.get("bounds") != (operation.cut_start, operation.cut_end):
            st.session_state.pop(state_key, None)
            proposal = None
            st.info("Os limites do corte mudaram. Gere uma nova proposta para estes horários.")
        if not proposal:
            return

        analysis = proposal["analysis"]
        st.caption(
            "Palavras procuradas: "
            + ", ".join(DEFAULT_SCENE_KEYWORDS)
            + ". Variações de plural, “por cento” e % também são reconhecidas."
        )
        selected_occurrence_ids: set[str] = set()
        if analysis.occurrences:
            st.markdown("**Escolha as frases que devem permanecer em 1×:**")
            for occurrence in analysis.occurrences:
                keep_key = (
                    f"keep_keyword_occurrence_{operation.id}_{occurrence.id}"
                )
                if st.checkbox(
                    (
                        f"{format_timecode(occurrence.cue_start)} · "
                        f"{', '.join(occurrence.keywords)} · {occurrence.text}"
                    ),
                    value=True,
                    key=keep_key,
                    help=(
                        "Desmarcada, esta fala não cria uma cena em 1× e continua "
                        "no trecho acelerado ao redor; nenhum conteúdo é removido."
                    ),
                ):
                    selected_occurrence_ids.add(occurrence.id)
        else:
            st.warning(
                f'Nenhuma das palavras foi encontrada nas falas de “{target_speaker}”. '
                "Revise com atenção antes de aplicar."
            )

        plan = build_scene_suggestion_plan(
            operation,
            analysis.occurrences,
            selected_occurrence_ids=selected_occurrence_ids,
            target_fast_duration=proposal["target_duration"],
            minimum_gap=proposal["minimum_gap"],
            max_speed=proposal["max_speed"],
        )
        st.markdown(
            f"**Proposta atual:** {len(plan.scenes)} blocos · "
            f"{plan.selected_occurrence_count}/{plan.relevant_cue_count} frases em 1× · "
            f"{plan.matched_keyword_count} palavras-chave selecionadas"
        )
        kind_labels = {
            "normal": "Normal",
            "accelerated": "Acelerada",
            "jump": "Salto sugerido",
        }
        rows = []
        for index, suggestion in enumerate(plan.scenes):
            final_duration = (
                "depende da aprovação"
                if suggestion.kind == "jump"
                else format_timecode(suggestion.output_duration, milliseconds=True)
            )
            rows.append(
                {
                    "#": index + 1,
                    "Início": format_timecode(suggestion.start),
                    "Fim": format_timecode(suggestion.end),
                    "Tipo": kind_labels[suggestion.kind],
                    "Velocidade": (
                        f"{suggestion.speed:.2f}× necessária"
                        if suggestion.kind == "jump"
                        else f"{suggestion.speed:.2f}×"
                    ),
                    "Duração final": final_duration,
                    "Motivo": suggestion.reason,
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        approved_jumps: set[int] = set()
        for index, suggestion in enumerate(plan.scenes):
            if suggestion.kind != "jump":
                continue
            if st.checkbox(
                (
                    f"Aprovar remoção do bloco {index + 1} · "
                    f"{format_timecode(suggestion.start)}–{format_timecode(suggestion.end)}"
                ),
                value=False,
                key=(
                    f"approve_scene_jump_{operation.id}_"
                    f"{int(suggestion.start * 1000)}_{int(suggestion.end * 1000)}"
                ),
                help=(
                    f"Sem aprovação, este intervalo será mantido em "
                    f"{proposal['max_speed']:g}×, sem áudio e sem legendas."
                ),
            ):
                approved_jumps.add(index)

        apply_column, cancel_column = st.columns(2)
        if apply_column.button(
            "Aplicar proposta às cenas",
            key=f"apply_scene_suggestions_{operation.id}",
            width="stretch",
        ):
            materialize_suggestions(
                operation,
                plan.scenes,
                approved_jumps=approved_jumps,
                max_speed=proposal["max_speed"],
            )
            operation.crop_area = "profit_index"
            apply_crop_preset(operation, get_crop_presets())
            st.session_state.pop(state_key, None)
            st.session_state[f"selected_scene_{operation.id}"] = 0
            st.session_state["refresh_operations_editor"] = True
            st.session_state.pop("scene_frame_preview", None)
            st.session_state.pop("scene_video_preview", None)
            st.session_state[flash_key] = True
            st.rerun()
        if cancel_column.button(
            "Descartar proposta",
            key=f"discard_scene_suggestions_{operation.id}",
            width="stretch",
        ):
            st.session_state.pop(state_key, None)
            st.rerun()


def render_scene_editor(
    operation: Operation,
    *,
    video_path: str,
    professor_video_path: str,
    orientation: str,
    professor_sync_offset: float,
    audio_source: str,
    cues,
    subtitles_enabled: bool,
    subtitle_speaker: str,
    subtitle_style: str,
    target_speaker: str,
    ffmpeg_path: str,
) -> None:
    st.markdown("#### Cenas deste trecho")
    st.caption(
        "O início e o fim abaixo são os limites exatos exportados. O contexto "
        "mostrado nas prévias não é incluído no vídeo final."
    )

    start_key = f"scene_cut_start_{operation.id}"
    end_key = f"scene_cut_end_{operation.id}"
    bounds_key = f"scene_cut_bounds_{operation.id}"
    current_bounds = (operation.cut_start, operation.cut_end)
    if st.session_state.get(bounds_key) != current_bounds:
        st.session_state[start_key] = format_timecode(operation.cut_start)
        st.session_state[end_key] = format_timecode(operation.cut_end)
        st.session_state[bounds_key] = current_bounds

    start_column, end_column = st.columns(2)
    start_value = start_column.text_input(
        "Início exato do vídeo",
        key=start_key,
        on_change=_normalize_timecode_widget,
        args=(start_key,),
        help="Este é o primeiro segundo exportado, sem contexto anterior.",
    )
    end_value = end_column.text_input(
        "Fim exato do vídeo",
        key=end_key,
        on_change=_normalize_timecode_widget,
        args=(end_key,),
        help="Este é o último limite do trecho exportado.",
    )
    try:
        parsed_start = parse_timecode(start_value)
        parsed_end = parse_timecode(end_value)
        if parsed_start is None or parsed_end is None:
            raise ValueError("Preencha o início e o fim do vídeo.")
        operation.set_cut_bounds(parsed_start, parsed_end)
        st.session_state[bounds_key] = (operation.cut_start, operation.cut_end)
    except ValueError as error:
        st.warning(str(error))

    scenes = sorted(operation.ensure_scenes(), key=lambda item: (item.start, item.end))
    operation.scenes = scenes
    _render_scene_suggestion_panel(
        operation,
        cues=cues,
        target_speaker=target_speaker,
    )
    st.caption(
        "Dividir uma cena troca apenas a composição. Use “Começar vídeo aqui” "
        "quando quiser descartar tudo o que vem antes do horário informado."
    )

    timeline_rows = [
        {
            "#": index + 1,
            "Início na aula": format_timecode(scene.start),
            "Fim na aula": format_timecode(scene.end),
            "Duração original": format_timecode(scene.end - scene.start),
            "Duração final": format_timecode(scene.output_duration, milliseconds=True),
            "Estado": "Salto (não exporta)" if scene.skip else "Incluída",
            "Velocidade": "—" if scene.skip else f"{scene.playback_speed:g}×",
            "Áudio": SCENE_AUDIO_LABELS.get(scene.audio_mode, scene.audio_mode),
            "Legendas": "Sim" if scene.subtitles_enabled else "Não",
            "Composição": SCENE_LAYOUT_LABELS[scene.layout],
        }
        for index, scene in enumerate(scenes)
    ]
    st.dataframe(pd.DataFrame(timeline_rows), hide_index=True, width="stretch")

    split_default = scenes[-1].start + (scenes[-1].end - scenes[-1].start) / 2
    split_key = f"split_scene_at_{operation.id}"
    if split_key not in st.session_state:
        st.session_state[split_key] = format_timecode(split_default)
    split_left, split_right, start_here_column = st.columns([3, 1, 1])
    split_value = split_left.text_input(
        "Trocar composição em",
        key=split_key,
        on_change=_normalize_timecode_widget,
        args=(split_key,),
        help="Muda a composição nesse ponto, mas não altera o início do vídeo.",
    )
    if split_right.button("Dividir cena", key=f"split_scene_{operation.id}", width="stretch"):
        try:
            split_at = parse_timecode(split_value)
            target_index = next(
                (
                    index
                    for index, item in enumerate(scenes)
                    if split_at is not None and item.start < split_at < item.end
                ),
                None,
            )
            if target_index is None or split_at is None:
                raise ValueError("O horário precisa ficar dentro de uma das cenas existentes.")
            current = scenes[target_index]
            new_scene = replace(
                current,
                id=f"scene-{int(split_at * 1000)}-{len(scenes) + 1}",
                start=split_at,
            )
            current.end = split_at
            scenes.insert(target_index + 1, new_scene)
            operation.scenes = scenes
            st.session_state[f"selected_scene_{operation.id}"] = target_index + 1
            st.rerun()
        except ValueError as error:
            st.warning(str(error))

    if start_here_column.button(
        "Começar vídeo aqui",
        key=f"start_video_here_{operation.id}",
        width="stretch",
    ):
        try:
            start_at = parse_timecode(split_value)
            if start_at is None or not operation.cut_start <= start_at < operation.cut_end:
                raise ValueError("O novo início precisa ficar dentro deste trecho.")
            operation.set_cut_bounds(start_at, operation.cut_end)
            st.session_state[f"selected_scene_{operation.id}"] = 0
            st.session_state.pop("scene_frame_preview", None)
            st.session_state.pop("scene_video_preview", None)
            st.rerun()
        except ValueError as error:
            st.warning(str(error))

    selected_scene_key = f"selected_scene_{operation.id}"
    if st.session_state.get(selected_scene_key, 0) not in range(len(scenes)):
        st.session_state[selected_scene_key] = 0
    selected_index = st.selectbox(
        "Cena para editar",
        range(len(scenes)),
        format_func=lambda index: (
            f"Cena {index + 1} · {format_timecode(scenes[index].start)}–"
            f"{format_timecode(scenes[index].end)} · {SCENE_LAYOUT_LABELS[scenes[index].layout]}"
            f"{' · SALTO' if scenes[index].skip else ''}"
        ),
        key=selected_scene_key,
    )
    scene = scenes[selected_index]
    layout_label = st.selectbox(
        "Composição",
        list(SCENE_LAYOUT_LABELS.values()),
        index=list(SCENE_LAYOUT_LABELS).index(scene.layout),
        key=f"scene_layout_{operation.id}_{scene.id}",
    )
    scene.layout = next(key for key, label in SCENE_LAYOUT_LABELS.items() if label == layout_label)

    if st.button(
        "Aplicar preset · Gráfico acelerado",
        key=f"preset_fast_graph_{operation.id}_{scene.id}",
        help="Define 10×, silêncio e legendas desligadas sem alterar a composição.",
    ):
        scene.playback_speed = 10.0
        scene.audio_mode = "mute"
        scene.subtitles_enabled = False
        _set_scene_widget_values(operation, scene)
        st.rerun()

    settings_speed, settings_audio, settings_subtitles, settings_skip = st.columns(4)
    scene.playback_speed = round(float(scene.playback_speed), 2)
    speed_options = sorted(set((*SCENE_SPEED_OPTIONS, scene.playback_speed)))
    scene.playback_speed = float(settings_speed.selectbox(
        "Velocidade da cena",
        speed_options,
        index=speed_options.index(scene.playback_speed),
        format_func=lambda value: f"{value:g}×",
        key=_scene_widget_key(operation, scene, "playback_speed"),
    ))
    if scene.audio_mode not in SCENE_AUDIO_LABELS:
        scene.audio_mode = "project"
    scene.audio_mode = settings_audio.selectbox(
        "Áudio da cena",
        list(SCENE_AUDIO_LABELS),
        index=list(SCENE_AUDIO_LABELS).index(scene.audio_mode),
        format_func=lambda value: SCENE_AUDIO_LABELS[value],
        key=_scene_widget_key(operation, scene, "audio_mode"),
    )
    scene.subtitles_enabled = settings_subtitles.checkbox(
        "Legendas nesta cena",
        value=bool(scene.subtitles_enabled),
        key=_scene_widget_key(operation, scene, "subtitles_enabled"),
        disabled=not subtitles_enabled,
        help="A opção global de legendas também precisa estar ativada.",
    )
    scene.skip = settings_skip.checkbox(
        "Remover do vídeo (salto)",
        value=bool(scene.skip),
        key=_scene_widget_key(operation, scene, "skip"),
        help="O intervalo permanece no projeto, mas não será exportado.",
    )
    st.caption(
        f"Duração: {format_timecode(scene.end - scene.start, milliseconds=True)} original "
        f"→ {format_timecode(scene.output_duration, milliseconds=True)} no vídeo final."
    )
    if scene.playback_speed >= 5 and scene.audio_mode != "mute":
        st.warning("Em 5× ou mais, o áudio costuma ficar incompreensível. Considere usar Sem áudio.")
    if not subtitles_enabled:
        st.caption("As legendas globais estão desligadas; a preferência desta cena foi preservada.")

    shows_professor = scene.layout != "graph_full"
    shows_graph = scene.layout != "professor_full"
    professor_column, graph_column = st.columns(2)
    with professor_column:
        st.markdown("**Professor**")
        if shows_professor:
            scene.professor_zoom = st.slider(
                "Zoom do professor", 100, 300,
                int(round(scene.professor_zoom * 100)), 5,
                format="%d%%",
                key=_scene_widget_key(operation, scene, "professor_zoom"),
            ) / 100.0
            scene.professor_x = float(st.slider(
                "Professor: horizontal", -100, 100, int(scene.professor_x), 5,
                key=_scene_widget_key(operation, scene, "professor_x"),
            ))
            scene.professor_y = float(st.slider(
                "Professor: vertical", -100, 100, int(scene.professor_y), 5,
                key=_scene_widget_key(operation, scene, "professor_y"),
            ))
        else:
            st.caption("O professor não aparece nesta cena.")
    with graph_column:
        st.markdown("**Gráfico**")
        if shows_graph:
            if scene.graph_alignment not in GRAPH_ALIGNMENT_LABELS:
                scene.graph_alignment = "center"
            scene.graph_alignment = st.radio(
                "Alinhamento horizontal do gráfico",
                list(GRAPH_ALIGNMENT_LABELS),
                index=list(GRAPH_ALIGNMENT_LABELS).index(scene.graph_alignment),
                format_func=lambda value: GRAPH_ALIGNMENT_LABELS[value],
                horizontal=True,
                key=_scene_widget_key(operation, scene, "graph_alignment"),
                on_change=_reset_graph_horizontal_adjustment,
                args=(operation, scene),
                help=(
                    "Direita mantém visível a borda direita da área selecionada, "
                    "onde ficam os dados mais recentes do gráfico."
                ),
            )
            scene.graph_zoom = st.slider(
                "Zoom do gráfico", 100, 300,
                int(round(scene.graph_zoom * 100)), 5,
                format="%d%%",
                key=_scene_widget_key(operation, scene, "graph_zoom"),
            ) / 100.0
            scene.graph_x = float(st.slider(
                "Gráfico: ajuste horizontal fino", -100, 100, int(scene.graph_x), 5,
                key=_scene_widget_key(operation, scene, "graph_x"),
                help="Refina o enquadramento a partir do alinhamento escolhido acima.",
            ))
            scene.graph_y = float(st.slider(
                "Gráfico: vertical", -100, 100, int(scene.graph_y), 5,
                key=_scene_widget_key(operation, scene, "graph_y"),
            ))
        else:
            st.caption("O gráfico não aparece nesta cena.")

    reset_column, copy_column, apply_column, remove_column = st.columns(4)
    if reset_column.button("Restaurar", key=f"reset_scene_{operation.id}_{scene.id}"):
        scene.professor_zoom = scene.graph_zoom = 1.0
        scene.professor_x = scene.professor_y = 0.0
        scene.graph_x = scene.graph_y = 0.0
        scene.graph_alignment = "center"
        scene.playback_speed = 1.0
        scene.audio_mode = "project"
        scene.subtitles_enabled = True
        scene.skip = False
        _set_scene_widget_values(operation, scene)
        st.rerun()
    if copy_column.button(
        "Copiar anterior",
        key=f"copy_scene_{operation.id}_{scene.id}",
        disabled=selected_index == 0,
    ):
        previous = scenes[selected_index - 1]
        scene.professor_zoom = previous.professor_zoom
        scene.professor_x = previous.professor_x
        scene.professor_y = previous.professor_y
        scene.graph_zoom = previous.graph_zoom
        scene.graph_x = previous.graph_x
        scene.graph_y = previous.graph_y
        scene.graph_alignment = previous.graph_alignment
        scene.playback_speed = previous.playback_speed
        scene.audio_mode = previous.audio_mode
        scene.subtitles_enabled = previous.subtitles_enabled
        _set_scene_widget_values(operation, scene)
        st.rerun()
    if apply_column.button("Aplicar às iguais", key=f"apply_scene_{operation.id}_{scene.id}"):
        for other in scenes:
            if other.layout == scene.layout and other.id != scene.id:
                other.professor_zoom = scene.professor_zoom
                other.professor_x = scene.professor_x
                other.professor_y = scene.professor_y
                other.graph_zoom = scene.graph_zoom
                other.graph_x = scene.graph_x
                other.graph_y = scene.graph_y
                other.graph_alignment = scene.graph_alignment
                other.playback_speed = scene.playback_speed
                other.audio_mode = scene.audio_mode
                other.subtitles_enabled = scene.subtitles_enabled
                _set_scene_widget_values(operation, other)
        st.success("Configuração aplicada às cenas com a mesma composição.")
    if remove_column.button(
        "Remover cena",
        key=f"remove_scene_{operation.id}_{scene.id}",
        disabled=len(scenes) == 1,
    ):
        if selected_index > 0:
            scenes[selected_index - 1].end = scene.end
        else:
            scenes[1].start = scene.start
        scenes.pop(selected_index)
        operation.scenes = scenes
        st.session_state[f"selected_scene_{operation.id}"] = max(0, selected_index - 1)
        st.rerun()

    signature = _scene_signature(
        operation,
        scene,
        orientation,
        professor_sync_offset,
        audio_source,
        subtitles_enabled,
        subtitle_speaker,
        subtitle_style,
    )
    if st.button(
        "Atualizar prévia da cena",
        type="primary",
        key=f"preview_scene_{operation.id}_{scene.id}",
    ):
        try:
            with st.spinner("Montando a cena..."):
                image = capture_scene_frame(
                    video_path,
                    professor_video_path,
                    operation,
                    scene,
                    orientation=orientation,
                    ffmpeg_path=ffmpeg_path,
                    professor_sync_offset=professor_sync_offset,
                )
            st.session_state["scene_frame_preview"] = {
                "image": image,
                "signature": signature,
            }
        except Exception as error:
            st.error(str(error))
    preview = st.session_state.get("scene_frame_preview")
    if isinstance(preview, dict) and preview.get("signature") == signature:
        preview_column, _ = st.columns([1, 2] if orientation == "vertical" else [2, 1])
        preview_column.image(preview["image"], caption="Prévia da cena", width="stretch")
    elif preview:
        st.info("A prévia está desatualizada. Atualize para conferir o enquadramento atual.")

    if st.button(
        "Gerar prévia em vídeo desta cena (até 10s)",
        key=f"video_preview_scene_{operation.id}_{scene.id}",
    ):
        try:
            preview_scene = replace(scene, end=min(scene.end, scene.start + 10.0))
            digest = hashlib.sha256(repr(signature).encode("utf-8")).hexdigest()[:16]
            preview_target = (
                Path(tempfile.gettempdir())
                / "trade-video-cutter"
                / "scene-previews"
                / f"{digest}.mp4"
            )
            with st.spinner("Gerando prévia em vídeo..."):
                render_scene_video(
                    video_path,
                    professor_video_path,
                    operation,
                    preview_scene,
                    preview_target,
                    orientation=orientation,
                    ffmpeg_path=ffmpeg_path,
                    professor_sync_offset=professor_sync_offset,
                    audio_source=audio_source,
                    cues=cues if subtitles_enabled else None,
                    subtitle_speaker=subtitle_speaker,
                    subtitle_style=subtitle_style,
                )
            st.session_state["scene_video_preview"] = {
                "path": str(preview_target),
                "signature": signature,
            }
        except Exception as error:
            st.error(str(error))
    video_preview = st.session_state.get("scene_video_preview")
    if (
        isinstance(video_preview, dict)
        and video_preview.get("signature") == signature
        and Path(str(video_preview.get("path", ""))).exists()
    ):
        st.video(video_preview["path"])


def get_crop_presets() -> dict[str, dict[str, float]]:
    if "crop_presets" not in st.session_state:
        st.session_state["crop_presets"] = {
            key: dict(value) for key, value in DEFAULT_CROP_PRESETS.items()
        }
    else:
        # Migra somente o antigo valor padrão; calibrações personalizadas são preservadas.
        profit_dollar = st.session_state["crop_presets"].get("profit_dollar", {})
        is_legacy_default = (
            abs(profit_dollar.get("x", -1.0) - 0.750) < 0.0001
            and abs(profit_dollar.get("y", -1.0) - 0.000) < 0.0001
            and abs(profit_dollar.get("width", -1.0) - 0.190) < 0.0001
            and abs(profit_dollar.get("height", -1.0) - 1.000) < 0.0001
        )
        if is_legacy_default:
            profit_dollar["width"] = 0.250
            if "crop_profit_dollar_width" in st.session_state:
                st.session_state["crop_profit_dollar_width"] = 25.0
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
            "Ordem": operation.sequence_order,
            "Operação": operation.title,
            "Área": AREA_LABELS.get(operation.crop_area, AREA_LABELS["full"]),
            "Cenas": len(operation.ensure_scenes()),
            "Entrada": format_timecode(operation.entry_time),
            "Início": format_timecode(operation.cut_start),
            "Fim": format_timecode(operation.cut_end),
            "Confiança": round(operation.confidence * 100),
            "Resultado": operation.result,
            "Fonte": operation.source,
        }
        for operation in operations
    ]


def rule_rows(rules: list[RuleDefinition]) -> list[dict]:
    return [
        {
            "Ativa": rule.enabled,
            "Categoria": RULE_CATEGORY_LABELS[rule.category],
            "Tipo": RULE_MODE_LABELS[rule.mode],
            "Expressão": rule.expression,
            "Resultado": rule.label,
            "Peso": rule.strength,
            "ID": rule.id,
        }
        for rule in rules
    ]


def apply_rule_rows(rows) -> list[RuleDefinition]:
    records = rows.to_dict("records")
    for record in records:
        record["Categoria"] = LABEL_TO_RULE_CATEGORY.get(
            str(record.get("Categoria", "")), str(record.get("Categoria", "")).lower()
        )
        record["Tipo"] = LABEL_TO_RULE_MODE.get(
            str(record.get("Tipo", "")), str(record.get("Tipo", "")).lower()
        )
    return rules_from_records(records)


def add_manual_operation(
    *,
    title: str,
    start_value: str,
    end_value: str,
    entry_time: float,
    area_label: str,
    evidence: list[str],
    identity: str,
    presets: dict[str, dict[str, float]],
) -> Operation:
    cut_start = parse_timecode(start_value)
    cut_end = parse_timecode(end_value)
    if not title.strip():
        raise ValueError("Informe um título para o corte manual.")
    if cut_start is None or cut_end is None:
        raise ValueError("Informe início e fim válidos.")
    if cut_end <= cut_start:
        raise ValueError("O fim precisa ser posterior ao início.")

    crop_area = LABEL_TO_AREA[area_label]
    asset = ""
    if crop_area.endswith("index"):
        asset = "índice"
    elif crop_area.endswith("dollar"):
        asset = "dólar"
    digest_source = (
        f"{st.session_state.get('source', '')}-{identity}-"
        f"{cut_start:.3f}-{cut_end:.3f}-{title.strip()}"
    )
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:10]
    operation = Operation(
        id=f"manual-{digest}",
        title=title.strip(),
        asset=asset,
        direction="",
        setup_start=None,
        entry_time=entry_time,
        operation_end=cut_end,
        cut_start=cut_start,
        cut_end=cut_end,
        result="corte manual",
        confidence=1.0,
        evidence=evidence,
        event_times=[entry_time],
        selected=True,
        source="manual",
        crop_area=crop_area,
    )
    apply_crop_preset(operation, presets)
    current_operations = list(st.session_state.get("operations", []))
    current_operations.append(operation)
    st.session_state["operations"] = sorted(
        current_operations,
        key=lambda item: item.entry_time,
    )
    st.session_state.pop("operations_editor", None)
    return operation


def render_source_video_preview(
    video_path: str,
    start_time: float,
    end_time: float,
    *,
    widget_key: str,
    ffmpeg_path: str = "",
) -> None:
    """Render a short cached proxy instead of loading the full source in Streamlit."""
    if not video_path or not Path(video_path).exists():
        st.warning("Carregue um vídeo da tela válido para visualizar este ponto.")
        return

    start = max(0.0, float(start_time))
    requested_end = max(start + 0.2, float(end_time))
    preview_end = min(requested_end, start + SOURCE_PREVIEW_MAX_SECONDS)
    source = Path(video_path)
    source_stat = source.stat()
    signature_source = "|".join(
        (
            "streamlit-preview-v2",
            str(source.resolve()),
            str(source_stat.st_size),
            str(source_stat.st_mtime_ns),
            f"{start:.3f}",
            f"{preview_end:.3f}",
        )
    )
    signature = hashlib.sha1(signature_source.encode("utf-8")).hexdigest()
    state_key = f"source_preview_result_{widget_key}"

    if st.button(
        "Carregar prévia leve",
        key=f"load_source_preview_{widget_key}",
        width="stretch",
    ):
        try:
            with st.spinner("Gerando prévia leve..."):
                preview_path = create_preview_clip(
                    source,
                    start,
                    preview_end,
                    ffmpeg_path=ffmpeg_path,
                )
            st.session_state[state_key] = {
                "signature": signature,
                "path": str(preview_path),
            }
        except Exception as error:
            st.session_state.pop(state_key, None)
            st.error(str(error))

    preview = st.session_state.get(state_key)
    if (
        isinstance(preview, dict)
        and preview.get("signature") == signature
        and Path(str(preview.get("path", ""))).exists()
    ):
        st.video(str(preview["path"]), format="video/mp4")
        duration = preview_end - start
        st.caption(
            f"Prévia leve de {duration:.0f}s. "
            "O corte final continua usando o vídeo original."
        )
    elif requested_end > preview_end:
        st.caption(
            "A prévia mostra os primeiros 2 minutos deste intervalo. "
            "O corte final mantém a duração completa."
        )


def render_source_frame_preview(
    video_path: str,
    time_seconds: float,
    *,
    widget_key: str,
    caption: str,
    ffmpeg_path: str = "",
) -> bool:
    """Capture and display one source-video frame, returning whether it is current."""
    if not video_path or not Path(video_path).exists():
        st.warning("Carregue o vídeo da tela/gráficos para capturar este momento.")
        return False

    source = Path(video_path)
    source_stat = source.stat()
    signature_source = "|".join(
        (
            "streamlit-source-frame-v1",
            str(source.resolve()),
            str(source_stat.st_size),
            str(source_stat.st_mtime_ns),
            f"{max(0.0, float(time_seconds)):.3f}",
        )
    )
    signature = hashlib.sha1(signature_source.encode("utf-8")).hexdigest()
    state_key = f"source_frame_preview_{widget_key}"

    if st.button(
        "Capturar/atualizar imagem",
        key=f"capture_source_frame_{widget_key}",
        width="stretch",
    ):
        try:
            with st.spinner("Capturando o relógio no vídeo da tela..."):
                image = capture_frame(
                    source,
                    max(0.0, float(time_seconds)),
                    ffmpeg_path=ffmpeg_path,
                )
            st.session_state[state_key] = {
                "image": image,
                "signature": signature,
            }
        except Exception as error:
            st.session_state.pop(state_key, None)
            st.error(str(error))

    preview = st.session_state.get(state_key)
    if isinstance(preview, dict) and preview.get("signature") == signature:
        st.image(preview["image"], caption=caption, width="stretch")
        return True
    if preview:
        st.info("A captura está desatualizada. Atualize-a para conferir este instante.")
    return False


def apply_rows(
    operations: list[Operation],
    rows,
    presets: dict[str, dict[str, float]],
) -> list[Operation]:
    edited: list[Operation] = []
    for operation, row in zip(operations, rows.to_dict("records")):
        operation.selected = bool(row["Usar"])
        operation.sequence_order = max(0, int(row.get("Ordem", 0) or 0))
        operation.title = str(row["Operação"])
        operation.crop_area = LABEL_TO_AREA.get(str(row["Área"]), "full")

        try:
            entry_time = parse_timecode(row["Entrada"])
        except ValueError:
            entry_time = None
            st.warning(f'Entrada inválida em “{operation.title}”. Use HH:MM:SS.')
        try:
            cut_start = parse_timecode(row["Início"])
        except ValueError:
            cut_start = None
            st.warning(f'Início inválido em “{operation.title}”. Use HH:MM:SS.')
        try:
            cut_end = parse_timecode(row["Fim"])
        except ValueError:
            cut_end = None
            st.warning(f'Fim inválido em “{operation.title}”. Use HH:MM:SS.')
        if entry_time is not None:
            operation.entry_time = entry_time
        if cut_start is not None and cut_end is not None:
            try:
                operation.set_cut_bounds(cut_start, cut_end)
            except ValueError as error:
                st.warning(f'Horários de “{operation.title}”: {error}')

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


@st.cache_data(show_spinner=False)
def cached_recordings(folder: str):
    return scan_recordings(folder, recursive=True)


def clear_loaded_recording_state() -> None:
    for key in (
        "source",
        "cues",
        "operations",
        "operations_editor",
        "crop_preview_image",
        "vertical_frame_preview",
        "vertical_preview_path",
        "clock_sync",
        "clock_sync_video_time_input",
        "clock_sync_clock_time_input",
        "annotated_cut_time",
    ):
        st.session_state.pop(key, None)
    for key in list(st.session_state):
        if key.startswith(
            (
                "source_preview_result_",
                "load_source_preview_",
                "source_frame_preview_",
                "capture_source_frame_",
            )
        ):
            st.session_state.pop(key, None)


def load_exported_project(path: str) -> Path:
    manifest_path, manifest = load_project_manifest(path)
    files = manifest["files"]
    cuts_path = resolve_project_file(manifest_path, files.get("cuts"))
    if cuts_path is None or not cuts_path.exists():
        raise FileNotFoundError("O cuts.json do projeto não foi encontrado.")

    source_transcript = resolve_project_file(
        manifest_path,
        files.get("source_transcript"),
    )
    if source_transcript is None or not source_transcript.exists():
        source_transcript = resolve_project_file(
            manifest_path,
            manifest.get("sources", {}).get("transcript"),
        )

    loaded_operations = load_operations(cuts_path)
    loaded_cues = []
    if source_transcript is not None and source_transcript.exists():
        loaded_cues = parse_vtt(source_transcript)

    clear_loaded_recording_state()
    st.session_state["operations"] = loaded_operations
    if source_transcript is not None and source_transcript.exists():
        st.session_state["source"] = str(source_transcript)
        st.session_state["cues"] = loaded_cues
        st.session_state["transcript_path_input"] = str(source_transcript)
    else:
        st.session_state["source"] = ""
        st.session_state["cues"] = []
        st.session_state["transcript_path_input"] = ""

    sources = manifest.get("sources", {})
    st.session_state["video_path_input"] = str(sources.get("screen_video", ""))
    st.session_state["professor_video_path_input"] = str(
        sources.get("professor_video", "")
    )
    settings = manifest.get("settings", {})
    widget_generation = st.session_state.get("project_widget_generation", 0) + 1
    st.session_state["project_widget_generation"] = widget_generation
    st.session_state[f"target_speaker_input_{widget_generation}"] = str(
        settings.get("target_speaker", "RAFAEL FOSSALUSSA")
    )
    orientation = str(settings.get("orientation", "vertical"))
    st.session_state[f"final_output_orientation_label_{widget_generation}"] = (
        OUTPUT_ORIENTATION_LABELS.get(orientation, OUTPUT_ORIENTATION_LABELS["vertical"])
    )
    st.session_state[f"final_professor_sync_offset_{widget_generation}"] = float(
        settings.get("professor_sync_offset", 0.0)
    )
    clock_sync_video_time = settings.get("clock_sync_video_time")
    clock_sync_clock_time = settings.get("clock_sync_clock_time")
    if clock_sync_video_time is not None and clock_sync_clock_time is not None:
        clock_sync = {
            "video_time": float(clock_sync_video_time),
            "clock_time": float(clock_sync_clock_time),
        }
        st.session_state["clock_sync"] = clock_sync
        st.session_state["clock_sync_video_time_input"] = format_timecode(
            clock_sync["video_time"]
        )
        st.session_state["clock_sync_clock_time_input"] = format_timecode(
            clock_sync["clock_time"]
        )
    st.session_state[f"final_audio_source_label_{widget_generation}"] = (
        "Vídeo da tela"
        if settings.get("audio_source") == "screen"
        else "Vídeo do professor"
    )
    st.session_state[f"final_subtitles_enabled_{widget_generation}"] = bool(
        settings.get("subtitles_enabled", True)
    )
    st.session_state[f"final_subtitles_only_presenter_{widget_generation}"] = bool(
        settings.get("subtitles_only_presenter", True)
    )
    subtitle_style = str(settings.get("subtitle_style", "normal"))
    st.session_state[f"final_subtitle_style_label_{widget_generation}"] = (
        SUBTITLE_STYLE_LABELS.get(subtitle_style, SUBTITLE_STYLE_LABELS["normal"])
    )
    st.session_state["transcript_upload_generation"] = (
        st.session_state.get("transcript_upload_generation", 0) + 1
    )
    st.session_state["loaded_project_manifest"] = str(manifest_path)
    return manifest_path


with st.sidebar:
    st.header("Configuração")
    with st.expander("Abrir projeto exportado", expanded=False):
        project_path = st.text_input(
            "Pasta do projeto ou project.json",
            key="project_path_input",
            placeholder=r"C:\Videos\output\2026-08-01_143218_video-final",
        )
        if st.button("Abrir projeto", width="stretch", disabled=not project_path.strip()):
            try:
                loaded_manifest = load_exported_project(project_path)
                st.session_state["project_loaded_message"] = (
                    f"Projeto carregado: {loaded_manifest.parent.name}"
                )
            except Exception as error:
                st.error(str(error))
        loaded_message = st.session_state.pop("project_loaded_message", "")
        if loaded_message:
            st.success(loaded_message)

    st.subheader("Biblioteca de gravações")
    user_config = load_user_config()
    st.session_state.setdefault(
        "recordings_folder_input",
        str(user_config.get("recordings_folder", "") or DEFAULT_RECORDINGS_FOLDER),
    )
    recordings_folder = st.text_input(
        "Pasta padrão",
        key="recordings_folder_input",
        placeholder=r"C:\Videos\Aulas",
    )
    save_folder_column, refresh_column = st.columns(2)
    save_folder_clicked = save_folder_column.button("Salvar pasta", width="stretch")
    refresh_recordings_clicked = refresh_column.button("Atualizar", width="stretch")

    if save_folder_clicked:
        folder = Path(recordings_folder)
        if not folder.exists() or not folder.is_dir():
            st.error("Informe uma pasta válida antes de salvar.")
        else:
            save_user_config({"recordings_folder": str(folder.resolve())})
            st.success("Pasta padrão salva neste computador.")
    if refresh_recordings_clicked:
        cached_recordings.clear()

    recordings = []
    if recordings_folder:
        folder = Path(recordings_folder)
        if folder.exists() and folder.is_dir():
            try:
                recordings = cached_recordings(str(folder.resolve()))
            except Exception as error:
                st.error(str(error))
        else:
            st.caption("A pasta informada ainda não foi encontrada.")

    selected_recording = None
    if recordings:
        recordings_by_key = {item.key: item for item in recordings}
        selected_recording_key = st.selectbox(
            "Gravação",
            options=list(recordings_by_key),
            format_func=lambda key: recordings_by_key[key].label,
            key="recording_catalog_selection",
        )
        selected_recording = recordings_by_key[selected_recording_key]
        st.caption(f"{len(recordings)} gravação(ões) encontrada(s), incluindo subpastas.")
        status_rows = (
            ("Tela", selected_recording.screen_video),
            ("Transcrição", selected_recording.transcript),
            ("Professor", selected_recording.professor_video),
        )
        for label, path in status_rows:
            st.write(f"{'✅' if path else '❌'} {label}")
        with st.expander("Ver caminhos encontrados"):
            for label, path in status_rows:
                st.caption(f"{label}: {path or 'não encontrado'}")

        can_load_recording = bool(
            selected_recording.screen_video and selected_recording.transcript
        )
        if st.button(
            "Carregar gravação",
            type="primary",
            width="stretch",
            disabled=not can_load_recording,
        ):
            try:
                clear_loaded_recording_state()
                st.session_state["transcript_path_input"] = selected_recording.transcript
                st.session_state["video_path_input"] = selected_recording.screen_video
                st.session_state["professor_video_path_input"] = (
                    selected_recording.professor_video
                )
                st.session_state["loaded_recording_id"] = selected_recording.key
                st.session_state["transcript_upload_generation"] = (
                    st.session_state.get("transcript_upload_generation", 0) + 1
                )
                loaded_cues = parse_vtt(selected_recording.transcript)
                st.session_state["source"] = selected_recording.transcript
                st.session_state["cues"] = loaded_cues
                st.success(
                    f"Gravação carregada com {len(loaded_cues)} trechos de transcrição."
                )
            except Exception as error:
                st.error(str(error))
    elif recordings_folder and Path(recordings_folder).is_dir():
        st.caption("Nenhuma gravação com o padrão esperado foi encontrada.")

    st.divider()
    st.subheader("Arquivos")
    default_transcript = str(Path("examples/GMT20260717-114920_Recording.transcript.vtt"))
    st.session_state.setdefault("transcript_path_input", default_transcript)
    st.session_state.setdefault("video_path_input", "")
    st.session_state.setdefault("professor_video_path_input", "")
    upload_generation = st.session_state.get("transcript_upload_generation", 0)
    transcript_upload = st.file_uploader(
        "Transcrição VTT",
        type=["vtt"],
        key=f"transcript_upload_{upload_generation}",
    )
    transcript_path = st.text_input("Ou caminho local do VTT", key="transcript_path_input")
    video_path = st.text_input(
        "Vídeo da tela",
        placeholder=r"C:\Videos\gravacao-tela.mp4",
        key="video_path_input",
        on_change=_invalidate_clock_sync,
    )
    professor_video_path = st.text_input(
        "Vídeo do professor (opcional)",
        placeholder=r"C:\Videos\professor.mp4",
        key="professor_video_path_input",
    )
    ffmpeg_path = st.text_input(
        "Caminho do ffmpeg.exe (opcional)",
        value=default_ffmpeg_path(),
        help="O FFmpeg instalado pelo WinGet já é preenchido como padrão deste projeto.",
    )
    project_widget_generation = st.session_state.get("project_widget_generation", 0)
    target_speaker_key = f"target_speaker_input_{project_widget_generation}"
    st.session_state.setdefault(target_speaker_key, "RAFAEL FOSSALUSSA")
    target_speaker = st.text_input(
        "Apresentador a detectar",
        key=target_speaker_key,
    )
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
        operations = detect_operations(cues, config, rules=load_rules(RULES_PATH))
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

with st.expander("Gerenciar regras automáticas", expanded=False):
    rule_message = st.session_state.pop("rule_editor_message", "")
    if rule_message:
        st.success(rule_message)
    st.caption(
        "Editar ou salvar não altera os cortes atuais. "
        "Use Salvar e reanalisar para aplicar as regras à transcrição carregada."
    )
    try:
        current_rules = load_rules(RULES_PATH)
    except ValueError as error:
        st.error(str(error))
        st.info("Os padrões originais foram carregados para permitir a recuperação.")
        current_rules = default_rules()

    rules_editor_generation = st.session_state.get("rules_editor_generation", 0)
    edited_rules_df = st.data_editor(
        pd.DataFrame(rule_rows(current_rules)),
        hide_index=True,
        width="stretch",
        num_rows="dynamic",
        column_config={
            "Ativa": st.column_config.CheckboxColumn(required=True),
            "Categoria": st.column_config.SelectboxColumn(
                options=list(RULE_CATEGORY_LABELS.values()),
                required=True,
            ),
            "Tipo": st.column_config.SelectboxColumn(
                options=list(RULE_MODE_LABELS.values()),
                required=True,
            ),
            "Expressão": st.column_config.TextColumn(required=True, width="large"),
            "Resultado": st.column_config.TextColumn(
                help="Obrigatório somente para regras da categoria Resultado."
            ),
            "Peso": st.column_config.NumberColumn(
                min_value=0.0,
                max_value=1.0,
                step=0.05,
                format="%.2f",
                required=True,
            ),
            "ID": None,
        },
        disabled=["ID"],
        key=f"rules_editor_{rules_editor_generation}",
    )
    st.caption(
        "Texto simples procura a palavra/frase inteira e ignora acentos. "
        "Regex mantém o comportamento avançado das regras originais."
    )

    validate_column, save_column, analyze_column, restore_column = st.columns(4)
    validate_rules_clicked = validate_column.button("Validar", width="stretch")
    save_rules_clicked = save_column.button("Salvar", width="stretch")
    reanalyze_rules_clicked = analyze_column.button(
        "Salvar e reanalisar",
        width="stretch",
        disabled=not bool(cues),
    )
    restore_rules_clicked = restore_column.button("Restaurar padrões", width="stretch")

    if restore_rules_clicked:
        save_rules(default_rules(), RULES_PATH)
        st.session_state["rules_editor_generation"] = rules_editor_generation + 1
        st.session_state["rule_editor_message"] = "Regras originais restauradas."
        st.rerun()

    if validate_rules_clicked or save_rules_clicked or reanalyze_rules_clicked:
        try:
            edited_rules = apply_rule_rows(edited_rules_df)
            compile_rules(edited_rules)
            if validate_rules_clicked:
                st.success(f"{len(edited_rules)} regras válidas.")
            if save_rules_clicked:
                target = save_rules(edited_rules, RULES_PATH)
                st.success(f"{len(edited_rules)} regras salvas em {target}.")
            if reanalyze_rules_clicked:
                save_rules(edited_rules, RULES_PATH)
                manual_operations = [
                    operation for operation in operations if operation.source == "manual"
                ]
                old_automatic_count = len(operations) - len(manual_operations)
                config = DetectionConfig(
                    target_speaker=target_speaker,
                    minimum_confidence=minimum_confidence,
                )
                automatic_operations = detect_operations(
                    cues,
                    config,
                    rules=edited_rules,
                )
                operations = sorted(
                    automatic_operations + manual_operations,
                    key=lambda operation: operation.entry_time,
                )
                st.session_state["operations"] = operations
                st.session_state.pop("operations_editor", None)
                st.success(
                    f"Reanálise concluída: {old_automatic_count} → "
                    f"{len(automatic_operations)} cortes automáticos. "
                    f"{len(manual_operations)} corte(s) manual(is) preservado(s)."
                )
        except Exception as error:
            st.error(str(error))

    st.caption(
        "Continuam protegidas no código: associação entre entrada e resultado, "
        "remoção de duplicidades, direção, ativos e limites de tempo."
    )

added_message = st.session_state.pop("manual_cut_added_message", "")
if added_message:
    st.success(added_message)

if cues:
    st.subheader("Buscar uma palavra na transcrição")
    with st.container(border=True):
        search_column, context_column = st.columns([3, 1])
        search_word = search_column.text_input(
            "Palavra",
            placeholder="Ex.: resistência",
            key="transcript_search_word",
        )
        context_seconds = context_column.select_slider(
            "Contexto",
            options=[15, 30, 60, 120],
            value=30,
            format_func=lambda value: f"{value}s",
            key="transcript_search_context",
        )

        if search_word.strip():
            try:
                matches = search_cues(cues, search_word)
                if not matches:
                    st.info(f'A palavra "{search_word.strip()}" não foi encontrada.')
                else:
                    if len(matches) > 300:
                        st.warning(
                            f"{len(matches)} ocorrências encontradas. "
                            "Mostrando as primeiras 300; use uma palavra mais específica se necessário."
                        )
                    else:
                        st.caption(f"{len(matches)} ocorrência(s) encontrada(s).")
                    visible_matches = matches[:300]
                    search_key = hashlib.sha1(
                        search_word.strip().lower().encode("utf-8")
                    ).hexdigest()[:10]
                    match_index = st.selectbox(
                        "Onde a palavra aparece",
                        options=range(len(visible_matches)),
                        format_func=lambda index: (
                            f"{format_timecode(visible_matches[index].start)} — "
                            f"{visible_matches[index].speaker or 'Sem identificação'}: "
                            f"{visible_matches[index].text[:120]}"
                        ),
                        key=f"transcript_match_{search_key}",
                    )
                    match = visible_matches[match_index]
                    context_start = max(0.0, match.start - context_seconds)
                    context_end = match.end + context_seconds

                    transcript_column, video_column = st.columns([1, 1])
                    with transcript_column:
                        st.markdown("**Transcrição ao redor da ocorrência**")
                        st.code(
                            transcript_between(cues, context_start, context_end),
                            language=None,
                        )
                    with video_column:
                        st.markdown("**Vídeo nesse ponto**")
                        render_source_video_preview(
                            video_path,
                            max(0.0, match.start - 5),
                            match.end + 30,
                            widget_key=f"search_{search_key}_{match.index}",
                            ffmpeg_path=ffmpeg_path,
                        )

                    st.markdown("**Adicionar como corte manual**")
                    form_key = f"manual_cut_{search_key}_{match.index}"
                    with st.form(form_key):
                        manual_title = st.text_input(
                            "Título do corte",
                            value=f"Trecho sobre {search_word.strip()}",
                        )
                        manual_left, manual_middle, manual_right = st.columns([1, 1, 1])
                        manual_start_value = manual_left.text_input(
                            "Início",
                            value=format_timecode(match.start),
                            help="Começa exatamente no horário encontrado; o contexto aparece apenas na prévia.",
                        )
                        manual_end_value = manual_middle.text_input(
                            "Fim",
                            value=format_timecode(match.end + 30),
                            help="Padrão: 30 segundos depois da palavra.",
                        )
                        manual_area_label = manual_right.selectbox(
                            "Área",
                            options=list(AREA_LABELS.values()),
                            index=0,
                        )
                        add_manual_cut_clicked = st.form_submit_button(
                            "Adicionar corte manual",
                            type="primary",
                            width="stretch",
                        )

                    if add_manual_cut_clicked:
                        try:
                            manual_operation = add_manual_operation(
                                title=manual_title,
                                start_value=manual_start_value,
                                end_value=manual_end_value,
                                entry_time=match.start,
                                area_label=manual_area_label,
                                evidence=[match.text],
                                identity=f"search-{match.index}",
                                presets=presets,
                            )
                            st.session_state["manual_cut_added_message"] = (
                                f'Corte "{manual_operation.title}" adicionado à tabela.'
                            )
                            st.rerun()
                        except Exception as error:
                            st.error(str(error))
            except ValueError as error:
                st.warning(str(error))

st.subheader("Adicionar corte por horário anotado")
with st.container(border=True):
    st.markdown("**1. Sincronize o relógio com o vídeo da tela/gráficos**")
    st.session_state.setdefault("clock_sync_video_time_input", "00:00:00")
    sync_video_column, sync_clock_column = st.columns(2)
    sync_video_time_value = sync_video_column.text_input(
        "Posição correspondente no vídeo",
        placeholder="HH:MM:SS",
        help="Escolha um instante em que o relógio esteja claramente visível.",
        key="clock_sync_video_time_input",
        on_change=_clock_sync_video_time_changed,
        args=("clock_sync_video_time_input",),
    )
    sync_clock_time_value = sync_clock_column.text_input(
        "Horário mostrado no relógio",
        placeholder="HH:MM:SS",
        help="Digite exatamente o horário visível na captura abaixo.",
        key="clock_sync_clock_time_input",
        on_change=_clock_sync_clock_time_changed,
    )

    sync_video_time = None
    try:
        sync_video_time = parse_timecode(sync_video_time_value)
    except ValueError as error:
        st.warning(str(error))

    sync_frame_ready = False
    if sync_video_time is not None:
        sync_frame_ready = render_source_frame_preview(
            video_path,
            sync_video_time,
            widget_key="clock_sync",
            caption=(
                "Vídeo da tela/gráficos em "
                f"{format_timecode(sync_video_time)} — confira o relógio nesta imagem"
            ),
            ffmpeg_path=ffmpeg_path,
        )

    if st.button(
        "Confirmar sincronização",
        type="primary",
        disabled=not sync_frame_ready or not sync_clock_time_value.strip(),
        width="stretch",
    ):
        try:
            sync_clock_time = parse_clock_time(sync_clock_time_value)
            if sync_video_time is None or sync_clock_time is None:
                raise ValueError("Informe os dois horários da sincronização.")
            st.session_state["clock_sync"] = {
                "video_time": sync_video_time,
                "clock_time": sync_clock_time,
            }
            st.rerun()
        except ValueError as error:
            st.error(str(error))

    clock_sync = st.session_state.get("clock_sync")
    if isinstance(clock_sync, dict):
        st.success(
            f"Sincronização confirmada: relógio "
            f"{format_timecode(clock_sync['clock_time'])} = vídeo "
            f"{format_timecode(clock_sync['video_time'])}."
        )
    else:
        st.caption(
            "Capture a imagem, leia o relógio exibido nela e confirme a correspondência."
        )

    st.divider()
    st.markdown("**2. Localize a anotação pelo horário do relógio**")
    annotated_time_value = st.text_input(
        "Horário anotado",
        placeholder="HH:MM:SS",
        help="Exemplo: 14:45:20. Este é o horário real anotado durante a sala.",
        key="annotated_cut_time",
        disabled=not isinstance(clock_sync, dict),
    )
    if not isinstance(clock_sync, dict):
        st.info("Confirme a sincronização acima para localizar uma anotação.")
    elif annotated_time_value.strip():
        try:
            annotated_clock_time = parse_clock_time(annotated_time_value)
            if annotated_clock_time is None:
                raise ValueError("Informe um horário anotado válido.")
            annotated_video_time = clock_time_to_video_time(
                annotated_clock_time,
                clock_sync["clock_time"],
                clock_sync["video_time"],
            )
            annotated_key = hashlib.sha1(
                (
                    f"{annotated_clock_time:.3f}-"
                    f"{annotated_video_time:.3f}"
                ).encode("utf-8")
            ).hexdigest()[:10]

            st.success(
                f"Horário anotado {format_timecode(annotated_clock_time)} "
                f"→ posição {format_timecode(annotated_video_time)} no vídeo."
            )

            annotated_left, annotated_right = st.columns([1, 1])
            with annotated_left:
                st.markdown("**Transcrição ao redor do horário**")
                if cues:
                    st.code(
                        transcript_between(
                            cues,
                            max(0.0, annotated_video_time - 30),
                            annotated_video_time + 30,
                        ),
                        language=None,
                    )
                else:
                    st.caption("Carregue uma transcrição para visualizar o contexto.")
            with annotated_right:
                st.markdown("**Captura para conferir o relógio**")
                render_source_frame_preview(
                    video_path,
                    annotated_video_time,
                    widget_key=f"annotated_clock_{annotated_key}",
                    caption=(
                        f"Vídeo em {format_timecode(annotated_video_time)} — "
                        f"o relógio deve mostrar {format_timecode(annotated_clock_time)}"
                    ),
                    ffmpeg_path=ffmpeg_path,
                )
                st.markdown("**Prévia em vídeo (opcional)**")
                render_source_video_preview(
                    video_path,
                    max(0.0, annotated_video_time - 5),
                    annotated_video_time + 30,
                    widget_key=f"annotated_{annotated_key}",
                    ffmpeg_path=ffmpeg_path,
                )

            with st.form(f"annotated_cut_{annotated_key}"):
                annotated_title = st.text_input(
                    "Título do corte por horário",
                    value=f"Corte {format_timecode(annotated_clock_time)}",
                )
                time_left, time_middle, time_right = st.columns([1, 1, 1])
                annotated_start_value = time_left.text_input(
                    "Início do corte no vídeo",
                    value=format_timecode(annotated_video_time),
                    help="Posição relativa calculada; pode ser ajustada normalmente.",
                )
                annotated_end_value = time_middle.text_input(
                    "Fim do corte no vídeo",
                    value=format_timecode(annotated_video_time + 30),
                    help="Padrão: 30 segundos depois da posição calculada.",
                )
                annotated_area_label = time_right.selectbox(
                    "Área do corte",
                    options=list(AREA_LABELS.values()),
                    index=0,
                )
                add_annotated_cut_clicked = st.form_submit_button(
                    "Adicionar corte pelo horário",
                    type="primary",
                    width="stretch",
                )

            if add_annotated_cut_clicked:
                try:
                    nearby_cues = sorted(
                        cues,
                        key=lambda cue: abs(cue.start - annotated_video_time),
                    ) if cues else []
                    evidence = (
                        [nearby_cues[0].text]
                        if nearby_cues
                        else [
                            f"Horário anotado: {format_timecode(annotated_clock_time)} "
                            f"(vídeo: {format_timecode(annotated_video_time)})"
                        ]
                    )
                    manual_operation = add_manual_operation(
                        title=annotated_title,
                        start_value=annotated_start_value,
                        end_value=annotated_end_value,
                        entry_time=annotated_video_time,
                        area_label=annotated_area_label,
                        evidence=evidence,
                        identity=(
                            f"annotated-{annotated_clock_time:.3f}-"
                            f"{annotated_video_time:.3f}"
                        ),
                        presets=presets,
                    )
                    st.session_state["manual_cut_added_message"] = (
                        f'Corte "{manual_operation.title}" adicionado à tabela.'
                    )
                    st.rerun()
                except Exception as error:
                    st.error(str(error))
        except ValueError as error:
            st.warning(str(error))

if operations:
    if st.session_state.pop("refresh_operations_editor", False):
        st.session_state.pop("operations_editor", None)
    for operation_index, existing_operation in enumerate(operations, 1):
        if existing_operation.sequence_order <= 0:
            existing_operation.sequence_order = operation_index
        existing_operation.ensure_scenes()

    st.subheader("2. Revise os trechos, a ordem e as cenas")
    st.info(
        "Edite início, fim, título, seleção, ordem e área diretamente na tabela. "
        "Use HH:MM:SS."
    )
    edited_df = st.data_editor(
        pd.DataFrame(operation_rows(operations)),
        hide_index=True,
        width="stretch",
        column_config={
            "Usar": st.column_config.CheckboxColumn(),
            "Ordem": st.column_config.NumberColumn(min_value=1, step=1),
            "Área": st.column_config.SelectboxColumn(options=list(AREA_LABELS.values()), required=True),
            "Confiança": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d%%"),
        },
        disabled=["Cenas", "Confiança", "Fonte"],
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
        st.write(f"**Ordem no vídeo final:** {operation.sequence_order} · **Cenas:** {len(operation.scenes)}")
        if False and operation.layout_mode == "split_then_professor":
            default_switch_time = operation.layout_switch_time
            if (
                default_switch_time is None
                or default_switch_time <= operation.cut_start
                or default_switch_time >= operation.cut_end
            ):
                default_switch_time = (
                    operation.cut_start + (operation.cut_end - operation.cut_start) / 2
                )
            switch_value = st.text_input(
                "Mudar para professor em",
                value=format_timecode(default_switch_time),
                key=f"layout_switch_time_{operation.id}",
                help="Horário absoluto da aula, entre o início e o fim deste corte.",
            )
            parsed_switch_time = parse_timecode(switch_value)
            if (
                parsed_switch_time is not None
                and operation.cut_start < parsed_switch_time < operation.cut_end
            ):
                operation.layout_switch_time = parsed_switch_time
                st.caption(
                    f"A tela ficará dividida por "
                    f"{format_timecode(parsed_switch_time - operation.cut_start)} "
                    "e depois mostrará somente o professor."
                )
            else:
                operation.layout_switch_time = None
                st.warning("A mudança precisa ficar entre o início e o fim do corte.")
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
        render_source_video_preview(
            video_path,
            operation.cut_start,
            operation.cut_end,
            widget_key="selected_cut",
            ffmpeg_path=ffmpeg_path,
        )

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
    professor_sync_offset = 0.0
    audio_source = "professor"
    st.markdown("### 3. Monte as cenas e o vídeo final")
    project_left, project_middle, project_right = st.columns(3)
    orientation_widget_key = f"final_output_orientation_label_{project_widget_generation}"
    sync_widget_key = f"final_professor_sync_offset_{project_widget_generation}"
    audio_widget_key = f"final_audio_source_label_{project_widget_generation}"
    subtitles_widget_key = f"final_subtitles_enabled_{project_widget_generation}"
    subtitle_style_widget_key = f"final_subtitle_style_label_{project_widget_generation}"
    presenter_subtitles_widget_key = (
        f"final_subtitles_only_presenter_{project_widget_generation}"
    )
    st.session_state.setdefault(
        orientation_widget_key,
        OUTPUT_ORIENTATION_LABELS["vertical"],
    )
    st.session_state.setdefault(sync_widget_key, 0.0)
    st.session_state.setdefault(audio_widget_key, "Vídeo do professor")
    st.session_state.setdefault(subtitles_widget_key, True)
    st.session_state.setdefault(
        subtitle_style_widget_key,
        SUBTITLE_STYLE_LABELS["normal"],
    )
    st.session_state.setdefault(presenter_subtitles_widget_key, True)
    orientation_label = project_left.radio(
        "Orientação do vídeo final",
        list(OUTPUT_ORIENTATION_LABELS.values()),
        horizontal=True,
        key=orientation_widget_key,
    )
    orientation = next(
        key for key, label in OUTPUT_ORIENTATION_LABELS.items() if label == orientation_label
    )
    professor_sync_offset = project_middle.number_input(
        "Sincronização do professor (s)",
        step=0.1,
        help="Positivo avança o vídeo do professor.",
        key=sync_widget_key,
    )
    audio_label = project_right.radio(
        "Áudio contínuo",
        ["Vídeo do professor", "Vídeo da tela"],
        horizontal=True,
        key=audio_widget_key,
    )
    audio_source = "professor" if audio_label == "Vídeo do professor" else "screen"
    subtitle_left, subtitle_middle, subtitle_right = st.columns(3)
    subtitles_enabled = subtitle_left.checkbox(
        "Gravar legendas no vídeo",
        key=subtitles_widget_key,
        help="Usa os textos e horários da transcrição VTT carregada.",
    )
    subtitle_style_label = subtitle_middle.selectbox(
        "Estilo da legenda",
        list(SUBTITLE_STYLE_LABELS.values()),
        key=subtitle_style_widget_key,
        disabled=not subtitles_enabled,
    )
    subtitle_style = next(
        key for key, label in SUBTITLE_STYLE_LABELS.items()
        if label == subtitle_style_label
    )
    subtitles_only_presenter = subtitle_right.checkbox(
        "Legendar somente o apresentador",
        key=presenter_subtitles_widget_key,
        disabled=not subtitles_enabled,
    )
    subtitle_speaker = target_speaker if subtitles_only_presenter else ""
    if subtitles_enabled and subtitles_only_presenter:
        st.caption(f'As legendas usarão somente as falas identificadas como “{target_speaker}”.')
    elif subtitles_enabled:
        st.caption("As falas de todos os participantes presentes no VTT serão legendadas.")
    for item in operations:
        item.output_orientation = orientation

    if not professor_video_path or not Path(professor_video_path).exists():
        st.warning("Informe um vídeo do professor válido para montar e exportar as cenas.")
    with st.expander(f"Editar cenas · {operation.title}", expanded=True):
        render_scene_editor(
            operation,
            video_path=video_path,
            professor_video_path=professor_video_path,
            orientation=orientation,
            professor_sync_offset=professor_sync_offset,
            audio_source=audio_source,
            cues=cues,
            subtitles_enabled=subtitles_enabled,
            subtitle_speaker=subtitle_speaker,
            subtitle_style=subtitle_style,
            target_speaker=target_speaker,
            ffmpeg_path=ffmpeg_path,
        )

    st.caption(
        "A exportação recodifica as cenas para manter a mesma resolução e o áudio "
        "contínuo antes de reuni-las em um arquivo."
    )
    final_filename = st.text_input(
        "Nome-base do projeto e do vídeo",
        value="video-final.mp4",
        key="final_video_filename",
        help="A data e o horário serão adicionados automaticamente à pasta e ao MP4.",
    ).strip()
    final_filename = Path(final_filename or "video-final.mp4").name
    if not final_filename.lower().endswith(".mp4"):
        final_filename += ".mp4"

    col_json, col_report, col_export = st.columns(3)
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
    with col_export:
        if st.button("4. Exportar vídeo final", type="primary", width="stretch"):
            project_directory: Path | None = None
            try:
                if not video_path:
                    raise ValueError("Informe o caminho do vídeo da tela.")
                if not professor_video_path:
                    raise ValueError("Informe o caminho do vídeo do professor.")
                find_ffmpeg(ffmpeg_path)
                project_directory = create_project_directory(output_dir, final_filename)
                source_transcript_path = st.session_state.get("source", "")
                cuts_path = save_operations(
                    project_directory / "cuts.json",
                    operations,
                    source_transcript_path,
                )
                report_path = create_html_report(
                    project_directory / "report.html",
                    operations,
                    video_path=video_path,
                )
                copied_source_transcript = copy_source_transcript(
                    source_transcript_path,
                    project_directory,
                )
                progress = st.progress(0, text="Preparando...")

                def update(index: int, total: int, message: str) -> None:
                    progress.progress(index / max(total, 1), text=message)

                dated_video_path = project_video_path(project_directory)
                target = export_final_video(
                    video_path,
                    professor_video_path,
                    operations,
                    dated_video_path,
                    orientation=orientation,
                    ffmpeg_path=ffmpeg_path,
                    progress=update,
                    professor_sync_offset=professor_sync_offset,
                    audio_source=audio_source,
                    cues=cues,
                    burn_subtitles=subtitles_enabled,
                    subtitle_speaker=subtitle_speaker,
                    subtitle_style=subtitle_style,
                    transcript_path=source_transcript_path,
                )
                generated_sidecars = sidecar_paths(target)
                manifest_path = write_project_manifest(
                    project_directory,
                    name=project_directory.name,
                    files={
                        "video": target,
                        "transcript": generated_sidecars["transcript"],
                        "captions": generated_sidecars["captions"],
                        "edit_map": generated_sidecars["edit_map"],
                        "cuts": cuts_path,
                        "report": report_path,
                        "source_transcript": copied_source_transcript,
                    },
                    source_video=video_path,
                    professor_video=professor_video_path,
                    source_transcript=source_transcript_path,
                    settings={
                        "orientation": orientation,
                        "professor_sync_offset": professor_sync_offset,
                        "clock_sync_video_time": (
                            clock_sync.get("video_time")
                            if isinstance(clock_sync, dict)
                            else None
                        ),
                        "clock_sync_clock_time": (
                            clock_sync.get("clock_time")
                            if isinstance(clock_sync, dict)
                            else None
                        ),
                        "audio_source": audio_source,
                        "subtitles_enabled": subtitles_enabled,
                        "subtitles_only_presenter": subtitles_only_presenter,
                        "subtitle_speaker": subtitle_speaker,
                        "subtitle_style": subtitle_style,
                        "target_speaker": target_speaker,
                        "scene_keywords": list(DEFAULT_SCENE_KEYWORDS),
                        "default_crop_area": "profit_index",
                        "default_layout": "professor_top",
                        "default_graph_alignment": "right",
                    },
                )
                st.session_state["final_video_path"] = str(target)
                st.success(f"Projeto exportado em {project_directory}")
                st.caption(
                    "Arquivos do projeto: "
                    + " · ".join(path.name for path in generated_sidecars.values())
                    + f" · {cuts_path.name} · {report_path.name} · {manifest_path.name}"
                )
            except Exception as error:
                if project_directory is not None:
                    error_path = write_export_error(project_directory, error)
                    st.caption(f"Projeto incompleto registrado em {error_path}")
                st.error(str(error))
    final_video_path = st.session_state.get("final_video_path")
    if final_video_path and Path(final_video_path).exists():
        st.video(final_video_path)
else:
    st.markdown(
        """
### Como testar

1. Mantenha a transcrição de exemplo ou escolha outro `.vtt`.
2. Clique em **Analisar transcrição**.
3. Revise os horários e escolha a área de cada corte.
4. Informe os vídeos da tela e do professor.
5. Organize os trechos, divida as cenas e ajuste os enquadramentos.
6. Clique em **Exportar vídeo final**.

O modo **Regras locais** não usa internet nem API. O modo **Ollama** mantém toda a análise no computador. O modo **Gemini** envia somente os trechos de texto candidatos.
"""
    )
