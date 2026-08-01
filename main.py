from __future__ import annotations

import argparse
import sys
from pathlib import Path

from trade_cutter.export import load_operations, save_operations
from trade_cutter.ffmpeg import cut_selected, export_final_video
from trade_cutter.pipeline import analyze_transcript
from trade_cutter.timecode import format_timecode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Detecta operações em VTT e corta um vídeo local.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Analisa a transcrição e gera cuts.json/report.html")
    analyze.add_argument("--transcript", required=True)
    analyze.add_argument("--output", default="output")
    analyze.add_argument("--speaker", default="RAFAEL FOSSALUSSA")
    analyze.add_argument("--provider", choices=["rules", "ollama", "gemini"], default="rules")
    analyze.add_argument("--model", default="")
    analyze.add_argument("--ollama-url", default="http://localhost:11434")
    analyze.add_argument("--gemini-api-key", default="")
    analyze.add_argument("--minimum-confidence", type=float, default=0.50)
    analyze.add_argument("--video", default="")
    analyze.add_argument("--rules", default="user_rules.json")

    cut = subparsers.add_parser("cut", help="Gera os clipes a partir de cuts.json")
    cut.add_argument("--video", required=True)
    cut.add_argument("--cuts", default="output/cuts.json")
    cut.add_argument("--output", default="output/clips")
    cut.add_argument("--mode", choices=["exact", "fast"], default="exact")
    cut.add_argument("--ffmpeg", default="")
    cut.add_argument(
        "--format",
        choices=[
            "original",
            "vertical",
            "split_vertical",
            "professor_vertical",
            "professor_horizontal",
            "split_then_professor",
        ],
        default=None,
        help="Sobrescreve o formato salvo em cada corte.",
    )
    cut.add_argument("--professor-video", default="")
    cut.add_argument("--professor-sync-offset", type=float, default=0.0)
    cut.add_argument("--audio-source", choices=["professor", "screen"], default="professor")
    cut.add_argument("--professor-zoom", type=float, default=1.0)
    cut.add_argument("--professor-x", type=float, default=0.0)
    cut.add_argument("--professor-y", type=float, default=0.0)
    cut.add_argument("--graph-zoom", type=float, default=1.0)
    cut.add_argument("--graph-x", type=float, default=0.0)
    cut.add_argument("--graph-y", type=float, default=0.0)
    cut.add_argument("--full-professor-zoom", type=float, default=1.0)
    cut.add_argument("--full-professor-x", type=float, default=0.0)
    cut.add_argument("--full-professor-y", type=float, default=0.0)
    cut.add_argument("--all", action="store_true", help="Corta inclusive candidatos não selecionados")

    assemble = subparsers.add_parser(
        "assemble", help="Monta todas as cenas selecionadas em um único MP4"
    )
    assemble.add_argument("--video", required=True, help="Vídeo da tela/gráfico")
    assemble.add_argument("--professor-video", required=True)
    assemble.add_argument("--cuts", default="output/cuts.json")
    assemble.add_argument("--output", default="output/video-final.mp4")
    assemble.add_argument("--orientation", choices=["vertical", "horizontal"], default="vertical")
    assemble.add_argument("--professor-sync-offset", type=float, default=0.0)
    assemble.add_argument("--audio-source", choices=["professor", "screen"], default="professor")
    assemble.add_argument("--ffmpeg", default="")

    all_command = subparsers.add_parser("all", help="Analisa e corta em uma única execução")
    all_command.add_argument("--transcript", required=True)
    all_command.add_argument("--video", required=True)
    all_command.add_argument("--output", default="output")
    all_command.add_argument("--speaker", default="RAFAEL FOSSALUSSA")
    all_command.add_argument("--provider", choices=["rules", "ollama", "gemini"], default="rules")
    all_command.add_argument("--model", default="")
    all_command.add_argument("--ollama-url", default="http://localhost:11434")
    all_command.add_argument("--gemini-api-key", default="")
    all_command.add_argument("--minimum-confidence", type=float, default=0.50)
    all_command.add_argument("--mode", choices=["exact", "fast"], default="exact")
    all_command.add_argument("--ffmpeg", default="")
    all_command.add_argument(
        "--format",
        choices=[
            "original",
            "vertical",
            "split_vertical",
            "professor_vertical",
            "professor_horizontal",
            "split_then_professor",
        ],
        default=None,
        help="Sobrescreve o formato salvo em cada corte.",
    )
    all_command.add_argument("--professor-video", default="")
    all_command.add_argument("--professor-sync-offset", type=float, default=0.0)
    all_command.add_argument("--audio-source", choices=["professor", "screen"], default="professor")
    all_command.add_argument("--professor-zoom", type=float, default=1.0)
    all_command.add_argument("--professor-x", type=float, default=0.0)
    all_command.add_argument("--professor-y", type=float, default=0.0)
    all_command.add_argument("--graph-zoom", type=float, default=1.0)
    all_command.add_argument("--graph-x", type=float, default=0.0)
    all_command.add_argument("--graph-y", type=float, default=0.0)
    all_command.add_argument("--full-professor-zoom", type=float, default=1.0)
    all_command.add_argument("--full-professor-x", type=float, default=0.0)
    all_command.add_argument("--full-professor-y", type=float, default=0.0)
    all_command.add_argument("--rules", default="user_rules.json")
    return parser


