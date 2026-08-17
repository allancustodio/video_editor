from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trade_cutter.timecode import (
    clock_time_to_video_time,
    normalize_timecode,
    parse_clock_time,
    parse_timecode,
)


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

    assert parse_clock_time("14:32:10") == 14 * 3600 + 32 * 60 + 10
    assert clock_time_to_video_time(
        parse_clock_time("14:45:20"),
        parse_clock_time("14:32:10"),
        parse_timecode("00:01:42"),
    ) == parse_timecode("00:14:52")
    assert clock_time_to_video_time(
        parse_clock_time("14:31:00"),
        parse_clock_time("14:32:10"),
        parse_timecode("00:01:42"),
    ) == parse_timecode("00:00:32")

    for invalid_clock in ("24:00:00", "12:60:00", "12:00:60", "12:30"):
        try:
            parse_clock_time(invalid_clock)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Horário de relógio inválido aceito: {invalid_clock}")

    try:
        clock_time_to_video_time(
            parse_clock_time("14:00:00"),
            parse_clock_time("14:32:10"),
            parse_timecode("00:01:42"),
        )
    except ValueError as error:
        assert "antes do início" in str(error)
    else:
        raise AssertionError("Horário anterior à gravação deveria ser rejeitado.")

    try:
        parse_timecode("horário errado")
    except ValueError as error:
        assert "Use" in str(error)
    else:
        raise AssertionError("Texto arbitrário deveria ser rejeitado.")

    print("OK: horários incompletos são completados e normalizados.")


if __name__ == "__main__":
    main()
