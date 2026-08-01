from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


RULE_CATEGORIES = ("setup", "entry", "outcome", "negation")
RULE_MODES = ("literal", "regex")


@dataclass(slots=True)
class RuleDefinition:
    id: str
    category: str
    expression: str
    strength: float = 1.0
    label: str = ""
    enabled: bool = True
    mode: str = "literal"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CompiledDetectionRules:
    setup: list[tuple[re.Pattern[str], float]]
    entry: list[tuple[re.Pattern[str], float]]
    outcome: list[tuple[re.Pattern[str], str, float]]
    negation: list[re.Pattern[str]]


def default_rules() -> list[RuleDefinition]:
    raw = [
        ("entry-explicit", "entry", r"\b(comprei|vendi|entrei)\b", 1.00, ""),
        ("entry-position", "entry", r"\b(ja )?estou (comprado|vendido)\b", 0.95, ""),
        ("entry-triggered", "entry", r"\bacionou( e pagou)?\b", 0.84, ""),
        ("entry-order", "entry", r"\bpegou (a )?(ordem|entrada)\b", 0.80, ""),
        ("entry-activated", "entry", r"\bativou\b", 0.75, ""),
        ("setup-i-will", "setup", r"\beu vou (comprar|vender)\b", 0.85, ""),
        ("setup-we-will", "setup", r"\b(vou|vamos) (comprar|vender)\b", 0.76, ""),
        ("setup-start", "setup", r"\bcomeca a (comprar|vender)\b", 0.70, ""),
        ("setup-scalp", "setup", r"\b(vamos|tentar) pegar um (scalp|scalpe)\b", 0.58, ""),
        ("setup-who-enters", "setup", r"\bquem for entrar\b", 0.42, ""),
        ("setup-entry-word", "setup", r"\bentrada\b", 0.35, ""),
        ("outcome-first-target", "outcome", r"\b(primeiro alvo|foi ali no alvo|bateu o alvo)\b", 0.65, "primeiro alvo"),
        ("outcome-second-target", "outcome", r"\bsegundo alvo\b", 0.75, "segundo alvo"),
        ("outcome-third-target", "outcome", r"\bterceiro alvo\b", 0.90, "terceiro alvo"),
        ("outcome-partial", "outcome", r"\b(parcial|parcela|parciais)\b", 0.52, "parcial"),
        ("outcome-paid", "outcome", r"\bpagou\b", 0.62, "pagou"),
        ("outcome-stop", "outcome", r"\b(estopou|tomou um stop|pegou o stop)\b", 0.78, "stop"),
        ("outcome-closed", "outcome", r"\bzerei\b", 0.82, "zerou"),
        ("outcome-risk", "outcome", r"\b(tirei|tirar|retirei) (o )?risco\b", 0.72, "risco retirado"),
        ("outcome-breakeven", "outcome", r"\bbreakeven\b", 0.60, "breakeven"),
        ("outcome-exited", "outcome", r"\bme tirou aqui\b", 0.75, "encerrada"),
        ("negation-did-not", "negation", r"\bnao (entrei|comprei|vendi|vou comprar|vou vender|acionou)\b", 1.0, ""),
        ("negation-will-not", "negation", r"\bnao vou (comprar|vender)\b", 1.0, ""),
        ("negation-if-trigger", "negation", r"\bse (ele )?acionar\b", 1.0, ""),
        ("negation-if-arrives", "negation", r"\bse chegar.*\b(compro|vendo|comprar|vender)\b", 1.0, ""),
        ("negation-not-trading", "negation", r"\bnao (to|estou) (nem )?operando\b", 1.0, ""),
    ]
    return [
        RuleDefinition(
            id=rule_id,
            category=category,
            expression=expression,
            strength=strength,
            label=label,
            enabled=True,
            mode="regex",
        )
        for rule_id, category, expression, strength, label in raw
    ]


