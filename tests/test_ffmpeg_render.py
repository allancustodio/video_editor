from __future__ import annotations

from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trade_cutter.ffmpeg import (
    build_scene_ass,
    capture_scene_frame,
    capture_professor_frame,
    capture_vertical_frame,
    create_preview_clip,
    cut_video,
    export_final_video,
    render_scene_video,
    scene_filter,
    validate_scene_timeline,
)
from trade_cutter.models import Cue, Operation, Scene
from trade_cutter.sidecars import write_export_sidecars


def operation(*, crop_area: str = "full") -> Operation:
    return Operation(
        id="test",
        title="Compra",
        asset="indice",
        direction="compra",
        setup_start=10.0,
        entry_time=12.0,
        operation_end=20.0,
        cut_start=10.0,
        cut_end=20.0,
        result="alvo",
        confidence=0.9,
        crop_area=crop_area,
        crop_x=0.5,
        crop_y=0.1,
        crop_width=0.25,
        crop_height=0.8,
    )


def rendered_command(op: Operation, **kwargs) -> list[str]:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        screen = root / "screen.mp4"
        professor = root / "professor.mp4"
        screen.touch()
        professor.touch()

        completed = SimpleNamespace(returncode=0, stderr="")
        with patch("trade_cutter.ffmpeg.find_ffmpeg", return_value="ffmpeg"), patch(
            "trade_cutter.ffmpeg.subprocess.run", return_value=completed
        ) as run:
            cut_video(
                screen,
                op,
                root / "output.mp4",
                professor_video_path=professor,
                **kwargs,
            )
        return run.call_args.args[0]


def rendered_scene_command(
    scene: Scene,
    *,
    cues: list[Cue] | None = None,
    audio_source: str = "professor",
) -> list[str]:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        screen = root / "screen.mp4"
        professor = root / "professor.mp4"
        screen.touch()
        professor.touch()
        completed = SimpleNamespace(returncode=0, stderr="")
        with patch("trade_cutter.ffmpeg.find_ffmpeg", return_value="ffmpeg"), patch(
            "trade_cutter.ffmpeg.subprocess.run", return_value=completed
        ) as run:
            render_scene_video(
                screen,
                professor,
                operation(crop_area="profit_index"),
                scene,
                root / "output.mp4",
                audio_source=audio_source,
                cues=cues,
                subtitle_speaker="PROFESSOR",
            )
        return run.call_args.args[0]


def test_full_fast_cut_keeps_copy_mode() -> None:
    command = rendered_command(operation(), mode="fast")
    assert "copy" in command
    assert "-vf" not in command


def test_area_cut_forces_crop_and_reencode() -> None:
    command = rendered_command(operation(crop_area="profit_index"), mode="fast")
    assert "copy" not in command
    assert "-vf" in command
    video_filter = command[command.index("-vf") + 1]
    assert "crop=" in video_filter
    assert "0.500000" in video_filter
    assert "0.250000" in video_filter


def test_vertical_cut_stacks_professor_and_graph() -> None:
    command = rendered_command(
        operation(crop_area="profit_index"),
        output_format="vertical",
        audio_source="professor",
        professor_zoom=1.25,
        professor_position_x=-100,
        professor_position_y=100,
        graph_zoom=1.5,
        graph_position_x=100,
        graph_position_y=-100,
    )
    filter_complex = command[command.index("-filter_complex") + 1]
    assert "crop=" in filter_complex
    assert "vstack=inputs=2" in filter_complex
    assert "scale=1350:1200" in filter_complex
    assert "scale=1620:1440" in filter_complex
    assert "crop=1080:960:540:0" in filter_complex
    assert "(iw-ow)*0.000000:(ih-oh)*1.000000" in filter_complex
    assert "1:a:0?" in command


