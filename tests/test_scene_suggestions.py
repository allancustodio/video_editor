from __future__ import annotations

from trade_cutter.models import Cue, Operation, Scene
from trade_cutter.scene_suggestions import (
    build_scene_suggestion_plan,
    materialize_suggestions,
    suggest_scenes,
)


def _operation(start: float = 0.0, end: float = 80.0) -> Operation:
    return Operation(
        id="op-1",
        title="Operação",
        asset="índice",
        direction="compra",
        setup_start=start,
        entry_time=start,
        operation_end=end,
        cut_start=start,
        cut_end=end,
        result="",
        confidence=1.0,
    )


def test_keywords_are_limited_to_cut_and_target_speaker() -> None:
    operation = _operation()
    cues = [
        Cue(1, 20.0, 22.0, "RAFAEL FOSSALUSSA", "Vou ajustar o stop agora."),
        Cue(2, 30.0, 32.0, "RAFAEL FOSSALUSSA", "Fiz parciais no primeiro alvo."),
        Cue(3, 40.0, 42.0, "ALUNO", "Peguei dois lotes com 1% de gain."),
        Cue(4, 90.0, 92.0, "RAFAEL FOSSALUSSA", "Bateu o alvo."),
    ]
    plan = suggest_scenes(
        operation,
        cues,
        target_speaker="Rafael",
        context_before=3.0,
        context_after=3.0,
    )

    assert plan.relevant_cue_count == 2
    assert plan.selected_occurrence_count == 2
    assert plan.occurrences[0].text == "Vou ajustar o stop agora."
    assert plan.occurrences[0].keywords == ("stop",)
    assert plan.occurrences[1].keywords == ("parcial", "alvo")
    assert (plan.occurrences[0].start, plan.occurrences[0].end) == (17.0, 25.0)


def test_percentage_lot_and_gain_variants_are_recognized() -> None:
    operation = _operation(0.0, 30.0)
    plan = suggest_scenes(
        operation,
        [
            Cue(
                1,
                10.0,
                12.0,
                "RAFAEL",
                "Dois lotes, cinquenta por cento e seguimos no gain.",
            )
        ],
        target_speaker="RAFAEL",
    )
    assert plan.occurrences[0].keywords == ("lote", "porcento", "gain")


def test_unselected_phrase_stays_in_accelerated_content() -> None:
    operation = _operation(0.0, 30.0)
    initial = suggest_scenes(
        operation,
        [Cue(1, 10.0, 12.0, "RAFAEL", "Vou ajustar o stop.")],
        target_speaker="RAFAEL",
    )
    plan = build_scene_suggestion_plan(
        operation,
        initial.occurrences,
        selected_occurrence_ids=set(),
        target_fast_duration=5.0,
        minimum_gap=12.0,
        max_speed=20.0,
    )

    assert plan.selected_occurrence_count == 0
    assert len(plan.scenes) == 1
    assert plan.scenes[0].kind == "accelerated"
    assert (plan.scenes[0].start, plan.scenes[0].end) == (0.0, 30.0)


def test_long_gap_requires_explicit_jump_approval() -> None:
    operation = _operation(0.0, 600.0)
    plan = suggest_scenes(operation, [], target_speaker="RAFAEL")
    assert len(plan.scenes) == 1
    assert plan.scenes[0].kind == "jump"

    kept = materialize_suggestions(operation, plan.scenes, max_speed=100.0)
    assert kept[0].skip is False
    assert kept[0].playback_speed == 100.0
    assert kept[0].audio_mode == "mute"
    assert kept[0].subtitles_enabled is False

    removed = materialize_suggestions(
        operation,
        plan.scenes,
        approved_jumps={0},
        max_speed=100.0,
    )
    assert removed[0].skip is True
    assert removed[0].output_duration == 0.0


def test_materialization_forces_agreed_default_composition() -> None:
    operation = _operation(0.0, 100.0)
    operation.scenes = [
        Scene(
            "old",
            0.0,
            100.0,
            "professor_full",
            professor_zoom=1.6,
            graph_zoom=1.4,
            graph_alignment="left",
        )
    ]
    plan = suggest_scenes(
        operation,
        [Cue(1, 45.0, 47.0, "RAFAEL", "Vou fazer uma parcial.")],
        target_speaker="RAFAEL",
    )
    scenes = materialize_suggestions(operation, plan.scenes, max_speed=20.0)

    assert all(scene.layout == "professor_top" for scene in scenes)
    assert all(scene.graph_alignment == "right" for scene in scenes)
    assert all(scene.professor_zoom == 1.6 for scene in scenes)
    assert all(scene.graph_zoom == 1.4 for scene in scenes)
    normal = next(scene for scene in scenes if scene.playback_speed == 1.0)
    assert normal.audio_mode == "project"
    assert normal.subtitles_enabled is True


def main() -> None:
    test_keywords_are_limited_to_cut_and_target_speaker()
    test_percentage_lot_and_gain_variants_are_recognized()
    test_unselected_phrase_stays_in_accelerated_content()
    test_long_gap_requires_explicit_jump_approval()
    test_materialization_forces_agreed_default_composition()
    print("OK: scene keyword suggestions")


if __name__ == "__main__":
    main()
