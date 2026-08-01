from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trade_cutter.timecode import normalize_timecode, parse_timecode


def main() -> None:
    expected = {
        "02:30:": 2 * 3600 + 30 * 60,
        "02::": 2 * 3600,
        ":30:": 30 * 60,
        "::15": 15,
        "02:30": 2 * 60 + 30,
        "02:": 2 * 60,
        ":30": 30,
        "1:02:03.500": 3723.5,
    }
    for value, seconds in expected.items():
        assert parse_timecode(value) == seconds, value

    assert normalize_timecode("02:30:") == "02:30:00"
    assert normalize_timecode("02::") == "02:00:00"
    assert normalize_timecode(15) == "00:00:15"

    try:
        parse_timecode("horário errado")
    except ValueError as error:
        assert "Use" in str(error)
    else:
        raise AssertionError("Texto arbitrário deveria ser rejeitado.")

    print("OK: horários incompletos são completados e normalizados.")


if __name__ == "__main__":
    main()