def test_vertical_frame_uses_the_same_adjustable_filter() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        screen = root / "screen.mp4"
        professor = root / "professor.mp4"
        screen.touch()
        professor.touch()
        completed = SimpleNamespace(returncode=0, stderr=b"", stdout=b"jpeg")
        with patch("trade_cutter.ffmpeg.find_ffmpeg", return_value="ffmpeg"), patch(
            "trade_cutter.ffmpeg.subprocess.run", return_value=completed
        ) as run:
            result = capture_vertical_frame(
                screen,
                professor,
                operation(crop_area="profit_index"),
                professor_zoom=1.2,
                graph_zoom=1.4,
            )
        command = run.call_args.args[0]
        filter_complex = command[command.index("-filter_complex") + 1]
        assert result == b"jpeg"
        assert "scale=1296:1152" in filter_complex
        assert "scale=1512:1344" in filter_complex
        assert "image2pipe" in command


def test_professor_vertical_fills_portrait_frame() -> None:
    command = rendered_command(
        operation(),
        output_format="professor_vertical",
        full_professor_zoom=1.3,
        full_professor_position_x=100,
        full_professor_position_y=-100,
    )
    filter_complex = command[command.index("-filter_complex") + 1]
    assert "[1:v]" in filter_complex
    assert "scale=1404:2496" in filter_complex
    assert "crop=1080:1920:(iw-ow)*1.000000:(ih-oh)*0.000000" in filter_complex
    assert "vstack" not in filter_complex


def test_professor_horizontal_uses_camera_only() -> None:
    command = rendered_command(operation(), output_format="professor_horizontal")
    filter_complex = command[command.index("-filter_complex") + 1]
    assert "[1:v]" in filter_complex
    assert "crop=1080:1920" not in filter_complex
    assert "vstack" not in filter_complex


def test_split_then_professor_switches_inside_one_file() -> None:
    op = operation(crop_area="profit_index")
    op.layout_mode = "split_then_professor"
    op.layout_switch_time = 15.0
    command = rendered_command(
        op,
        full_professor_zoom=1.2,
        full_professor_position_x=-100,
    )
    filter_complex = command[command.index("-filter_complex") + 1]
    assert "vstack=inputs=2" in filter_complex
    assert "split=2" in filter_complex
    assert "crop=1080:1920" in filter_complex
    assert "enable='gte(t,5.000)'" in filter_complex
    assert command.count("-map") == 2


def test_professor_frame_uses_full_portrait_filter() -> None:
    with TemporaryDirectory() as temporary:
        professor = Path(temporary) / "professor.mp4"
        professor.touch()
        completed = SimpleNamespace(returncode=0, stderr=b"", stdout=b"jpeg")
        with patch("trade_cutter.ffmpeg.find_ffmpeg", return_value="ffmpeg"), patch(
            "trade_cutter.ffmpeg.subprocess.run", return_value=completed
        ) as run:
            result = capture_professor_frame(
                professor,
                12.0,
                zoom=1.25,
                position_x=50,
                position_y=-50,
            )
        command = run.call_args.args[0]
        video_filter = command[command.index("-vf") + 1]
        assert result == b"jpeg"
        assert "scale=1350:2400" in video_filter
        assert "crop=1080:1920" in video_filter


def test_lightweight_preview_is_scaled_and_cached() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "screen.mp4"
        source.write_bytes(b"source")
        cache = root / "cache"

        def create_output(command, **_kwargs):
            Path(command[-1]).write_bytes(b"preview")
            return SimpleNamespace(returncode=0, stderr="")

        with patch("trade_cutter.ffmpeg.find_ffmpeg", return_value="ffmpeg"), patch(
            "trade_cutter.ffmpeg.subprocess.run", side_effect=create_output
        ) as run:
            first = create_preview_clip(source, 10.0, 45.0, cache_dir=cache)
            second = create_preview_clip(source, 10.0, 45.0, cache_dir=cache)

        command = run.call_args.args[0]
        assert first == second
        assert first.read_bytes() == b"preview"
        assert run.call_count == 1
        assert command[command.index("-vf") + 1].startswith("scale=1280:")
        assert "setpts=PTS-STARTPTS" in command[command.index("-vf") + 1]
        assert command[command.index("-map") + 3] == "0:a:0?"
        assert command[command.index("-af") + 1] == "aresample=async=1:first_pts=0"
        assert command[command.index("-avoid_negative_ts") + 1] == "make_zero"
        assert command[command.index("-t") + 1] == "35.000"
        assert str(source) in command


