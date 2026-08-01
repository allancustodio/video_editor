from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


OUTPUT_LAYOUT_LABELS = {
    "original": "Tela original",
    "split_vertical": "Dividido vertical",
    "professor_vertical": "Professor vertical",
    "professor_horizontal": "Professor horizontal",
    "split_then_professor": "Dividido → professor",
}

OUTPUT_ORIENTATION_LABELS = {
    "vertical": "Vertical 9:16",
    "horizontal": "Horizontal 16:9",
}

SCENE_LAYOUT_LABELS = {
    "graph_full": "Gráfico em tela inteira",
    "professor_full": "Professor em tela inteira",
    "professor_top": "Professor em cima · gráfico embaixo",
    "graph_top": "Gráfico em cima · professor embaixo",
    "side_by_side": "Professor e gráfico lado a lado",
}

GRAPH_ALIGNMENT_LABELS = {
    "left": "Esquerda",
    "center": "Centro",
    "right": "Direita",
}


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
class Scene:
    id: str
    start: float
    end: float
    layout: str = "professor_top"
    professor_zoom: float = 1.0
    professor_x: float = 0.0
    professor_y: float = 0.0
    graph_zoom: float = 1.0
    graph_x: float = 0.0
    graph_y: float = 0.0
    graph_alignment: str = "center"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Scene":
        allowed = {field_name for field_name in cls.__dataclass_fields__}
        return cls(**{key: value[key] for key in allowed if key in value})


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
    layout_mode: str = "original"
    layout_switch_time: float | None = None
    sequence_order: int = 0
    output_orientation: str = "vertical"
    scenes: list[Scene] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Operation":
        allowed = {field_name for field_name in cls.__dataclass_fields__}
        payload = {key: value[key] for key in allowed if key in value and key != "scenes"}
        payload["scenes"] = [
            item if isinstance(item, Scene) else Scene.from_dict(item)
            for item in value.get("scenes", [])
        ]
        return cls(**payload)

    def ensure_scenes(self) -> list[Scene]:
        """Create an editable scene timeline from legacy layout fields when needed."""
        if self.scenes:
            return self.scenes

        legacy_layout = {
            "original": "graph_full",
            "split_vertical": "professor_top",
            "vertical": "professor_top",
            "professor_vertical": "professor_full",
            "professor_horizontal": "professor_full",
        }.get(self.layout_mode, "professor_top")
        if (
            self.layout_mode == "split_then_professor"
            and self.layout_switch_time is not None
            and self.cut_start < self.layout_switch_time < self.cut_end
        ):
            self.scenes = [
                Scene("scene-1", self.cut_start, self.layout_switch_time, "professor_top"),
                Scene("scene-2", self.layout_switch_time, self.cut_end, "professor_full"),
            ]
        else:
            self.scenes = [Scene("scene-1", self.cut_start, self.cut_end, legacy_layout)]
        return self.scenes

    def set_cut_bounds(self, start: float, end: float) -> list[Scene]:
        """Trim or extend the scene timeline while preserving scene framing."""
        start = max(0.0, float(start))
        end = max(0.0, float(end))
        if end <= start:
            raise ValueError("O fim do trecho precisa ser posterior ao início.")

        scenes = sorted(self.ensure_scenes(), key=lambda item: (item.start, item.end))
        if start < scenes[0].start:
            scenes[0].start = start
        if end > scenes[-1].end:
            scenes[-1].end = end

        kept = [scene for scene in scenes if scene.end > start and scene.start < end]
        if not kept:
            reference = scenes[0] if end <= scenes[0].start else scenes[-1]
            kept = [
                Scene(
                    id=f"scene-{int(start * 1000)}-bounds",
                    start=start,
                    end=end,
                    layout=reference.layout,
                    professor_zoom=reference.professor_zoom,
                    professor_x=reference.professor_x,
                    professor_y=reference.professor_y,
                    graph_zoom=reference.graph_zoom,
                    graph_x=reference.graph_x,
                    graph_y=reference.graph_y,
                    graph_alignment=reference.graph_alignment,
                )
            ]
        else:
            kept[0].start = start
            kept[-1].end = end

        self.cut_start = start
        self.cut_end = end
        self.scenes = kept
        return kept
