from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Iterable

from .detector import normalize
from .models import Cue, Operation, Scene


DEFAULT_SCENE_KEYWORDS = ("stop", "lote", "parcial", "alvo", "porcento", "gain")

_KEYWORD_PATTERNS = {
    "stop": re.compile(r"\b(?:e?stop\w*)\b"),
    "lote": re.compile(r"\blotes?\b"),
    "parcial": re.compile(r"\bparcia(?:l|is)\b"),
    "alvo": re.compile(r"\balvos?\b"),
    "porcento": re.compile(r"(?:\bpor\s*cento\b|\bporcento\b|%)"),
    "gain": re.compile(r"\bgains?\b"),
}


@dataclass(frozen=True, slots=True)
class KeywordOccurrence:
    id: str
    cue_index: int
    cue_start: float
    cue_end: float
    start: float
    end: float
    speaker: str
    text: str
    keywords: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SceneSuggestion:
    start: float
    end: float
    kind: str
    speed: float
    reason: str
    keyword_labels: tuple[str, ...] = ()

    @property
    def source_duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def output_duration(self) -> float:
        if self.kind == "jump":
            return 0.0
        return self.source_duration / max(0.1, self.speed)


@dataclass(frozen=True, slots=True)
class SceneSuggestionPlan:
    scenes: tuple[SceneSuggestion, ...]
    occurrences: tuple[KeywordOccurrence, ...]
    selected_occurrence_ids: frozenset[str]
    matched_keyword_count: int

    @property
    def relevant_cue_count(self) -> int:
        return len(self.occurrences)

    @property
    def selected_occurrence_count(self) -> int:
        return len(self.selected_occurrence_ids)


def suggest_scenes(
    operation: Operation,
    cues: Iterable[Cue],
    *,
    target_speaker: str,
    context_before: float = 3.0,
    context_after: float = 3.0,
    target_fast_duration: float = 5.0,
    minimum_gap: float = 12.0,
    max_speed: float = 100.0,
) -> SceneSuggestionPlan:
    """Find keyword phrases and initially keep every occurrence at normal speed."""
    occurrences = find_keyword_occurrences(
        operation,
        cues,
        target_speaker=target_speaker,
        context_before=context_before,
        context_after=context_after,
    )
    return build_scene_suggestion_plan(
        operation,
        occurrences,
        selected_occurrence_ids={item.id for item in occurrences},
        target_fast_duration=target_fast_duration,
        minimum_gap=minimum_gap,
        max_speed=max_speed,
    )


def find_keyword_occurrences(
    operation: Operation,
    cues: Iterable[Cue],
    *,
    target_speaker: str,
    context_before: float = 3.0,
    context_after: float = 3.0,
) -> tuple[KeywordOccurrence, ...]:
    """Return one approval item per matching VTT cue inside the selected cut."""
    before = max(0.0, float(context_before))
    after = max(0.0, float(context_after))
    wanted_speaker = normalize(target_speaker)
    occurrences: list[KeywordOccurrence] = []
    for cue in cues:
        if cue.end <= operation.cut_start or cue.start >= operation.cut_end:
            continue
        if wanted_speaker and wanted_speaker not in normalize(cue.speaker):
            continue
        text = normalize(cue.text)
        matched = tuple(
            keyword
            for keyword in DEFAULT_SCENE_KEYWORDS
            if _KEYWORD_PATTERNS[keyword].search(text)
        )
        if not matched:
            continue
        occurrences.append(
            KeywordOccurrence(
                id=f"cue-{cue.index}-{int(cue.start * 1000)}",
                cue_index=cue.index,
                cue_start=cue.start,
                cue_end=cue.end,
                start=max(operation.cut_start, cue.start - before),
                end=min(operation.cut_end, cue.end + after),
                speaker=cue.speaker,
                text=" ".join(cue.text.split()),
                keywords=matched,
            )
        )
    return tuple(occurrences)