def test_scene_filters_support_every_composition_and_orientation() -> None:
    op = operation(crop_area="profit_index")
    scene = Scene("s1", 10.0, 15.0, "professor_top", professor_zoom=1.2, graph_zoom=1.4)
    portrait = scene_filter(op, scene, "vertical")
    assert "vstack=inputs=2" in portrait
    assert "[professor][graph]" in portrait
    assert "crop=1080:960" in portrait
    assert "fps=30" in portrait

    scene.layout = "graph_top"
    assert "[graph][professor]vstack" in scene_filter(op, scene, "horizontal")
    scene.layout = "side_by_side"
    landscape = scene_filter(op, scene, "horizontal")
    assert "hstack=inputs=2" in landscape
    assert "crop=960:1080" in landscape
    scene.layout = "graph_full"
    assert "crop=1920:1080" in scene_filter(op, scene, "horizontal")
    scene.layout = "professor_full"
    assert "[1:v]" in scene_filter(op, scene, "vertical")


def test_scene_graph_can_anchor_the_crop_to_the_right_edge() -> None:
    op = operation(crop_area="profit_index")
    scene = Scene(
        "s1",
        10.0,
        15.0,
        "professor_top",
        graph_zoom=1.5,
        graph_alignment="right",
    )
    aligned_right = scene_filter(op, scene, "vertical")
    assert aligned_right.count("(iw-ow)*1.000000") == 1

    scene.graph_x = -20
    adjusted = scene_filter(op, scene, "vertical")
    assert "(iw-ow)*0.900000" in adjusted


def test_scene_speed_mute_and_low_memory_render_options() -> None:
    scene = Scene(
        "fast",
        10.0,
        20.0,
        "graph_full",
        playback_speed=10.0,
        audio_mode="mute",
        subtitles_enabled=False,
    )
    command = rendered_scene_command(scene)
    filter_complex = command[command.index("-filter_complex") + 1]
    assert "setpts=(PTS-STARTPTS)/10.000000" in filter_complex
    assert "anullsrc=channel_layout=stereo:sample_rate=48000" in filter_complex
    assert command[command.index("-t") + 1] == "1.000"
    assert command[command.index("-filter_complex_threads") + 1] == "1"
    assert command[command.index("-threads:v") + 1] == "2"
    assert command[command.index("-map") + 3] == "[a]"


def test_scene_audio_source_and_speed_are_applied_together() -> None:
    scene = Scene(
        "fast-audio",
        10.0,
        20.0,
        "professor_full",
        playback_speed=5.0,
        audio_mode="screen",
    )
    command = rendered_scene_command(scene)
    filter_complex = command[command.index("-filter_complex") + 1]
    assert "[0:a:0]aresample=" in filter_complex
    assert filter_complex.count("atempo=2.000000") == 2
    assert "atempo=1.250000" in filter_complex
    assert command[command.index("-t") + 1] == "2.000"


def test_scene_ass_filters_speaker_and_retimes_for_speed() -> None:
    scene = Scene(
        "captioned",
        10.0,
        20.0,
        "professor_top",
        playback_speed=2.0,
    )
    captions = build_scene_ass(
        [
            Cue(1, 11.0, 13.0, "PROFESSOR", "Vamos observar o gráfico."),
            Cue(2, 12.0, 14.0, "ALUNO", "Conversa paralela."),
        ],
        scene,
        "vertical",
        speaker="PROFESSOR",
    )
    assert "0:00:00.50,0:00:01.50" in captions
    assert "Vamos observar o gráfico." in captions
    assert "Conversa paralela." not in captions
    assert "MarginL, MarginR, MarginV" in captions
    assert ",1040,1" in captions


