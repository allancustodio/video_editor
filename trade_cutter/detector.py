from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from .models import Cue, Event, Operation


def normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.lower())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", normalized).strip()


@dataclass(slots=True)
class DetectionConfig:
    target_speaker: str = "RAFAEL FOSSALUSSA"
    seconds_before_setup: float = 10.0
    seconds_before_entry: float = 45.0
    seconds_after_result: float = 25.0
    setup_lookback: float = 240.0
    outcome_lookahead: float = 2100.0
    minimum_confidence: float = 0.50


ENTRY_PATTERNS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"\b(comprei|vendi|entrei)\b"), 1.00),
    (re.compile(r"\b(ja )?estou (comprado|vendido)\b"), 0.95),
    (re.compile(r"\bacionou( e pagou)?\b"), 0.84),
    (re.compile(r"\bpegou (a )?(ordem|entrada)\b"), 0.80),
    (re.compile(r"\bativou\b"), 0.75),
]

SETUP_PATTERNS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"\beu vou (comprar|vender)\b"), 0.85),
    (re.compile(r"\b(vou|vamos) (comprar|vender)\b"), 0.76),
    (re.compile(r"\bcomeca a (comprar|vender)\b"), 0.70),
    (re.compile(r"\b(vamos|tentar) pegar um (scalp|scalpe)\b"), 0.58),
    (re.compile(r"\bquem for entrar\b"), 0.42),
    (re.compile(r"\bentrada\b"), 0.35),
]

OUTCOME_PATTERNS: list[tuple[re.Pattern[str], str, float]] = [
    (re.compile(r"\b(primeiro alvo|foi ali no alvo|bateu o alvo)\b"), "primeiro alvo", 0.65),
    (re.compile(r"\bsegundo alvo\b"), "segundo alvo", 0.75),
    (re.compile(r"\bterceiro alvo\b"), "terceiro alvo", 0.90),
    (re.compile(r"\b(parcial|parcela|parciais)\b"), "parcial", 0.52),
    (re.compile(r"\bpagou\b"), "pagou", 0.62),
    (re.compile(r"\b(estopou|tomou um stop|pegou o stop)\b"), "stop", 0.78),
    (re.compile(r"\bzerei\b"), "zerou", 0.82),
    (re.compile(r"\b(tirei|tirar|retirei) (o )?risco\b"), "risco retirado", 0.72),
    (re.compile(r"\bbreakeven\b"), "breakeven", 0.60),
    (re.compile(r"\bme tirou aqui\b"), "encerrada", 0.75),
]

NEGATION_PATTERNS = [
    re.compile(r"\bnao (entrei|comprei|vendi|vou comprar|vou vender|acionou)\b"),
    re.compile(r"\bnao vou (comprar|vender)\b"),
    re.compile(r"\bse (ele )?acionar\b"),
    re.compile(r"\bse chegar.*\b(compro|vendo|comprar|vender)\b"),
    re.compile(r"\bnao (to|estou) (nem )?operando\b"),
]

DIRECTION_BUY = [
    re.compile(r"\b(comprei|comprado|comprinha|vou comprar|compra aqui|entrada de compra)\b"),
]
DIRECTION_SELL = [
    re.compile(r"\b(vendi|vendido|vou vender|venda aqui|entrada de venda|comeca a vender)\b"),
]

ASSETS: list[tuple[str, list[str]]] = [
    ("índice", ["indice", "win", "mini indice"]),
    ("dólar", ["dolar", "dolinha", "wdo", "mini dolar"]),
    ("Nasdaq", ["nasdaq", "nq"]),
    ("óleo", ["oleo", "oil", "zoio", "zoyo"]),
    ("S&P", ["s&p", "sp500", "es"]),
    ("Bitcoin", ["bitcoin", "btc"]),
]

TRADE_TERMS = re.compile(
    r"\b(stop|alvo|parcial|ordem|oco|contrato|trade|operacao|scalp|scalpe|"
    r"candle|kendo|indice|dolar|dolinha|nasdaq|mercado|gap|comprado|vendido|"
    r"rompimento|media|vwap|vap|profit)\b"
)

RETROSPECTIVE_PATTERNS = [
    re.compile(r"\beu entrei sem ordem\b"),
    re.compile(r"\bcomo eu estou (comprado|vendido)\b"),
    re.compile(r"\buma entrada .* eu entrei\b"),
    re.compile(r"\bentao eu entrei\b"),
    re.compile(r"\bcomprei aleatorio\b"),
]


def _speaker_matches(cue: Cue, target: str) -> bool:
    if not target.strip():
        return True
    return normalize(target) in normalize(cue.speaker)


def _is_negated(text: str) -> bool:
    return any(pattern.search(text) for pattern in NEGATION_PATTERNS)


def _direction(text: str) -> str:
    if any(pattern.search(text) for pattern in DIRECTION_BUY):
        return "compra"
    if any(pattern.search(text) for pattern in DIRECTION_SELL):
        return "venda"
    return ""


