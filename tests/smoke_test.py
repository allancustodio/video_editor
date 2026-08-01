from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trade_cutter.detector import DetectionConfig, detect_operations
from trade_cutter.export import load_operations, save_operations
from trade_cutter.models import Operation, Scene
from trade_cutter.vtt import parse_vtt


TRANSCRIPT = ROOT / "examples" / "GMT20260717-114920_Recording.transcript.vtt"


def main() -> None:
    cues = parse_vtt(TRANSCRIPT)
    operations = detect_operations(cues, DetectionConfig(target_speaker="RAFAEL FOSSALUSSA"))
    assert len(cues) > 1000
    assert len(operations) >= 6
    assert any(abs(item.entry_time - (40 * 60 + 16)) < 3 for item in operations)
    assert any(abs(item.entry_time - (68 * 60 + 1)) < 3 for item in operations)
    assert any(abs(item.entry_time - (2 * 3600 + 32 * 60 + 14)) < 3 for item in operations)

    legacy_payload = operations[0].to_dict()
    for key in ("crop_area", "crop_x", "crop_y", "crop_width", "crop_height"):
        legacy_payload.pop(key)
    legacy_operation = Operation.from_dict(legacy_payload)
    assert legacy_operation.crop_area == "full"
    assert legacy_operation.crop_width == 1.0

    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary) / "cuts.json"
        save_operations(target, operations, str(TRANSCRIPT))
        loaded = load_operations(target)
        assert len(loaded) == len(operations)
        assert loaded[0].crop_area == "full"

        operations[0].crop_area = "profit_dollar"
        operations[0].crop_x = 0.75
        operations[0].crop_width = 0.19
        operations[0].sequence_order = 3
        operations[0].output_orientation = "horizontal"
        operations[0].scenes = [
            Scene(
                "intro", operations[0].cut_start, operations[0].cut_end,
                "side_by_side", professor_zoom=1.25, graph_x=50,
                graph_alignment="right",
            )
        ]
        save_operations(target, operations, str(TRANSCRIPT))
        loaded = load_operations(target)
        assert loaded[0].crop_area == "profit_dollar"
        assert loaded[0].crop_x == 0.75
        assert loaded[0].crop_width == 0.19
        assert loaded[0].sequence_order == 3
        assert loaded[0].output_orientation == "horizontal"
        assert loaded[0].scenes[0].layout == "side_by_side"
        assert loaded[0].scenes[0].professor_zoom == 1.25
        assert loaded[0].scenes[0].graph_x == 50
        assert loaded[0].scenes[0].graph_alignment == "right"

    print(f"OK: {len(cues)} legendas e {len(operations)} candidatos.")


if __name__ == "__main__":
    main()