def test_scene_ass_can_highlight_each_word_in_gold() -> None:
    scene = Scene("highlighted", 10.0, 20.0, "professor_top")
    captions = build_scene_ass(
        [Cue(1, 11.0, 14.0, "PROFESSOR", "Um eu tu")],
        scene,
        "vertical",
        speaker="PROFESSOR",
        subtitle_style="highlight",
    )

    assert captions.count("Dialogue:") == 3
    assert "0:00:01.00,0:00:02.00" in captions
    assert "0:00:02.00,0:00:03.00" in captions
    assert "0:00:03.00,0:00:04.00" in captions
    assert r"{\c&H0023A6F5&\3c&H00040608&\bord3}" in captions
    assert "&H00DDEBF3" in captions


def test_scene_frame_uses_scene_specific_framing() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        screen = root / "screen.mp4"
        professor = root / "professor.mp4"
        screen.touch()
        professor.touch()
        scene = Scene(
            "s1", 12.0, 18.0, "side_by_side",
            professor_zoom=1.25, professor_x=100,
            graph_zoom=1.5, graph_y=-100,
        )
        completed = SimpleNamespace(returncode=0, stderr=b"", stdout=b"jpeg")
        with patch("trade_cutter.ffmpeg.find_ffmpeg", return_value="ffmpeg"), patch(
            "trade_cutter.ffmpeg.subprocess.run", return_value=completed
        ) as run:
            result = capture_scene_frame(
                screen, professor, operation(), scene, orientation="horizontal"
            )
        command = run.call_args.args[0]
        filter_complex = command[command.index("-filter_complex") + 1]
        assert result == b"jpeg"
        assert "hstack=inputs=2" in filter_complex
        assert "scale=1200:1350" in filter_complex
        assert "scale=1440:1620" in filter_complex


def test_scene_timeline_requires_complete_coverage() -> None:
    op = operation()
    op.scenes = [
        Scene("s1", 10.0, 15.0, "graph_full"),
        Scene("s2", 15.0, 20.0, "professor_full"),
    ]
    assert len(validate_scene_timeline(op)) == 2
    op.scenes[1].start = 16.0
    try:
        validate_scene_timeline(op)
    except ValueError as error:
        assert "espaço ou sobreposição" in str(error)
    else:
        raise AssertionError("Uma linha do tempo com buraco deveria ser rejeitada.")


def test_exact_cut_bounds_trim_previous_scenes() -> None:
    op = operation()
    op.scenes = [
        Scene("context", 10.0, 15.0, "graph_full"),
        Scene("main", 15.0, 20.0, "professor_full", professor_zoom=1.3),
    ]
    op.set_cut_bounds(15.0, 19.0)
    assert op.cut_start == 15.0
    assert op.cut_end == 19.0
    assert len(op.scenes) == 1
    assert op.scenes[0].id == "main"
    assert op.scenes[0].start == 15.0
    assert op.scenes[0].end == 19.0
    assert op.scenes[0].professor_zoom == 1.3
    assert validate_scene_timeline(op) == op.scenes


def test_final_export_respects_order_and_creates_one_concat() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        screen = root / "screen.mp4"
        professor = root / "professor.mp4"
        screen.touch()
        professor.touch()
        first = operation()
        first.id = "first"
        first.title = "Primeiro"
        first.sequence_order = 2
        first.scenes = [Scene("first-scene", 10.0, 20.0, "graph_full")]
        second = operation()
        second.id = "second"
        second.title = "Segundo"
        second.sequence_order = 1
        second.scenes = [
            Scene("removed-scene", 10.0, 15.0, "graph_full", skip=True),
            Scene("second-scene", 15.0, 20.0, "professor_full"),
        ]
        rendered: list[str] = []

        def fake_render(_screen, _professor, op, scene, target, **_kwargs):
            rendered.append(f"{op.id}:{scene.id}")
            Path(target).touch()
            return Path(target)

        completed = SimpleNamespace(returncode=0, stderr="")
        with patch("trade_cutter.ffmpeg.find_ffmpeg", return_value="ffmpeg"), patch(
            "trade_cutter.ffmpeg.render_scene_video", side_effect=fake_render
        ), patch("trade_cutter.ffmpeg.subprocess.run", return_value=completed) as run:
            target = export_final_video(
                screen, professor, [first, second], root / "final.mp4"
            )
        assert target == root / "final.mp4"
        assert rendered == ["second:second-scene", "first:first-scene"]
        concat_command = run.call_args.args[0]
        assert concat_command[concat_command.index("-f") + 1] == "concat"
        assert concat_command[-1] == str(target)
        assert (root / "final.edit.json").exists()


