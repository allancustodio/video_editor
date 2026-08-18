from __future__ import annotations

import subprocess
from datetime import date
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from trade_cutter.social_proof import (
    analyze_zoom_chat,
    default_social_proof_config,
    feedback_rule_records,
    feedback_rules_from_records,
    infer_chat_date,
    estimate_feedback_video_duration,
    parse_zoom_chat,
    feedback_page_occupancy,
    plan_feedback_pages,
    render_feedback_panels,
    render_feedback_video,
    render_individual_feedback,
    render_safe_area_preview,
    save_social_proof_config,
    load_social_proof_config,
    staff_from_records,
    staff_records,
)


CHAT = """00:01:00\tRafael Fossalussa:\tBati a meta
00:02:00\tRafael Bettiol:\tBati a meta
00:02:04\tRafael Bettiol:\tObrigado Rafa pela call
00:02:05\tAluno Dois:\tReacted to "Bati a meta" with 👏
00:03:00\tRafael Souza:\tMeta batida
00:04:00\tPaula Montibeller:\tMeta batidíssima,
já recuperando o stop!
00:06:00\tAluno Três:\tReplying to "Bati a meta"

Excelente dia, valeu!
"""


def _write_sample_chat(directory: str | Path) -> Path:
    source = Path(directory) / "GMT20260817-120000_RecordingnewChat.txt"
    source.write_text(CHAT, encoding="utf-8")
    return source


def test_parser_analysis_privacy_and_clock() -> None:
    with TemporaryDirectory(dir=Path.cwd()) as temporary:
        source = _write_sample_chat(temporary)
        messages = parse_zoom_chat(source)
        candidates = analyze_zoom_chat(source, default_social_proof_config())

    assert len(messages) == 7
    assert messages[3].kind == "reaction"
    assert messages[-1].kind == "reply"
    assert messages[-1].text == "Excelente dia, valeu!"
    assert all(item.author != "Rafael Fossalussa" for item in candidates)
    rafael = next(item for item in candidates if item.author == "Rafael Bettiol")
    assert rafael.display_name == "Rafael"
    assert rafael.wall_time.strftime("%H:%M") == "09:01"
    assert rafael.score >= 10
    other_rafael = next(item for item in candidates if item.author == "Rafael Souza")
    assert other_rafael.display_name == "Rafael"
    assert other_rafael.avatar_color != rafael.avatar_color
    paula = next(item for item in candidates if item.author == "Paula Montibeller")
    assert "recuperando o stop" in paula.text
    assert paula.classification == "Forte"


def test_configuration_records_and_persistence() -> None:
    config = default_social_proof_config()
    config.staff = staff_from_records(staff_records(config.staff))
    config.rules = feedback_rules_from_records(feedback_rule_records(config.rules))
    with TemporaryDirectory(dir=Path.cwd()) as temporary:
        target = Path(temporary) / "social.json"
        save_social_proof_config(config, target)
        loaded = load_social_proof_config(target)
    assert loaded.to_dict() == config.to_dict()


def test_hybrid_panels_and_individual_are_vertical_pngs() -> None:
    with TemporaryDirectory(dir=Path.cwd()) as temporary:
        source = _write_sample_chat(temporary)
        candidates = analyze_zoom_chat(source, default_social_proof_config())
        selected = [item for item in candidates if item.classification == "Forte"]
        panels = render_feedback_panels(selected, infer_chat_date(source))
        individual = render_individual_feedback(selected[0], date(2026, 8, 17))
        planned = plan_feedback_pages(selected)

    assert panels
    assert all(len(page) <= 8 for page in planned)
    assert all(feedback_page_occupancy(page) <= 1.0 for page in planned)
    for content in (*panels, individual):
        with Image.open(BytesIO(content)) as image:
            assert image.size == (1080, 1920)
            assert image.format == "PNG"
    safe_preview = render_safe_area_preview(panels[0])
    assert safe_preview != panels[0]
    with Image.open(BytesIO(safe_preview)) as image:
        assert image.size == (1080, 1920)


def test_manual_page_sizes_are_respected_and_validated() -> None:
    with TemporaryDirectory(dir=Path.cwd()) as temporary:
        source = _write_sample_chat(temporary)
        selected = [
            item
            for item in analyze_zoom_chat(source, default_social_proof_config())
            if item.classification == "Forte"
        ][:3]
    pages = plan_feedback_pages(selected, page_sizes=[2, 1])
    assert [len(page) for page in pages] == [2, 1]
    try:
        plan_feedback_pages(selected, page_sizes=[2])
    except ValueError as error:
        assert "soma 2" in str(error)
    else:
        raise AssertionError("Uma distribuição incompleta deveria ser rejeitada.")


def test_animated_video_uses_cumulative_frames_and_ffmpeg_pop() -> None:
    with TemporaryDirectory(dir=Path.cwd()) as chat_temporary:
        source = _write_sample_chat(chat_temporary)
        selected = [
            item
            for item in analyze_zoom_chat(source, default_social_proof_config())
            if item.classification == "Forte"
        ][:2]
    duration = estimate_feedback_video_duration(
        selected,
        page_sizes=[2],
        comment_interval=0.5,
        page_pause=0.6,
        final_hold=0.7,
    )
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        Path(command[-1]).write_bytes(b"fake mp4")
        return subprocess.CompletedProcess(command, 0, "", "")

    with TemporaryDirectory(dir=Path.cwd()) as temporary:
        target = Path(temporary) / "prova-social.mp4"
        with patch(
            "trade_cutter.social_proof.find_ffmpeg", return_value="ffmpeg"
        ), patch("trade_cutter.social_proof.subprocess.run", side_effect=fake_run):
            result = render_feedback_video(
                selected,
                date(2026, 8, 17),
                target,
                page_sizes=[2],
                comment_interval=0.5,
                page_pause=0.6,
                final_hold=0.7,
                notification_sound=True,
                notification_volume=0.25,
            )
        assert target.exists()

    assert round(duration, 3) == 1.7
    assert result.duration == duration
    assert result.comment_count == 2
    assert result.page_count == 1
    command = commands[0]
    assert command.count("sine=frequency=1040:sample_rate=48000:duration=0.160") == 2
    assert "-filter_complex" in command
    assert "amix=inputs=2" in command[command.index("-filter_complex") + 1]
    assert "fps=30,format=yuv420p" in command


def main() -> None:
    test_parser_analysis_privacy_and_clock()
    test_configuration_records_and_persistence()
    test_hybrid_panels_and_individual_are_vertical_pngs()
    test_manual_page_sizes_are_respected_and_validated()
    test_animated_video_uses_cumulative_frames_and_ffmpeg_pop()
    print("OK: análise local e painéis híbridos do chat do Zoom")


if __name__ == "__main__":
    main()
