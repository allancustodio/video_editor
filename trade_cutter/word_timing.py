from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TimedWord:
    text: str
    normalized: str
    start: float
    end: float


def normalize_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^\w%]+", "", normalized)


def subtitle_words(value: str) -> list[str]:
    cleaned = value.replace("{", "").replace("}", "").replace("\\", "")
    return " ".join(cleaned.split()).split()


def estimate_word_timings(value: str, start: float, end: float) -> tuple[TimedWord, ...]:
    """Distribute a cue across its words exactly like highlighted captions."""
    words = subtitle_words(value)
    if not words:
        return ()
    weights = [max(1, len(re.sub(r"\W+", "", word))) for word in words]
    total_weight = sum(weights)
    duration = max(0.0, float(end) - float(start))
    elapsed_weight = 0
    timed: list[TimedWord] = []
    for word, weight in zip(words, weights):
        word_start = float(start) + duration * elapsed_weight / total_weight
        elapsed_weight += weight
        word_end = float(start) + duration * elapsed_weight / total_weight
        timed.append(
            TimedWord(
                text=word,
                normalized=normalize_token(word),
                start=word_start,
                end=word_end,
            )
        )
    return tuple(timed)


def find_phrase_intervals(
    value: str,
    start: float,
    end: float,
    expression: str,
) -> tuple[tuple[float, float], ...]:
    """Return estimated source-clock intervals for every literal phrase match."""
    timed = estimate_word_timings(value, start, end)
    wanted = tuple(
        token
        for token in (normalize_token(part) for part in expression.split())
        if token
    )
    if not timed or not wanted:
        return ()
    found: list[tuple[float, float]] = []
    values = tuple(word.normalized for word in timed)
    size = len(wanted)
    for index in range(0, len(values) - size + 1):
        if values[index:index + size] == wanted:
            found.append((timed[index].start, timed[index + size - 1].end))
    return tuple(found)