def print_operations(operations) -> None:
    print(f"\n{len(operations)} candidatos encontrados:\n")
    for index, operation in enumerate(operations, 1):
        mark = "X" if operation.selected else " "
        print(
            f"[{mark}] {index:02d} {operation.title:<28} "
            f"entrada={format_timecode(operation.entry_time)} "
            f"corte={format_timecode(operation.cut_start)}-{format_timecode(operation.cut_end)} "
            f"conf={operation.confidence:.0%} resultado={operation.result}"
        )


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "analyze":
            operations = analyze_transcript(
                args.transcript,
                args.output,
                target_speaker=args.speaker,
                provider=args.provider,
                model=args.model,
                ollama_url=args.ollama_url,
                gemini_api_key=args.gemini_api_key,
                minimum_confidence=args.minimum_confidence,
                video_path=args.video,
                rules_path=args.rules,
            )
            print_operations(operations)
            print(f"\nArquivos: {Path(args.output) / 'cuts.json'} e {Path(args.output) / 'report.html'}")
            return 0

        if args.command == "cut":
            operations = load_operations(args.cuts)
            if args.all:
                for operation in operations:
                    operation.selected = True
            results = cut_selected(
                args.video,
                operations,
                args.output,
                mode=args.mode,
                ffmpeg_path=args.ffmpeg,
                output_format=args.format,
                professor_video_path=args.professor_video,
                professor_sync_offset=args.professor_sync_offset,
                audio_source=args.audio_source,
                professor_zoom=args.professor_zoom,
                professor_position_x=args.professor_x,
                professor_position_y=args.professor_y,
                graph_zoom=args.graph_zoom,
                graph_position_x=args.graph_x,
                graph_position_y=args.graph_y,
                full_professor_zoom=args.full_professor_zoom,
                full_professor_position_x=args.full_professor_x,
                full_professor_position_y=args.full_professor_y,
            )
            print(f"{len(results)} clipes gerados em {args.output}")
            return 0

        if args.command == "assemble":
            operations = load_operations(args.cuts)
            target = export_final_video(
                args.video,
                args.professor_video,
                operations,
                args.output,
                orientation=args.orientation,
                ffmpeg_path=args.ffmpeg,
                professor_sync_offset=args.professor_sync_offset,
                audio_source=args.audio_source,
            )
            print(f"Vídeo final gerado em {target}")
            return 0

        if args.command == "all":
            operations = analyze_transcript(
                args.transcript,
                args.output,
                target_speaker=args.speaker,
                provider=args.provider,
                model=args.model,
                ollama_url=args.ollama_url,
                gemini_api_key=args.gemini_api_key,
                minimum_confidence=args.minimum_confidence,
                video_path=args.video,
                rules_path=args.rules,
            )
            print_operations(operations)
            save_operations(Path(args.output) / "cuts.json", operations, transcript_path=args.transcript)
            results = cut_selected(
                args.video,
                operations,
                Path(args.output) / "clips",
                mode=args.mode,
                ffmpeg_path=args.ffmpeg,
                output_format=args.format,
                professor_video_path=args.professor_video,
                professor_sync_offset=args.professor_sync_offset,
                audio_source=args.audio_source,
                professor_zoom=args.professor_zoom,
                professor_position_x=args.professor_x,
                professor_position_y=args.professor_y,
                graph_zoom=args.graph_zoom,
                graph_position_x=args.graph_x,
                graph_position_y=args.graph_y,
                full_professor_zoom=args.full_professor_zoom,
                full_professor_position_x=args.full_professor_x,
                full_professor_position_y=args.full_professor_y,
            )
            print(f"\n{len(results)} clipes gerados em {Path(args.output) / 'clips'}")
            return 0
    except Exception as error:
        print(f"ERRO: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