def _asset(text: str) -> str:
    for display, aliases in ASSETS:
        for alias in aliases:
            if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text):
                return display
    return ""


def classify_events(cues: list[Cue], config: DetectionConfig) -> list[Event]:
    events: list[Event] = []
    for position, cue in enumerate(cues):
        if not _speaker_matches(cue, config.target_speaker):
            continue
        text = normalize(cue.text)
        negated = _is_negated(text)
        direction = _direction(text)
        asset = _asset(text)
        nearby = " ".join(
            normalize(item.text)
            for item in cues[max(0, position - 8): min(len(cues), position + 9)]
            if abs(item.start - cue.start) <= 55 and _speaker_matches(item, config.target_speaker)
        )
        has_trade_context = bool(TRADE_TERMS.search(f"{text} {nearby}"))

        for pattern, strength in SETUP_PATTERNS:
            if pattern.search(text) and not negated:
                events.append(Event(cue.index, cue.start, "setup", cue.text, cue.speaker, direction, asset, strength))
                break

        for pattern, strength in ENTRY_PATTERNS:
            if not pattern.search(text):
                continue
            adjusted = strength
            if negated:
                adjusted = 0.0
            if re.search(r"\b(comprei|vendi|entrei)\b", text) and not has_trade_context:
                adjusted = 0.0
            if "alguem" in text or "quem entrou" in text or "pessoal que entrou" in text:
                adjusted *= 0.35
            if "nao deu nem tempo" in text:
                adjusted *= 0.35
            if "acionou" in text and "pagou" not in text and not direction:
                if "padraozinho" in text or "de novo" in text:
                    adjusted = min(adjusted, 0.45)
                elif not has_trade_context:
                    adjusted = min(adjusted, 0.52)
            if adjusted > 0:
                events.append(Event(cue.index, cue.start, "entry", cue.text, cue.speaker, direction, asset, adjusted))
            break

        for pattern, label, strength in OUTCOME_PATTERNS:
            if pattern.search(text):
                events.append(Event(cue.index, cue.start, f"outcome:{label}", cue.text, cue.speaker, direction, asset, strength))
                break
    return sorted(events, key=lambda event: (event.time, event.cue_index, event.kind))


def _context_text(cues: list[Cue], start: float, end: float, target: str = "") -> str:
    values: list[str] = []
    for cue in cues:
        if cue.end < start or cue.start > end:
            continue
        if target and not _speaker_matches(cue, target):
            continue
        values.append(normalize(cue.text))
    return " ".join(values)


def _infer_direction(cues: list[Cue], event: Event, setup: Event | None, target: str) -> str:
    if event.direction:
        return event.direction
    nearby = [
        cue for cue in cues
        if event.time - 35 <= cue.start <= event.time + 90 and (not target or _speaker_matches(cue, target))
    ]
    nearby.sort(key=lambda cue: abs(cue.start - event.time))
    for cue in nearby:
        text = normalize(cue.text)
        if _is_negated(text):
            continue
        found = _direction(text)
        if found and (cue.start <= event.time + 20 or re.search(r"\b(stop|ordem|entrada)\b", text)):
            return found
    if setup and setup.direction:
        return setup.direction
    return ""


def _infer_asset(cues: list[Cue], event: Event, setup: Event | None, target: str) -> str:
    if event.asset:
        return event.asset
    if setup and setup.asset:
        return setup.asset
    nearby = [
        cue for cue in cues
        if event.time - 75 <= cue.start <= event.time + 75 and (not target or _speaker_matches(cue, target))
    ]
    nearby.sort(key=lambda cue: abs(cue.start - event.time))
    for cue in nearby:
        text = normalize(cue.text)
        if _is_negated(text):
            continue
        found = _asset(text)
        if found and TRADE_TERMS.search(text) and re.search(r"\b(stop|alvo|ordem|scalp|entrada|compra|venda|operar|rompimento)\b", text):
            return found
    return ""


def _is_retrospective(event: Event) -> bool:
    text = normalize(event.text)
    return any(pattern.search(text) for pattern in RETROSPECTIVE_PATTERNS)


def _prune_retrospective_entries(entries: list[Event], setups: list[Event], max_gap: float) -> list[Event]:
    accepted: list[Event] = []
    for entry in entries:
        if accepted and _is_retrospective(entry):
            previous = accepted[-1]
            if entry.time - previous.time <= max_gap:
                explicit_setups = [setup for setup in setups if previous.time + 60 < setup.time < entry.time and setup.strength >= 0.65]
                if not explicit_setups:
                    continue
        accepted.append(entry)
    return accepted


def _near_duplicate(previous: Operation, entry_time: float, direction: str, asset: str) -> bool:
    gap = abs(previous.entry_time - entry_time)
    direction_matches = not direction or not previous.direction or direction == previous.direction
    if gap <= 45 and direction_matches:
        return True
    if gap > 150:
        return False
    asset_matches = not asset or not previous.asset or asset == previous.asset
    return direction_matches and asset_matches


