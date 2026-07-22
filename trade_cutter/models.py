from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Cue:
    index: int
    start: float
    end: float
    speaker: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Event:
    cue_index: int
    time: float
    kind: str
    text: str
    speaker: str
    direction: str = ""
    asset: str = ""
    strength: float = 0.0


@dataclass(slots=True)
class Operation:
    id: str
    title: str
    asset: str
    direction: str
    setup_start: float | None
    entry_time: float
    operation_end: float
    cut_start: float
    cut_end: float
    result: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    event_times: list[float] = field(default_factory=list)
    selected: bool = True
    source: str = "rules"
    crop_area: str = "full"
    crop_x: float = 0.0
    crop_y: float = 0.0
    crop_width: float = 1.0
    crop_height: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Operation":
        allowed = {field_name for field_name in cls.__dataclass_fields__}
        return cls(**{key: value[key] for key in allowed if key in value})
