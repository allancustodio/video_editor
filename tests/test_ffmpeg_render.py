from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trade_cutter.ffmpeg import cut_video
from trade_cutter.models import Operation


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
    )
    filter_complex = command[command.index("-filter_complex") + 1]
    assert "crop=" in filter_complex
    assert "vstack=inputs=2" in filter_complex
    assert "scale=1080:960" in filter_complex
    assert "1:a?" in command


def main() -> None:
    test_full_fast_cut_keeps_copy_mode()
    test_area_cut_forces_crop_and_reencode()
    test_vertical_cut_stacks_professor_and_graph()
    print("OK: comandos de corte original, recorte de área e composição vertical.")


if __name__ == "__main__":
    main()
