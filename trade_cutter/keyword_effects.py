from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


EFFECT_LABELS = {
    "none": "Nenhum",
    "shake": "Tremor curto",
    "flash": "Flash dourado",
    "shake_text": "Tremor + texto",
}
LABEL_TO_EFFECT = {label: key for key, label in EFFECT_LABELS.items()}


@dataclass(frozen=True, slots=True)
class KeywordRule:
    id: str
    expression: str
    keep_normal: bool = True
    effect: str = "none"
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_keyword_rules() -> list[KeywordRule]:
    return [
        KeywordRule("scene-stop", "stop"),
        KeywordRule("scene-lote", "lote"),
        KeywordRule("scene-parcial", "parcial"),
        KeywordRule("scene-alvo", "alvo"),
        KeywordRule("scene-porcento", "porcento"),
        KeywordRule("scene-gain", "gain"),
        KeywordRule("scene-delicia", "delícia", effect="shake_text"),
    ]


def validate_keyword_rules(rules: list[KeywordRule]) -> None:
    if not rules:
        raise ValueError("A lista de palavras de 1x não pode ficar vazia.")
    identifiers: set[str] = set()
    for position, rule in enumerate(rules, 1):
        if not rule.expression.strip():
            raise ValueError(f"Palavra {position}: informe uma palavra ou frase.")
        if rule.effect not in EFFECT_LABELS:
            raise ValueError(f"Palavra {position}: efeito inválido.")
        if rule.id in identifiers:
            raise ValueError(f"ID de palavra repetido: {rule.id}")
        identifiers.add(rule.id)


def keyword_rules_from_records(records: list[dict[str, Any]]) -> list[KeywordRule]:
    rules: list[KeywordRule] = []
    for position, record in enumerate(records, 1):
        expression = _clean_text(record.get("Palavra ou frase", ""))
        rule_id = _clean_text(record.get("ID", ""))
        if not rule_id:
            digest = hashlib.sha1(
                f"{expression}-{position}".encode("utf-8")
            ).hexdigest()[:10]
            rule_id = f"scene-user-{digest}"
        effect_label = _clean_text(record.get("Efeito", EFFECT_LABELS["none"]))
        effect = LABEL_TO_EFFECT.get(effect_label, effect_label)
        keep_normal = bool(record.get("Manter em 1x", True))
        if effect != "none":
            keep_normal = True
        rules.append(
            KeywordRule(
                id=rule_id,
                expression=expression,
                keep_normal=keep_normal,
                effect=effect,
                enabled=bool(record.get("Ativa", True)),
            )
        )
    validate_keyword_rules(rules)
    return rules


def keyword_rule_records(rules: list[KeywordRule]) -> list[dict[str, Any]]:
    return [
        {
            "Ativa": rule.enabled,
            "Palavra ou frase": rule.expression,
            "Manter em 1x": rule.keep_normal,
            "Efeito": EFFECT_LABELS[rule.effect],
            "ID": rule.id,
        }
        for rule in rules
    ]


def load_keyword_rules(path: str | Path = "scene_keyword_rules.json") -> list[KeywordRule]:
    source = Path(path)
    if not source.exists():
        return default_keyword_rules()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Não foi possível ler as palavras de 1x: {error}") from error
    raw = payload.get("rules", []) if isinstance(payload, dict) else []
    rules = [
        KeywordRule(
            id=str(item.get("id", "")),
            expression=str(item.get("expression", "")),
            keep_normal=bool(item.get("keep_normal", True)),
            effect=str(item.get("effect", "none")),
            enabled=bool(item.get("enabled", True)),
        )
        for item in raw
        if isinstance(item, dict)
    ]
    validate_keyword_rules(rules)
    return rules


def save_keyword_rules(
    rules: list[KeywordRule],
    path: str | Path = "scene_keyword_rules.json",
) -> Path:
    validate_keyword_rules(rules)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "rules": [rule.to_dict() for rule in rules]}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if value != value:
            return ""
    except TypeError:
        pass
    return str(value).strip()