def test_export_sidecars_retime_transcript_captions_and_edit_map() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        op = operation()
        op.cut_start = 10.0
        op.cut_end = 40.0
        op.scenes = [
            Scene(
                "spoken",
                10.0,
                20.0,
                "professor_top",
                playback_speed=2.0,
                audio_mode="professor",
            ),
            Scene(
                "fast",
                20.0,
                30.0,
                "graph_full",
                playback_speed=10.0,
                audio_mode="mute",
                subtitles_enabled=False,
            ),
            Scene("removed", 30.0, 40.0, "graph_full", skip=True),
        ]
        paths = write_export_sidecars(
            root / "video-final.mp4",
            [op],
            video_path=root / "screen.mp4",
            professor_video_path=root / "professor.mp4",
            cues=[
                Cue(1, 12.0, 14.0, "PROFESSOR", "Fala principal."),
                Cue(2, 22.0, 24.0, "ALUNO", "Conversa preservada."),
                Cue(3, 32.0, 34.0, "PROFESSOR", "Fala removida."),
            ],
            transcript_path=root / "source.vtt",
            orientation="vertical",
            project_audio="professor",
            professor_sync_offset=0.5,
            captions_enabled=False,
            caption_speaker="PROFESSOR",
        )

        transcript = paths["transcript"].read_text(encoding="utf-8")
        captions = paths["captions"].read_text(encoding="utf-8")
        edit_map = json.loads(paths["edit_map"].read_text(encoding="utf-8"))

        assert "00:00:01.000 --> 00:00:02.000" in transcript
        assert "PROFESSOR: Fala principal." in transcript
        assert "00:00:05.200 --> 00:00:05.400" in transcript
        assert "ALUNO: Conversa preservada." in transcript
        assert "Fala removida." not in transcript
        assert "00:00:01,000 --> 00:00:02,000" in captions
        assert "Fala principal." in captions
        assert "Conversa preservada." not in captions
        assert paths["captions"].name == "video-final.srt"
        assert edit_map["output_duration"] == 6.0
        assert edit_map["segments"][1]["audio"] == "mute"
        assert edit_map["segments"][1]["source"]["screen_start"] == 20.0
        assert edit_map["segments"][1]["output"]["start"] == 5.0
        assert edit_map["segments"][2]["skipped"] is True
        assert edit_map["segments"][2]["output"]["duration"] == 0.0


def main() -> None:
    test_full_fast_cut_keeps_copy_mode()
    test_area_cut_forces_crop_and_reencode()
    test_vertical_cut_stacks_professor_and_graph()
    test_vertical_frame_uses_the_same_adjustable_filter()
    test_professor_vertical_fills_portrait_frame()
    test_professor_horizontal_uses_camera_only()
    test_split_then_professor_switches_inside_one_file()
    test_professor_frame_uses_full_portrait_filter()
    test_lightweight_preview_is_scaled_and_cached()
    test_scene_filters_support_every_composition_and_orientation()
    test_scene_graph_can_anchor_the_crop_to_the_right_edge()
    test_scene_speed_mute_and_low_memory_render_options()
    test_scene_audio_source_and_speed_are_applied_together()
    test_scene_ass_filters_speaker_and_retimes_for_speed()
    test_scene_ass_can_highlight_each_word_in_gold()
    test_scene_frame_uses_scene_specific_framing()
    test_scene_timeline_requires_complete_coverage()
    test_exact_cut_bounds_trim_previous_scenes()
    test_final_export_respects_order_and_creates_one_concat()
    test_export_sidecars_retime_transcript_captions_and_edit_map()
    print("OK: cortes, cinco composições, duas orientações e montagem final.")


if __name__ == "__main__":
    main()
