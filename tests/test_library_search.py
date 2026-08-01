from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trade_cutter.library import load_user_config, save_user_config, scan_recordings
from trade_cutter.models import Cue
from trade_cutter.vtt import search_cues


def main() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        day = root / "2026-07-24"
        day.mkdir()
        prefix = "GMT20260724-114939_Recording"
        (day / f"{prefix}_as_3840x1080.mp4").touch()
        (day / f"{prefix}.transcript.vtt").touch()
        (day / f"{prefix}_avo_1280x720.mp4").touch()
        incomplete = "GMT20260724-150210_Recording"
        (root / f"{incomplete}.transcript.vtt").touch()

        recordings = scan_recordings(root)
        assert len(recordings) == 2
        assert recordings[0].key == incomplete
        assert recordings[0].missing == ["tela", "professor"]
        assert recordings[1].complete
        assert recordings[1].screen_video.endswith("_as_3840x1080.mp4")

        config_path = root / "user_config.json"
        save_user_config({"recordings_folder": str(root)}, config_path)
        assert load_user_config(config_path)["recordings_folder"] == str(root)

    cues = [
        Cue(1, 10.0, 12.0, "PROFESSOR", "A resistência está segurando."),
        Cue(2, 20.0, 22.0, "PROFESSOR", "Existe outra resistente aqui."),
        Cue(3, 30.0, 32.0, "PROFESSOR", "RESISTENCIA rompida."),
    ]
    matches = search_cues(cues, "resistência")
    assert [cue.index for cue in matches] == [1, 3]
    try:
        search_cues(cues, "duas palavras")
    except ValueError:
        pass
    else:
        raise AssertionError("A busca deveria aceitar apenas uma palavra.")

    print("OK: catálogo de gravações, configuração local e busca por palavra.")


if __name__ == "__main__":
    main()