def compile_rules(rules: list[RuleDefinition]) -> CompiledDetectionRules:
    validate_rules(rules)
    setup: list[tuple[re.Pattern[str], float]] = []
    entry: list[tuple[re.Pattern[str], float]] = []
    outcome: list[tuple[re.Pattern[str], str, float]] = []
    negation: list[re.Pattern[str]] = []
    for rule in rules:
        if not rule.enabled:
            continue
        pattern = _compile_expression(rule)
        if rule.category == "setup":
            setup.append((pattern, rule.strength))
        elif rule.category == "entry":
            entry.append((pattern, rule.strength))
        elif rule.category == "outcome":
            outcome.append((pattern, rule.label, rule.strength))
        elif rule.category == "negation":
            negation.append(pattern)
    return CompiledDetectionRules(setup=setup, entry=entry, outcome=outcome, negation=negation)


def validate_rules(rules: list[RuleDefinition]) -> None:
    if not rules:
        raise ValueError("A lista de regras não pode ficar vazia.")
    identifiers: set[str] = set()
    for position, rule in enumerate(rules, 1):
        if rule.category not in RULE_CATEGORIES:
            raise ValueError(f"Regra {position}: categoria inválida.")
        if rule.mode not in RULE_MODES:
            raise ValueError(f"Regra {position}: tipo inválido.")
        if not rule.expression.strip():
            raise ValueError(f"Regra {position}: informe uma expressão.")
        if not 0.0 <= rule.strength <= 1.0:
            raise ValueError(f"Regra {position}: o peso deve ficar entre 0 e 1.")
        if rule.category == "outcome" and not rule.label.strip():
            raise ValueError(f"Regra {position}: informe o resultado.")
        if rule.id in identifiers:
            raise ValueError(f"ID de regra repetido: {rule.id}")
        identifiers.add(rule.id)
        _compile_expression(rule)


def rules_from_records(records: list[dict[str, Any]]) -> list[RuleDefinition]:
    values: list[RuleDefinition] = []
    for position, record in enumerate(records, 1):
        category = _clean_text(record.get("Categoria", "")).lower()
        expression = _clean_text(record.get("Expressão", ""))
        mode = _clean_text(record.get("Tipo", "literal")).lower()
        label = _clean_text(record.get("Resultado", ""))
        rule_id = _clean_text(record.get("ID", ""))
        if not rule_id:
            digest = hashlib.sha1(
                f"{category}-{expression}-{position}".encode("utf-8")
            ).hexdigest()[:10]
            rule_id = f"user-{digest}"
        strength_value = record.get("Peso", 1.0)
        try:
            strength = float(strength_value)
        except (TypeError, ValueError):
            raise ValueError(f"Regra {position}: peso inválido.") from None
        values.append(
            RuleDefinition(
                id=rule_id,
                category=category,
                expression=expression,
                strength=strength,
                label=label,
                enabled=bool(record.get("Ativa", True)),
                mode=mode,
            )
        )
    validate_rules(values)
    return values


def load_rules(path: str | Path = "user_rules.json") -> list[RuleDefinition]:
    source = Path(path)
    if not source.exists():
        return default_rules()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Não foi possível ler as regras: {error}") from error
    raw = payload.get("rules", []) if isinstance(payload, dict) else []
    rules = [
        RuleDefinition(
            id=str(item.get("id", "")),
            category=str(item.get("category", "")),
            expression=str(item.get("expression", "")),
            strength=float(item.get("strength", 1.0)),
            label=str(item.get("label", "")),
            enabled=bool(item.get("enabled", True)),
            mode=str(item.get("mode", "literal")),
        )
        for item in raw
        if isinstance(item, dict)
    ]
    validate_rules(rules)
    return rules


def save_rules(rules: list[RuleDefinition], path: str | Path = "user_rules.json") -> Path:
    validate_rules(rules)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "rules": [rule.to_dict() for rule in rules]}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _compile_expression(rule: RuleDefinition) -> re.Pattern[str]:
    expression = rule.expression.strip()
    if rule.mode == "literal":
        expression = _normalize(expression)
        expression = rf"(?<!\w){re.escape(expression)}(?!\w)"
    try:
        return re.compile(expression)
    except re.error as error:
        raise ValueError(f"Regex inválida na regra {rule.id}: {error}") from error


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", normalized).strip()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if value != value:
            return ""
    except TypeError:
        pass
    return str(value).strip()
