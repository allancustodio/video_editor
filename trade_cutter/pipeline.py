from __future__ import annotations

from pathlib import Path

from .ai import refine_operations
from .detector import DetectionConfig, detect_operations
from .export import create_html_report, save_operations
from .models import Operation
from .vtt import parse_vtt


def analyze_transcript(
    transcript_path: str | Path,
    output_dir: str | Path,
    *,
    target_speaker: str = "RAFAEL FOSSALUSSA",
    provider: str = "rules",
    model: str = "",
    ollama_url: str = "http://localhost:11434",
    gemini_api_key: str = "",
    minimum_confidence: float = 0.50,
    video_path: str = "",
) -> list[Operation]:
    transcript = Path(transcript_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    cues = parse_vtt(transcript)
    config = DetectionConfig(target_speaker=target_speaker, minimum_confidence=minimum_confidence)
    operations = detect_operations(cues, config)

    if provider in {"ollama", "gemini"}:
        if not model:
            model = "qwen3:8b" if provider == "ollama" else "gemini-2.5-flash"
        operations = refine_operations(
            cues,
            operations,
            provider=provider,
            model=model,
            ollama_url=ollama_url,
            gemini_api_key=gemini_api_key,
            keep_rejected=True,
        )

    save_operations(output / "cuts.json", operations, transcript_path=str(transcript))
    create_html_report(output / "report.html", operations, video_path=video_path)
    return operations
