from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path
import sys

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trade_cutter.cards import format_trade_points, render_trade_card


def main() -> None:
    assert format_trade_points(1200) == "+1.200"
    assert format_trade_points(-350) == "-350"
    assert format_trade_points(0) == "0"

    opening = render_trade_card("opening", date(2026, 8, 17), 1200)
    closing = render_trade_card("closing", date(2026, 8, 17), 1200)
    assert opening.startswith(b"\x89PNG")
    assert closing.startswith(b"\x89PNG")
    assert opening != closing

    with Image.open(BytesIO(opening)) as image:
        assert image.size == (1080, 1920)
        assert image.mode == "RGB"
    with Image.open(BytesIO(closing)) as image:
        assert image.size == (1080, 1920)
        assert image.mode == "RGB"

    print("OK: capa e encerramento gerados em 1080x1920 com data e pontos.")


if __name__ == "__main__":
    main()
