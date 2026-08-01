from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trade_cutter.detector import DetectionConfig, detect_operations
from trade_cutter.models import Cue
from trade_cutter.rules import (
    RuleDefinition,
    compile_rules,
    default_rules,
    load_rules,
    save_rules,
)


def main() -> None:
    rules = default_rules()
    compile_rules(rules)
    custom = rules + [
        RuleDefinition(
            id="user-mergulhei",
            category="entry",
            expression="mergulhei",
            strength=1.0,
            mode="literal",
        )
    ]
    cues = [
        Cue(1, 10.0, 12.0, "PROFESSOR", "Eu vou comprar esse trade."),
        Cue(2, 20.0, 22.0, "PROFESSOR", "Mergulhei com stop curto."),
        Cue(3, 30.0, 32.0, "PROFESSOR", "Zerei a posição."),
    ]
    operations = detect_operations(
        cues,
        DetectionConfig(target_speaker="PROFESSOR", minimum_confidence=0.0),
        rules=custom,
    )
    assert len(operations) == 1
    assert operations[0].entry_time == 20.0
    assert operations[0].setup_start == 10.0
    assert operations[0].cut_start == 10.0

    with TemporaryDirectory() as temporary:
        target = Path(temporary) / "rules.json"
        save_rules(custom, target)
        loaded = load_rules(target)
        assert loaded[-1].expression == "mergulhei"
        assert loaded[-1].mode == "literal"

    invalid = [
        RuleDefinition(
            id="invalid",
            category="entry",
            expression="(",
            mode="regex",
        )
    ]
    try:
        compile_rules(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("Uma regex inválida deveria ser rejeitada.")

    print("OK: regras padrão, regra literal, persistência e validação.")


if __name__ == "__main__":
    main()
