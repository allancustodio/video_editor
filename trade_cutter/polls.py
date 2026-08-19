from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


OUTPUT_SIZE = (1080, 1920)
POLL_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1] / "assets" / "templates" / "enquete.png"
)
SAFE_LEFT = 120
SAFE_RIGHT = 920
SAFE_TOP = 220
SAFE_BOTTOM = 1640
QUESTION_BOX = (210, 710, 870, 1080)
RESULT_BOX = (210, 1140, 870, 1505)
_POLL_FILENAME_SUFFIX = ".poll.csv"
_POLL_DATE_RE = re.compile(r"GMT(?P<date>\d{8})-", re.IGNORECASE)
_FONT_CANDIDATES = (
    Path(r"C:\Windows\Fonts\impact.ttf"),
    Path(r"C:\Windows\Fonts\arialbd.ttf"),
)
_PORTUGUESE_MONTHS = (
    "JANEIRO",
    "FEVEREIRO",
    "MARÇO",
    "ABRIL",
    "MAIO",
    "JUNHO",
    "JULHO",
    "AGOSTO",
    "SETEMBRO",
    "OUTUBRO",
    "NOVEMBRO",
    "DEZEMBRO",
)


@dataclass(frozen=True, slots=True)
class PollAnswer:
    label: str
    percentage: float


@dataclass(frozen=True, slots=True)
class ZoomPollResult:
    polling_name: str
    question: str
    answers: tuple[PollAnswer, ...]
    poll_date: date
    meeting_topic: str = ""


def discover_zoom_poll_files(video_path: str | Path = "") -> list[Path]:
    video = Path(video_path) if video_path else None
    folder = video.parent if video and str(video).strip() else Path.cwd()
    if not folder.exists() or not folder.is_dir():
        return []
    return sorted(
        (
            path.resolve()
            for path in folder.iterdir()
            if path.is_file() and path.name.casefold().endswith(_POLL_FILENAME_SUFFIX)
        ),
        key=lambda path: path.name.casefold(),
    )


def parse_zoom_poll_csv(source: str | Path) -> list[ZoomPollResult]:
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo de enquete não encontrado: {path}")
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        rows = [
            [cell.strip() for cell in row]
            for row in csv.reader(handle)
            if any(cell.strip() for cell in row)
        ]
    if not rows:
        return []

    meeting_topic = ""
    start_value = ""
    for index, row in enumerate(rows[:-1]):
        lowered = [cell.casefold() for cell in row]
        if "meeting topic" in lowered and "start time" in lowered:
            values = rows[index + 1]
            topic_index = lowered.index("meeting topic")
            start_index = lowered.index("start time")
            meeting_topic = values[topic_index] if topic_index < len(values) else ""
            start_value = values[start_index] if start_index < len(values) else ""
            break
    poll_date = _poll_date(path, start_value)

    results: list[ZoomPollResult] = []
    polling_name = ""
    question_answers: dict[str, list[PollAnswer]] = {}
    question_order: list[str] = []

    def flush() -> None:
        nonlocal question_answers, question_order
        for question in question_order:
            answers = tuple(question_answers.get(question, ()))
            if answers:
                results.append(
                    ZoomPollResult(
                        polling_name=polling_name,
                        question=question,
                        answers=answers,
                        poll_date=poll_date,
                        meeting_topic=meeting_topic,
                    )
                )
        question_answers = {}
        question_order = []

    for row in rows:
        first = row[0] if row else ""
        if first.casefold().startswith("polling name"):
            flush()
            polling_name = first.split(":", 1)[1].strip() if ":" in first else ""
            continue
        if len(row) < 3 or first.casefold() == "question":
            continue
        percentage = _parse_percentage(row[2])
        question = first.strip()
        answer = row[1].strip()
        if percentage is None or not question or not answer:
            continue
        if question not in question_answers:
            question_answers[question] = []
            question_order.append(question)
        question_answers[question].append(PollAnswer(answer, percentage))
    flush()
    return results