def build_scene_suggestion_plan(
    operation: Operation,
    occurrences: Iterable[KeywordOccurrence],
    *,
    selected_occurrence_ids: set[str] | frozenset[str],
    target_fast_duration: float = 5.0,
    minimum_gap: float = 12.0,
    max_speed: float = 100.0,
) -> SceneSuggestionPlan:
    """Build the timeline after the user chooses which phrases stay at 1x."""
    occurrence_values = tuple(occurrences)
    selected_ids = frozenset(selected_occurrence_ids)
    selected = [item for item in occurrence_values if item.id in selected_ids]
    target_fast_duration = max(0.1, float(target_fast_duration))
    minimum_gap = max(0.0, float(minimum_gap))
    max_speed = max(1.0, float(max_speed))

    anchors = [
        SceneSuggestion(
            start=item.start,
            end=item.end,
            kind="normal",
            speed=1.0,
            reason=(
                f'Fala selecionada: “{item.text}” · '
                f"palavras: {', '.join(item.keywords)}"
            ),
            keyword_labels=item.keywords,
        )
        for item in selected
    ]
    merged_anchors = _merge_normal(anchors)
    proposed: list[SceneSuggestion] = []
    cursor = operation.cut_start
    for anchor in merged_anchors:
        if anchor.start > cursor:
            proposed.append(
                _gap_suggestion(
                    cursor,
                    anchor.start,
                    target_fast_duration=target_fast_duration,
                    minimum_gap=minimum_gap,
                    max_speed=max_speed,
                )
            )
        proposed.append(anchor)
        cursor = anchor.end
    if cursor < operation.cut_end:
        proposed.append(
            _gap_suggestion(
                cursor,
                operation.cut_end,
                target_fast_duration=target_fast_duration,
                minimum_gap=minimum_gap,
                max_speed=max_speed,
            )
        )
    if not proposed:
        proposed = [
            SceneSuggestion(
                operation.cut_start,
                operation.cut_end,
                "normal",
                1.0,
                "Trecho sem duração suficiente para análise.",
            )
        ]

    matched_keywords = {
        keyword
        for item in selected
        for keyword in item.keywords
    }
    return SceneSuggestionPlan(
        scenes=tuple(_merge_normal(proposed)),
        occurrences=occurrence_values,
        selected_occurrence_ids=selected_ids,
        matched_keyword_count=len(matched_keywords),
    )


def materialize_suggestions(
    operation: Operation,
    suggestions: Iterable[SceneSuggestion],
    *,
    approved_jumps: set[int] | None = None,
    max_speed: float = 100.0,
) -> list[Scene]:
    """Create editable scenes using the agreed default composition."""
    existing = sorted(operation.ensure_scenes(), key=lambda item: (item.start, item.end))
    approved_jumps = approved_jumps or set()
    generated: list[Scene] = []
    for suggestion_index, suggestion in enumerate(suggestions):
        midpoint = suggestion.start + (suggestion.end - suggestion.start) / 2
        reference = next(
            (scene for scene in existing if scene.start <= midpoint < scene.end),
            existing[-1],
        )
        is_approved_jump = suggestion.kind == "jump" and suggestion_index in approved_jumps
        if suggestion.kind == "normal":
            speed, audio, subtitles = 1.0, "project", True
        else:
            speed = min(float(max_speed), float(suggestion.speed))
            audio, subtitles = "mute", False
        generated.append(
            replace(
                reference,
                id=f"auto-{suggestion_index + 1}-{int(suggestion.start * 1000)}",
                start=suggestion.start,
                end=suggestion.end,
                layout="professor_top",
                graph_alignment="right",
                playback_speed=speed,
                audio_mode=audio,
                subtitles_enabled=subtitles,
                skip=is_approved_jump,
            )
        )
    operation.scenes = generated
    return generated


def _gap_suggestion(
    start: float,
    end: float,
    *,
    target_fast_duration: float,
    minimum_gap: float,
    max_speed: float,
) -> SceneSuggestion:
    duration = max(0.0, end - start)
    if duration < minimum_gap:
        return SceneSuggestion(
            start,
            end,
            "normal",
            1.0,
            f"Intervalo curto ({duration:.1f}s); mantido em velocidade normal.",
        )
    ideal_speed = duration / target_fast_duration
    if ideal_speed <= max_speed:
        return SceneSuggestion(
            start,
            end,
            "accelerated",
            max(1.0, ideal_speed),
            f"Sem frase selecionada por {duration:.1f}s; reduzido para cerca de {target_fast_duration:g}s.",
        )
    return SceneSuggestion(
        start,
        end,
        "jump",
        ideal_speed,
        (
            f"Sem frase selecionada por {duration:.1f}s; seriam necessários {ideal_speed:.1f}×. "
            "Salto sugerido, sujeito a aprovação."
        ),
    )


def _merge_normal(items: Iterable[SceneSuggestion]) -> list[SceneSuggestion]:
    ordered = sorted(items, key=lambda item: (item.start, item.end))
    merged: list[SceneSuggestion] = []
    for item in ordered:
        if (
            merged
            and merged[-1].kind == "normal"
            and item.kind == "normal"
            and item.start <= merged[-1].end + 0.001
        ):
            previous = merged[-1]
            labels = tuple(dict.fromkeys((*previous.keyword_labels, *item.keyword_labels)))
            reasons = list(dict.fromkeys((previous.reason, item.reason)))
            merged[-1] = SceneSuggestion(
                previous.start,
                max(previous.end, item.end),
                "normal",
                1.0,
                " | ".join(reasons),
                labels,
            )
        else:
            merged.append(item)
    return merged