def detect_operations(cues: list[Cue], config: DetectionConfig | None = None) -> list[Operation]:
    config = config or DetectionConfig()
    events = classify_events(cues, config)
    raw_entries = [event for event in events if event.kind == "entry" and event.strength >= 0.40]
    setups = [event for event in events if event.kind == "setup"]
    entries = _prune_retrospective_entries(raw_entries, setups, config.outcome_lookahead)
    outcomes = [event for event in events if event.kind.startswith("outcome:")]

    operations: list[Operation] = []
    for entry in entries:
        candidate_setups = [
            setup
            for setup in setups
            if 0 <= entry.time - setup.time <= config.setup_lookback
        ]
        setup = candidate_setups[-1] if candidate_setups else None
        direction = _infer_direction(cues, entry, setup, config.target_speaker)
        asset = _infer_asset(cues, entry, setup, config.target_speaker)

        if operations and _near_duplicate(operations[-1], entry.time, direction, asset):
            operations[-1].event_times.append(entry.time)
            if entry.text not in operations[-1].evidence:
                operations[-1].evidence.append(entry.text)
            operations[-1].confidence = min(0.99, operations[-1].confidence + 0.04)
            continue

        next_entries = [future for future in entries if future.time > entry.time + 45]
        next_entry_time = next_entries[0].time if next_entries else float("inf")
        end_limit = min(entry.time + config.outcome_lookahead, next_entry_time - 8)
        related_outcomes = [outcome for outcome in outcomes if entry.time <= outcome.time <= end_limit]

        entry_text = normalize(entry.text)
        if "acionou" in entry_text and "pagou" in entry_text:
            # Scalp instantâneo: não associe outro "pagou" muitos minutos depois.
            related_outcomes = [outcome for outcome in related_outcomes if outcome.time <= entry.time + 60]
            end_limit = min(end_limit, entry.time + 60)
        elif "acionou" in entry_text:
            early_outcomes = [outcome for outcome in related_outcomes if outcome.time <= entry.time + 180]
            if early_outcomes:
                chained: list[Event] = []
                previous_time = entry.time
                for outcome in related_outcomes:
                    if outcome.time - previous_time <= 240:
                        chained.append(outcome)
                        previous_time = outcome.time
                    else:
                        break
                related_outcomes = chained
            else:
                related_outcomes = []
                end_limit = min(end_limit, entry.time + 90)

        # When a new explicit setup appears for a different direction/asset, stop the current trade window.
        future_setups = [future for future in setups if entry.time + 45 < future.time <= end_limit]
        for future_setup in future_setups:
            different_direction = direction and future_setup.direction and future_setup.direction != direction
            different_asset = asset and future_setup.asset and future_setup.asset != asset
            if different_direction or different_asset:
                related_outcomes = [outcome for outcome in related_outcomes if outcome.time < future_setup.time]
                end_limit = future_setup.time - 5
                break

        setup_start = setup.time if setup else None
        cut_start = max(
            0.0,
            (setup_start - config.seconds_before_setup)
            if setup_start is not None
            else entry.time - config.seconds_before_entry,
        )

        if related_outcomes:
            operation_end = related_outcomes[-1].time
            cut_end = operation_end + config.seconds_after_result
        else:
            operation_end = min(entry.time + 75, end_limit)
            cut_end = operation_end + 15

        if cut_end <= cut_start:
            cut_end = cut_start + 30

        result_labels: list[str] = []
        evidence: list[str] = []
        if setup:
            evidence.append(setup.text)
        evidence.append(entry.text)
        for outcome in related_outcomes:
            label = outcome.kind.split(":", 1)[1]
            if label not in result_labels:
                result_labels.append(label)
            if outcome.text not in evidence:
                evidence.append(outcome.text)
        evidence = evidence[:8]

        confidence = 0.42 + entry.strength * 0.34
        if setup:
            confidence += 0.09
        if direction:
            confidence += 0.05
        if asset:
            confidence += 0.03
        if related_outcomes:
            confidence += min(0.14, 0.04 + len(related_outcomes) * 0.025)
        if entry.strength < 0.65 and not setup and not related_outcomes:
            confidence -= 0.15
        confidence = max(0.0, min(0.99, confidence))

        result = ", ".join(result_labels) if result_labels else "resultado não identificado"
        direction_label = direction or "operação"
        asset_label = f" no {asset}" if asset else ""
        title = f"{direction_label.capitalize()}{asset_label}"
        digest = hashlib.sha1(f"{entry.time:.3f}-{title}".encode()).hexdigest()[:8]

        operation = Operation(
            id=f"trade-{digest}",
            title=title,
            asset=asset,
            direction=direction,
            setup_start=setup_start,
            entry_time=entry.time,
            operation_end=operation_end,
            cut_start=cut_start,
            cut_end=cut_end,
            result=result,
            confidence=round(confidence, 3),
            evidence=evidence,
            event_times=[entry.time] + [outcome.time for outcome in related_outcomes],
            selected=confidence >= 0.68,
            source="rules",
        )
        if operation.confidence >= config.minimum_confidence:
            operations.append(operation)

    return operations