def render_poll_card(
    poll: ZoomPollResult,
    *,
    template_path: str | Path | None = None,
) -> bytes:
    if not poll.answers:
        raise ValueError("A enquete não possui respostas para exibir.")
    source = Path(template_path) if template_path else POLL_TEMPLATE_PATH
    if not source.exists():
        raise FileNotFoundError(f"Template de enquete não encontrado: {source}")
    with Image.open(source) as template:
        image = template.convert("RGB").resize(OUTPUT_SIZE, Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image)
    date_text = (
        f"{poll.poll_date.day:02d} DE {_PORTUGUESE_MONTHS[poll.poll_date.month - 1]} "
        f"DE {poll.poll_date.year}"
    )
    question = (poll.question or poll.polling_name or "ENQUETE DA SALA").strip().upper()
    _draw_gold_text(draw, date_text, (540, 770), max_width=600, max_height=58)
    _draw_wrapped_gold_text(
        draw,
        question,
        (QUESTION_BOX[0] + 35, 835, QUESTION_BOX[2] - 35, 1035),
        max_lines=3,
    )

    winner = max(poll.answers, key=lambda item: item.percentage)
    _draw_gold_text(
        draw,
        _format_percentage(winner.percentage),
        (540, 1205),
        max_width=560,
        max_height=118,
    )
    _draw_gold_text(
        draw,
        winner.label.upper(),
        (540, 1310),
        max_width=560,
        max_height=55,
    )
    remaining = [answer for answer in poll.answers if answer is not winner]
    _draw_secondary_answers(draw, remaining)

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _draw_secondary_answers(draw: ImageDraw.ImageDraw, answers: Iterable[PollAnswer]) -> None:
    values = list(answers)
    if not values:
        return
    top = 1380
    available_height = RESULT_BOX[3] - top
    row_height = min(58, max(34, available_height // len(values)))
    font_size = min(42, max(25, row_height - 12))
    font = _font(font_size)
    for index, answer in enumerate(values):
        y = top + index * row_height + row_height // 2
        label = answer.label.upper()
        percentage = _format_percentage(answer.percentage)
        draw.text(
            (RESULT_BOX[0] + 35, y),
            label,
            font=font,
            anchor="lm",
            fill="#F3E4C2",
            stroke_width=1,
            stroke_fill="#2B1700",
        )
        draw.text(
            (RESULT_BOX[2] - 35, y),
            percentage,
            font=font,
            anchor="rm",
            fill="#F6B622",
            stroke_width=1,
            stroke_fill="#6D3900",
        )


def _draw_wrapped_gold_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    *,
    max_lines: int,
) -> None:
    left, top, right, bottom = box
    max_width = right - left
    max_height = bottom - top
    for size in range(56, 21, -2):
        font = _font(size)
        lines = _wrap_text(draw, text, font, max_width)
        if len(lines) > max_lines:
            continue
        spacing = max(5, size // 6)
        bounds = draw.multiline_textbbox(
            (0, 0), "\n".join(lines), font=font, spacing=spacing, align="center"
        )
        if bounds[3] - bounds[1] <= max_height:
            draw.multiline_text(
                ((left + right) // 2, (top + bottom) // 2),
                "\n".join(lines),
                font=font,
                spacing=spacing,
                align="center",
                anchor="mm",
                fill="#F6B622",
                stroke_width=max(1, size // 40),
                stroke_fill="#7A4100",
            )
            return
    raise ValueError("A pergunta da enquete é longa demais para o template.")


def _draw_gold_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    center: tuple[int, int],
    *,
    max_width: int,
    max_height: int,
) -> None:
    font = _fit_font(draw, text, max_width=max_width, max_height=max_height)
    shadow = max(2, font.size // 28)
    draw.text(
        (center[0] + shadow, center[1] + shadow),
        text,
        font=font,
        anchor="mm",
        fill="#2B1700",
        stroke_width=1,
        stroke_fill="#000000",
    )
    draw.text(
        center,
        text,
        font=font,
        anchor="mm",
        fill="#F6B622",
        stroke_width=max(1, font.size // 45),
        stroke_fill="#8A4A00",
    )


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    max_width: int,
    max_height: int,
) -> ImageFont.FreeTypeFont:
    for size in range(max_height, 15, -2):
        font = _font(size)
        bounds = draw.textbbox((0, 0), text, font=font, stroke_width=1)
        if bounds[2] - bounds[0] <= max_width and bounds[3] - bounds[1] <= max_height:
            return font
    return _font(16)


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        proposed = f"{current} {word}"
        if draw.textlength(proposed, font=font) <= max_width:
            current = proposed
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in _FONT_CANDIDATES:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    try:
        return ImageFont.truetype("DejaVuSansCondensed-Bold.ttf", size=size)
    except OSError:
        return ImageFont.load_default(size=size)


def _parse_percentage(value: str) -> float | None:
    cleaned = value.strip().replace("%", "").replace(",", ".")
    try:
        percentage = float(cleaned)
    except ValueError:
        return None
    if percentage < 0 or percentage > 100:
        return None
    return percentage


def _format_percentage(value: float) -> str:
    if float(value).is_integer():
        return f"{int(value)}%"
    return f"{value:.1f}%".replace(".", ",")


def _poll_date(path: Path, start_value: str) -> date:
    if start_value:
        try:
            return datetime.fromisoformat(start_value).date()
        except ValueError:
            pass
    match = _POLL_DATE_RE.search(path.name)
    if match:
        return datetime.strptime(match.group("date"), "%Y%m%d").date()
    return date.today()
