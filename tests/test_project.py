from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from trade_cutter.project import (
    copy_source_transcript,
    create_project_directory,
    load_project_manifest,
    project_video_path,
    resolve_project_file,
    write_export_error,
    write_project_manifest,
)


def main() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        created_at = datetime(2026, 8, 1, 14, 32, 18)
        first = create_project_directory(
            root,
            "Meu Vídeo Final.mp4",
            created_at=created_at,
        )
        second = create_project_directory(
            root,
            "Meu Vídeo Final.mp4",
            created_at=created_at,
        )
        assert first.name == "2026-08-01_143218_Meu-Vídeo-Final"
        assert second.name == "2026-08-01_143218_Meu-Vídeo-Final-02"
        assert project_video_path(second).name == (
            "2026-08-01_143218_Meu-Vídeo-Final-02.mp4"
        )

        source_transcript = root / "original.vtt"
        source_transcript.write_text("WEBVTT\n", encoding="utf-8")
        copied = copy_source_transcript(source_transcript, first)
        assert copied == first / "source.transcript.vtt"
        assert copied.read_text(encoding="utf-8") == "WEBVTT\n"

        cuts = first / "cuts.json"
        video = first / "video-final.mp4"
        cuts.write_text("{}", encoding="utf-8")
        video.touch()
        manifest_path = write_project_manifest(
            first,
            name="video-final",
            files={
                "video": video,
                "cuts": cuts,
                "source_transcript": copied,
            },
            source_video=root / "screen.mp4",
            professor_video=root / "professor.mp4",
            source_transcript=source_transcript,
            settings={"default_crop_area": "profit_index"},
            created_at=created_at,
        )
        loaded_path, manifest = load_project_manifest(first)
        assert loaded_path == manifest_path.resolve()
        assert manifest["files"]["cuts"] == "cuts.json"
        assert manifest["settings"]["default_crop_area"] == "profit_index"
        assert resolve_project_file(
            loaded_path,
            manifest["files"]["source_transcript"],
        ) == copied.resolve()

        error_path = write_export_error(first, RuntimeError("falha simulada"))
        assert "falha simulada" in error_path.read_text(encoding="utf-8")
        assert json.loads(manifest_path.read_text(encoding="utf-8"))["version"] == 1

    print("OK: export project folders and manifest")


if __name__ == "__main__":
    main()
