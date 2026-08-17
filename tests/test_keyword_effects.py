from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from trade_cutter.keyword_effects import (
    EFFECT_LABELS,
    default_keyword_rules,
    keyword_rule_records,
    keyword_rules_from_records,
    load_keyword_rules,
    save_keyword_rules,
)


def test_defaults_include_delicia_effect() -> None:
    rule = next(item for item in default_keyword_rules() if item.expression == "delícia")
    assert rule.keep_normal is True
    assert rule.effect == "shake_text"


def test_effect_forces_normal_speed_and_persists() -> None:
    records = keyword_rule_records(default_keyword_rules())
    records[-1]["Manter em 1x"] = False
    records[-1]["Efeito"] = EFFECT_LABELS["flash"]
    rules = keyword_rules_from_records(records)
    assert rules[-1].keep_normal is True

    with TemporaryDirectory(dir=Path.cwd()) as temporary:
        target = Path(temporary) / "keywords.json"
        save_keyword_rules(rules, target)
        loaded = load_keyword_rules(target)
    assert loaded == rules


def main() -> None:
    test_defaults_include_delicia_effect()
    test_effect_forces_normal_speed_and_persists()
    print("OK: editable keyword effects")


if __name__ == "__main__":
    main()
