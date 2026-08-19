from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from trade_cutter.polls import (
    discover_zoom_poll_files,
    parse_zoom_poll_csv,
    render_poll_card,
)


POLL_CSV = """Meeting Topic,ID,Start Time,
Sala GL,87882968083,2026-08-19 08:45:48,
Polling Name :Como foi seu dia ?
Question,Answer,% of Votes,Choice Type,
Como foi seu dia hoje ?,Gain,76%,Single Choice
Como foi seu dia hoje ?,Loss,18%,Single Choice
Como foi seu dia hoje ?,Simulador,6%,Single Choice
"""


def test_optional_discovery_parser_and_branded_card() -> None:
    with TemporaryDirectory(dir=Path.cwd()) as temporary:
        root = Path(temporary)
        video = root / "GMT20260819-115625_Recording_3840x1080.mp4"
        video.write_bytes(b"")
        assert discover_zoom_poll_files(video) == []

        source = root / "GMT20260819-115625_Recording_3840x1080_test.poll.csv"
        source.write_text(POLL_CSV, encoding="utf-8")
        discovered = discover_zoom_poll_files(video)
        polls = parse_zoom_poll_csv(source)

    assert discovered == [source.resolve()]
    assert len(polls) == 1
    poll = polls[0]
    assert poll.meeting_topic == "Sala GL"
    assert poll.polling_name == "Como foi seu dia ?"
    assert poll.question == "Como foi seu dia hoje ?"
    assert poll.poll_date.isoformat() == "2026-08-19"
    assert [(item.label, item.percentage) for item in poll.answers] == [
        ("Gain", 76.0),
        ("Loss", 18.0),
        ("Simulador", 6.0),
    ]

    content = render_poll_card(poll)
    with Image.open(BytesIO(content)) as image:
        assert image.size == (1080, 1920)
        assert image.format == "PNG"


def main() -> None:
    test_optional_discovery_parser_and_branded_card()
    print("OK: CSV opcional de enquete e arte dourada em 1080x1920.")


if __name__ == "__main__":
    main()
