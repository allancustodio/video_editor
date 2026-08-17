from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


OUTPUT_SIZE = (1080, 1920)
TEMPLATE_DIRECTORY = Path(__file__).resolve().parents[1] / "assets" / "templates"
TEMPLATE_PATHS = {
    "opening": TEMPLATE_DIRECTORY / "abertura.png",
    "closing": TEMPLATE_DIRECTORY / "fechamento.png",
}

# Coordinates are normalized so the source templates may be replaced without
# requiring them to have the final 1080x1920 resolution.
CONTENT_BOXES = {
    "opening": {
        "date": (0.240, 0.370, 0.785, 0.472),
        "points": (0.240, 0.495, 0.785, 0.665),
    },
    "closing": {
        "date": (0.180, 0.285, 0.817, 0.372),
        "points": (0.104, 0.390, 0.895, 0.668),
    },
}

_FONT_CANDIDATES = (
    Path(r"C:\Windows\Fonts\impact.ttf"),
    Path(r"C:\Windows\Fonts\arialbd.ttf"),
)


def format_trade_points(points: int) -> str:
    value = int(points)
    sign = "+" if value > 0 else "-" if value < 0 else ""
    formatted = f"{abs(value):,}".replace(",", ".")
    return f"{sign}{formatted}"


def render_trade_card(
    kind: str,
    trade_date: date,
    points: int,
    *,
    template_path: str | Path | None = None,
) -> bytes:
    """Render a dated opening/closing PNG from a fixed brand template."""
    if kind not in TEMPLATE_PATHS:
        raise ValueError(f"Tipo de arte inválido: {kind}")
    source = Path(template_path) if template_path else TEMPLATE_PATHS[kind]
    if not source.exists():
        raise FileNotFoundError(f"Template não encontrado: {source}")

    with Image.open(source) as template:
        image = template.convert("RGB").resize(OUTPUT_SIZE, Image.Resampling.LANCZOS)

    boxes = CONTENT_BOXES[kind]
    _draw_centered_gold_text(
        image,
        trade_date.strftime("%d/%m/%Y"),
        _scaled_box(boxes["date"]),
        height_ratio=0.54,
        spacing=1,
    )
    _draw_points(image, format_trade_points(points), _scaled_box(boxes["points"]))

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _scaled_box(box: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    width, height = OUTPUT_SIZE
    left, top, right, bottom = box
    return (
        round(left * width),
        round(top * height),
        round(right * width),
        round(bottom * height),
    )


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in _FONT_CANDIDATES:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    try:
        return ImageFont.truetype("DejaVuSansCondensed-Bold.ttf", size=size)
    except OSError:
        return ImageFont.load_default(size=size)


def _fit_font(
    text: str,
    box: tuple[int, int, int, int],
    *,
    height_ratio: float,
    spacing: int = 0,
) -> ImageFont.FreeTypeFont:
    left, top, right, bottom = box
    max_width = max(1, right - left)
    max_height = max(1, int((bottom - top) * height_ratio))
    size = max(12, max_height)
    probe = Image.new("L", (1, 1))
    draw = ImageDraw.Draw(probe)
    while size > 12:
        font = _font(size)
        bounds = draw.textbbox((0, 0), text, font=font, stroke_width=spacing)
        if bounds[2] - bounds[0] <= max_width and bounds[3] - bounds[1] <= max_height:
            return font
        size -= 2
    return _font(12)


def _draw_centered_gold_text(
    image: Image.Image,
    text: str,
    box: tuple[int, int, int, int],
    *,
    height_ratio: float,
    spacing: int = 0,
) -> None:
    font = _fit_font(text, box, height_ratio=height_ratio, spacing=spacing)
    left, top, right, bottom = box
    center = ((left + right) // 2, (top + bottom) // 2)
    draw = ImageDraw.Draw(image)
    shadow_offset = max(2, font.size // 28)
    stroke = max(1, font.size // 45)
    draw.text(
        (center[0] + shadow_offset, center[1] + shadow_offset),
        text,
        font=font,
        anchor="mm",
        fill="#2B1700",
        stroke_width=stroke,
        stroke_fill="#000000",
    )
    draw.text(
        center,
        text,
        font=font,
        anchor="mm",
        fill="#F6B622",
        stroke_width=stroke,
        stroke_fill="#8A4A00",
    )


def _draw_points(
    image: Image.Image,
    points: str,
    box: tuple[int, int, int, int],
) -> None:
    left, top, right, bottom = box
    height = bottom - top
    number_box = (left, top + round(height * 0.08), right, top + round(height * 0.62))
    label_box = (left, top + round(height * 0.61), right, top + round(height * 0.91))
    _draw_centered_gold_text(
        image,
        points,
        number_box,
        height_ratio=0.86,
        spacing=2,
    )
    _draw_centered_gold_text(
        image,
        "PONTOS",
        label_box,
        height_ratio=0.72,
        spacing=1,
    )
