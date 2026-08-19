from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from .ffmpeg import find_ffmpeg


OUTPUT_SIZE = (1080, 1920)
SAFE_TOP = 220
SAFE_LEFT = 120
SAFE_RIGHT = 920
SAFE_BOTTOM = 1640
CONTENT_TOP = 470
CONTENT_BOTTOM = 1530
MAX_COMMENTS_PER_PAGE = 8
VIDEO_FADE_SECONDS = 0.20
VIDEO_FADE_STEPS = 5
VIDEO_PAGE_INTRO_SECONDS = 0.30
AVATAR_X = SAFE_LEFT
BUBBLE_LEFT = 206
TEXT_LEFT = 226
MESSAGE_TEXT_WIDTH = SAFE_RIGHT - TEXT_LEFT - 20
ZOOM_COLORS = (
    "#8E44AD",
    "#00A86B",
    "#0E7490",
    "#D97706",
    "#EA580C",
    "#0284C7",
    "#0F766E",
    "#475569",
    "#7C3AED",
    "#BE123C",
)
RULE_KINDS = ("positive", "negative")
RULE_KIND_LABELS = {"positive": "Positiva", "negative": "Negativa"}
LABEL_TO_RULE_KIND = {label: key for key, label in RULE_KIND_LABELS.items()}
_CHAT_LINE_RE = re.compile(
    r"^(?P<time>\d{2}:\d{2}:\d{2})\t(?P<author>[^\t:]+):\t?(?P<text>.*)$"
)
_FILENAME_RE = re.compile(
    r"GMT(?P<date>\d{8})-(?P<time>\d{6})",
    re.IGNORECASE,
)
_REACTION_RE = re.compile(r'^Reacted to "(?P<quote>.*)" with\s*(?P<emoji>.+)$', re.DOTALL)
_REPLY_RE = re.compile(r'^Replying to ".*?"\s*(?P<reply>.*)$', re.DOTALL)
_FONT_REGULAR = (
    Path(r"C:\Windows\Fonts\segoeui.ttf"),
    Path(r"C:\Windows\Fonts\arial.ttf"),
)
_FONT_BOLD = (
    Path(r"C:\Windows\Fonts\segoeuib.ttf"),
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
class ZoomChatMessage:
    index: int
    elapsed: float
    author: str
    text: str
    kind: str = "message"
    quoted_text: str = ""
    reaction: str = ""


@dataclass(frozen=True, slots=True)
class StaffMember:
    id: str
    full_name: str
    aliases: tuple[str, ...] = ()
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["aliases"] = list(self.aliases)
        return payload


@dataclass(frozen=True, slots=True)
class FeedbackRule:
    id: str
    kind: str
    expression: str
    score: float
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SocialProofConfig:
    staff: list[StaffMember] = field(default_factory=list)
    rules: list[FeedbackRule] = field(default_factory=list)
    group_seconds: float = 60.0
    possible_threshold: float = 3.0
    strong_threshold: float = 6.0
    teacher_mention_bonus: float = 2.0
    reaction_bonus: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "staff": [item.to_dict() for item in self.staff],
            "rules": [item.to_dict() for item in self.rules],
            "group_seconds": self.group_seconds,
            "possible_threshold": self.possible_threshold,
            "strong_threshold": self.strong_threshold,
            "teacher_mention_bonus": self.teacher_mention_bonus,
            "reaction_bonus": self.reaction_bonus,
        }


@dataclass(frozen=True, slots=True)
class FeedbackCandidate:
    id: str
    author: str
    display_name: str
    start: float
    end: float
    wall_time: datetime
    text: str
    avatar_color: str
    score: float
    classification: str
    reasons: tuple[str, ...]
    context: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["wall_time"] = self.wall_time.isoformat()
        payload["reasons"] = list(self.reasons)
        payload["context"] = list(self.context)
        return payload


@dataclass(frozen=True, slots=True)
class SocialProofVideoResult:
    path: Path
    duration: float
    comment_count: int
    page_count: int


def default_social_proof_config() -> SocialProofConfig:
    staff = [
        StaffMember("staff-rafael", "Rafael Fossalussa", ("Rafa", "Rafael")),
        StaffMember("staff-david", "David Fabri", ("David",)),
        StaffMember("staff-ricardo", "Ricardo Bueno", ("Ricardo",)),
    ]
    raw_rules = [
        ("meta-batida", "positive", "meta batid", 8.0),
        ("bati-meta", "positive", "bati a meta", 8.0),
        ("meta-dia", "positive", "meta do dia", 6.0),
        ("sai-gain", "positive", "sai no gain", 7.0),
        ("gain", "positive", "gain", 5.0),
        ("positivo", "positive", "positivo", 5.0),
        ("lucro", "positive", "lucro", 5.0),
        ("deu-bom", "positive", "deu bom", 4.0),
        ("acertei", "positive", "acertei", 5.0),
        ("acertou-tudo", "positive", "acertou tudo", 6.0),
        ("peguei", "positive", "peguei", 3.0),
        ("entramos", "positive", "pegamos", 3.0),
        ("entrei", "positive", "entrei", 3.0),
        ("pagou", "positive", "pagou", 3.0),
        ("pontos", "positive", "pontos", 3.0),
        ("pts", "positive", "pts", 3.0),
        ("call", "positive", "call", 3.0),
        ("segurei", "positive", "segurei", 3.0),
        ("ajudou", "positive", "ajudou", 5.0),
        ("aprendi", "positive", "aprendi", 5.0),
        ("didatica", "positive", "didatica", 5.0),
        ("melhor-sala", "positive", "melhor sala", 6.0),
        ("sala-excelente", "positive", "sala excelente", 6.0),
        ("parabens", "positive", "parabens", 3.0),
        ("excelente-dia", "positive", "excelente dia", 6.0),
        ("excelente", "positive", "excelente", 3.0),
        ("show", "positive", "show", 2.0),
        ("mestre", "positive", "mestre", 3.0),
        ("valeu", "positive", "valeu", 2.0),
        ("obrigado", "positive", "obrigad", 3.0),
        ("nao-peguei", "negative", "nao peguei", -7.0),
        ("nao-entrei", "negative", "nao entrei", -7.0),
        ("nao-deu-tempo", "negative", "nao deu tempo", -7.0),
        ("loss", "negative", "loss", -5.0),
        ("simulador", "negative", "simulador", -4.0),
        ("perdi", "negative", "perdi", -4.0),
        ("perigoso", "negative", "perigoso", -3.0),
        ("deu-ruim", "negative", "deu ruim", -4.0),
        ("stop", "negative", "stop", -2.0),
        ("question", "negative", "?", -3.0),
    ]
    rules = [FeedbackRule(*values) for values in raw_rules]
    return SocialProofConfig(staff=staff, rules=rules)


def validate_social_proof_config(config: SocialProofConfig) -> None:
    if config.group_seconds < 0:
        raise ValueError("O intervalo de agrupamento não pode ser negativo.")
    if config.possible_threshold > config.strong_threshold:
        raise ValueError("O limite possível não pode superar o limite forte.")
    ids: set[str] = set()
    for position, member in enumerate(config.staff, 1):
        if not member.full_name.strip():
            raise ValueError(f"Professor {position}: informe o nome completo.")
        if member.id in ids:
            raise ValueError(f"ID repetido: {member.id}")
        ids.add(member.id)
    for position, rule in enumerate(config.rules, 1):
        if rule.kind not in RULE_KINDS:
            raise ValueError(f"Regra {position}: tipo inválido.")
        if not rule.expression.strip():
            raise ValueError(f"Regra {position}: informe uma palavra ou frase.")
        if rule.kind == "positive" and rule.score <= 0:
            raise ValueError(f"Regra {position}: uma regra positiva precisa somar pontos.")
        if rule.kind == "negative" and rule.score >= 0:
            raise ValueError(f"Regra {position}: uma regra negativa precisa retirar pontos.")
        if rule.id in ids:
            raise ValueError(f"ID repetido: {rule.id}")
        ids.add(rule.id)


def save_social_proof_config(
    config: SocialProofConfig,
    path: str | Path = "social_proof_rules.json",
) -> Path:
    validate_social_proof_config(config)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, **config.to_dict()}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def load_social_proof_config(
    path: str | Path = "social_proof_rules.json",
) -> SocialProofConfig:
    source = Path(path)
    if not source.exists():
        return default_social_proof_config()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Não foi possível ler as regras de prova social: {error}") from error
    config = SocialProofConfig(
        staff=[
            StaffMember(
                id=str(item.get("id", "")),
                full_name=str(item.get("full_name", "")),
                aliases=tuple(str(value) for value in item.get("aliases", [])),
                enabled=bool(item.get("enabled", True)),
            )
            for item in payload.get("staff", [])
            if isinstance(item, dict)
        ],
        rules=[
            FeedbackRule(
                id=str(item.get("id", "")),
                kind=str(item.get("kind", "")),
                expression=str(item.get("expression", "")),
                score=float(item.get("score", 0.0)),
                enabled=bool(item.get("enabled", True)),
            )
            for item in payload.get("rules", [])
            if isinstance(item, dict)
        ],
        group_seconds=float(payload.get("group_seconds", 60.0)),
        possible_threshold=float(payload.get("possible_threshold", 3.0)),
        strong_threshold=float(payload.get("strong_threshold", 6.0)),
        teacher_mention_bonus=float(payload.get("teacher_mention_bonus", 2.0)),
        reaction_bonus=float(payload.get("reaction_bonus", 1.0)),
    )
    validate_social_proof_config(config)
    return config


def staff_records(staff: Iterable[StaffMember]) -> list[dict[str, Any]]:
    return [
        {
            "Ativo": item.enabled,
            "Nome completo no Zoom": item.full_name,
            "Apelidos nas mensagens": ", ".join(item.aliases),
            "ID": item.id,
        }
        for item in staff
    ]


def staff_from_records(records: list[dict[str, Any]]) -> list[StaffMember]:
    values: list[StaffMember] = []
    for position, record in enumerate(records, 1):
        name = _clean_value(record.get("Nome completo no Zoom", ""))
        member_id = _clean_value(record.get("ID", ""))
        if not member_id:
            member_id = f"staff-{_digest(f'{name}-{position}')}"
        aliases = tuple(
            value.strip()
            for value in _clean_value(record.get("Apelidos nas mensagens", "")).split(",")
            if value.strip()
        )
        values.append(
            StaffMember(
                id=member_id,
                full_name=name,
                aliases=aliases,
                enabled=bool(record.get("Ativo", True)),
            )
        )
    return values


def feedback_rule_records(rules: Iterable[FeedbackRule]) -> list[dict[str, Any]]:
    return [
        {
            "Ativa": rule.enabled,
            "Tipo": RULE_KIND_LABELS[rule.kind],
            "Palavra ou frase": rule.expression,
            "Pontos": rule.score,
            "ID": rule.id,
        }
        for rule in rules
    ]


def feedback_rules_from_records(records: list[dict[str, Any]]) -> list[FeedbackRule]:
    values: list[FeedbackRule] = []
    for position, record in enumerate(records, 1):
        expression = _clean_value(record.get("Palavra ou frase", ""))
        kind_value = _clean_value(record.get("Tipo", ""))
        kind = LABEL_TO_RULE_KIND.get(kind_value, kind_value.lower())
        rule_id = _clean_value(record.get("ID", ""))
        if not rule_id:
            rule_id = f"feedback-{_digest(f'{kind}-{expression}-{position}')}"
        try:
            score = float(record.get("Pontos", 0.0))
        except (TypeError, ValueError):
            raise ValueError(f"Regra {position}: pontuação inválida.") from None
        values.append(
            FeedbackRule(
                id=rule_id,
                kind=kind,
                expression=expression,
                score=score,
                enabled=bool(record.get("Ativa", True)),
            )
        )
    return values


def parse_zoom_chat(source: str | Path) -> list[ZoomChatMessage]:
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Chat do Zoom não encontrado: {path}")
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    records: list[tuple[str, str, str]] = []
    current: list[str] | None = None
    for line in raw.splitlines():
        match = _CHAT_LINE_RE.match(line)
        if match:
            if current is not None:
                records.append((current[0], current[1], "\n".join(current[2:])))
            current = [match.group("time"), match.group("author"), match.group("text")]
        elif current is not None:
            current.append(line)
    if current is not None:
        records.append((current[0], current[1], "\n".join(current[2:])))

    messages: list[ZoomChatMessage] = []
    for index, (time_value, author, raw_text) in enumerate(records, 1):
        elapsed = _parse_elapsed(time_value)
        text = raw_text.strip()
        reaction_match = _REACTION_RE.match(text)
        if reaction_match:
            messages.append(
                ZoomChatMessage(
                    index,
                    elapsed,
                    author.strip(),
                    "",
                    "reaction",
                    reaction_match.group("quote").strip(),
                    reaction_match.group("emoji").strip(),
                )
            )
            continue
        reply_match = _REPLY_RE.match(text)
        if reply_match:
            reply = reply_match.group("reply").strip()
            messages.append(
                ZoomChatMessage(index, elapsed, author.strip(), reply, "reply")
            )
            continue
        messages.append(ZoomChatMessage(index, elapsed, author.strip(), text))
    return messages


def discover_zoom_chat_files(video_path: str | Path = "") -> list[Path]:
    video = Path(video_path) if video_path else None
    folder = video.parent if video and str(video).strip() else Path.cwd()
    if not folder.exists() or not folder.is_dir():
        return []
    candidates = {
        path.resolve()
        for pattern in ("*Chat.txt", "*chat.txt")
        for path in folder.glob(pattern)
        if path.is_file()
    }
    if not candidates:
        return []
    video_token_match = _FILENAME_RE.search(video.name) if video else None
    video_token = video_token_match.group(0).casefold() if video_token_match else ""
    return sorted(
        candidates,
        key=lambda path: (
            0 if video_token and video_token in path.name.casefold() else 1,
            path.name.casefold(),
        ),
    )


def infer_chat_date(source: str | Path, *, timezone_name: str = "America/Sao_Paulo") -> date:
    return infer_recording_datetime(source, timezone_name=timezone_name).date()


def infer_recording_datetime(
    source: str | Path,
    *,
    timezone_name: str = "America/Sao_Paulo",
) -> datetime:
    match = _FILENAME_RE.search(Path(source).name)
    if not match:
        return datetime.now(ZoneInfo(timezone_name))
    utc_value = datetime.strptime(
        match.group("date") + match.group("time"),
        "%Y%m%d%H%M%S",
    ).replace(tzinfo=timezone.utc)
    return utc_value.astimezone(ZoneInfo(timezone_name))


def analyze_zoom_chat(
    source: str | Path,
    config: SocialProofConfig,
    *,
    clock_adjustment_minutes: float = 0.0,
) -> list[FeedbackCandidate]:
    validate_social_proof_config(config)
    messages = parse_zoom_chat(source)
    if not messages:
        return []
    recording_start = infer_recording_datetime(source)
    first_elapsed = messages[0].elapsed
    clock_anchor = recording_start + timedelta(minutes=float(clock_adjustment_minutes))
    staff_names = {
        _normalize(member.full_name)
        for member in config.staff
        if member.enabled
    }
    teacher_aliases = tuple(
        _normalize(alias)
        for member in config.staff
        if member.enabled
        for alias in (member.full_name, *member.aliases)
        if _normalize(alias)
    )
    reactions: dict[str, int] = {}
    normal_messages: list[ZoomChatMessage] = []
    for message in messages:
        if message.kind == "reaction":
            quote = _normalize(message.quoted_text)
            if quote:
                reactions[quote] = reactions.get(quote, 0) + 1
        elif message.text.strip():
            normal_messages.append(message)

    groups = _group_messages(normal_messages, config.group_seconds)
    color_map = _participant_color_map(group[0].author for group in groups)
    candidates: list[FeedbackCandidate] = []
    for group in groups:
        author = group[0].author
        if _normalize(author) in staff_names:
            continue
        text = "\n".join(item.text.strip() for item in group if item.text.strip())
        normalized_text = _normalize(text)
        score, positive_score, reasons = _score_feedback_text(
            normalized_text,
            config,
            teacher_aliases,
        )
        if positive_score <= 0:
            continue
        reaction_count = sum(
            reactions.get(_normalize(item.text), 0)
            for item in group
        )
        if reaction_count:
            bonus = min(2.0, reaction_count * config.reaction_bonus)
            score += bonus
            reasons.append(f"+{bonus:g} reação no chat")
        if score < config.possible_threshold:
            continue
        classification = "Forte" if score >= config.strong_threshold else "Possível"
        start = group[0].elapsed
        end = group[-1].elapsed
        wall_time = clock_anchor + timedelta(seconds=start - first_elapsed)
        group_indices = {item.index for item in group}
        context = tuple(
            f"{clock_anchor + timedelta(seconds=item.elapsed - first_elapsed):%H:%M:%S}"
            f" · {item.author}: {item.text}"
            for item in normal_messages
            if item.index not in group_indices
            and start - 45 <= item.elapsed <= end + 45
        )
        candidate_id = f"feedback-{_digest(f'{author}-{start}-{text}')}"
        candidates.append(
            FeedbackCandidate(
                id=candidate_id,
                author=author,
                display_name=_first_name(author),
                start=start,
                end=end,
                wall_time=wall_time,
                text=text,
                avatar_color=color_map[author],
                score=round(score, 2),
                classification=classification,
                reasons=tuple(reasons),
                context=context,
            )
        )
    return sorted(candidates, key=lambda item: (item.start, item.author.casefold()))


def messages_in_clock_interval(
    source: str | Path,
    config: SocialProofConfig,
    start_clock: float,
    end_clock: float,
    *,
    clock_adjustment_minutes: float = 0.0,
) -> list[FeedbackCandidate]:
    """Return every non-staff chat message inside an inclusive wall-clock range."""
    validate_social_proof_config(config)
    start_value = float(start_clock)
    end_value = float(end_clock)
    if not 0.0 <= start_value < 86400.0 or not 0.0 <= end_value < 86400.0:
        raise ValueError("O intervalo precisa usar horários válidos entre 00:00:00 e 23:59:59.")
    if end_value < start_value:
        raise ValueError("O horário final precisa ser igual ou posterior ao horário inicial.")

    messages = parse_zoom_chat(source)
    if not messages:
        return []
    recording_start = infer_recording_datetime(source)
    first_elapsed = messages[0].elapsed
    clock_anchor = recording_start + timedelta(minutes=float(clock_adjustment_minutes))
    staff_names = {
        _normalize(member.full_name)
        for member in config.staff
        if member.enabled
    }
    teacher_aliases = tuple(
        _normalize(alias)
        for member in config.staff
        if member.enabled
        for alias in (member.full_name, *member.aliases)
        if _normalize(alias)
    )
    reactions: dict[str, int] = {}
    normal_messages: list[ZoomChatMessage] = []
    for message in messages:
        if message.kind == "reaction":
            quote = _normalize(message.quoted_text)
            if quote:
                reactions[quote] = reactions.get(quote, 0) + 1
        elif message.text.strip():
            normal_messages.append(message)

    eligible_messages = [
        message
        for message in normal_messages
        if _normalize(message.author) not in staff_names
    ]
    color_map = _participant_color_map(message.author for message in eligible_messages)
    candidates: list[FeedbackCandidate] = []
    for message in eligible_messages:
        wall_time = clock_anchor + timedelta(seconds=message.elapsed - first_elapsed)
        wall_seconds = (
            wall_time.hour * 3600 + wall_time.minute * 60 + wall_time.second
        )
        if wall_seconds < start_value or wall_seconds > end_value:
            continue
        normalized_text = _normalize(message.text)
        score, positive_score, reasons = _score_feedback_text(
            normalized_text,
            config,
            teacher_aliases,
        )
        reaction_count = reactions.get(normalized_text, 0)
        if reaction_count:
            bonus = min(2.0, reaction_count * config.reaction_bonus)
            score += bonus
            reasons.append(f"+{bonus:g} reação no chat")
        if positive_score > 0 and score >= config.strong_threshold:
            classification = "Forte"
        elif positive_score > 0 and score >= config.possible_threshold:
            classification = "Possível"
        else:
            classification = "Sem destaque"
        context = tuple(
            f"{clock_anchor + timedelta(seconds=item.elapsed - first_elapsed):%H:%M:%S}"
            f" · {item.author}: {item.text}"
            for item in normal_messages
            if item.index != message.index
            and message.elapsed - 45 <= item.elapsed <= message.elapsed + 45
        )
        candidates.append(
            FeedbackCandidate(
                id=(
                    "interval-"
                    + _digest(
                        f"{message.index}-{message.author}-{message.elapsed}-{message.text}"
                    )
                ),
                author=message.author,
                display_name=_first_name(message.author),
                start=message.elapsed,
                end=message.elapsed,
                wall_time=wall_time,
                text=message.text,
                avatar_color=color_map[message.author],
                score=round(score, 2),
                classification=classification,
                reasons=tuple(reasons or ["Dentro do intervalo selecionado"]),
                context=context,
            )
        )
    return sorted(candidates, key=lambda item: (item.start, item.author.casefold()))


def render_feedback_panels(
    candidates: Iterable[FeedbackCandidate],
    feedback_date: date,
    *,
    page_sizes: Iterable[int] | None = None,
) -> list[bytes]:
    values = list(candidates)
    if not values:
        return []
    pages = plan_feedback_pages(values, page_sizes=page_sizes)
    overflowing = [
        index
        for index, page in enumerate(pages, 1)
        if feedback_page_occupancy(page) > 1.0
    ]
    if overflowing:
        labels = ", ".join(str(index) for index in overflowing)
        raise ValueError(
            f"A página {labels} ultrapassa a área segura. Reduza a quantidade ou mude a ordem."
        )
    return [
        _render_feedback_page(page, feedback_date, page_index=index, page_count=len(pages))
        for index, page in enumerate(pages, 1)
    ]


def estimate_feedback_video_duration(
    candidates: Iterable[FeedbackCandidate],
    *,
    page_sizes: Iterable[int] | None = None,
    comment_interval: float = 1.2,
    page_pause: float = 1.0,
    final_hold: float = 2.0,
) -> float:
    pages = plan_feedback_pages(candidates, page_sizes=page_sizes)
    _validate_video_timing(comment_interval, page_pause, final_hold)
    if not pages:
        return 0.0
    duration = len(pages) * VIDEO_PAGE_INTRO_SECONDS + final_hold
    for page_index, page in enumerate(pages):
        duration += len(page) * VIDEO_FADE_SECONDS
        duration += max(0, len(page) - 1) * (comment_interval - VIDEO_FADE_SECONDS)
        if page_index < len(pages) - 1:
            duration += page_pause
    return duration


def render_feedback_video(
    candidates: Iterable[FeedbackCandidate],
    feedback_date: date,
    output_path: str | Path,
    *,
    page_sizes: Iterable[int] | None = None,
    comment_interval: float = 1.2,
    page_pause: float = 1.0,
    final_hold: float = 2.0,
    notification_sound: bool = True,
    notification_volume: float = 0.25,
    ffmpeg_path: str = "",
) -> SocialProofVideoResult:
    """Render an independent vertical MP4 with cumulative Zoom-like feedbacks."""
    values = list(candidates)
    if not values:
        raise ValueError("Selecione ao menos um depoimento para gerar o vídeo.")
    pages = plan_feedback_pages(values, page_sizes=page_sizes)
    overflowing = [
        index
        for index, page in enumerate(pages, 1)
        if feedback_page_occupancy(page) > 1.0
    ]
    if overflowing:
        labels = ", ".join(str(index) for index in overflowing)
        raise ValueError(
            f"A página {labels} ultrapassa a área segura. Reduza a quantidade ou mude a ordem."
        )
    _validate_video_timing(comment_interval, page_pause, final_hold)
    if not 0.0 <= notification_volume <= 1.0:
        raise ValueError("O volume da notificação precisa ficar entre 0 e 1.")

    target = Path(output_path)
    if target.suffix.casefold() != ".mp4":
        raise ValueError("O vídeo de prova social precisa usar a extensão .mp4.")
    target.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg(ffmpeg_path)

    with tempfile.TemporaryDirectory(
        prefix=".social-proof-video-", dir=str(target.parent)
    ) as temporary:
        temp_dir = Path(temporary)
        timeline, notification_times, duration = _feedback_video_timeline(
            pages,
            feedback_date,
            comment_interval=comment_interval,
            page_pause=page_pause,
            final_hold=final_hold,
        )
        concat_lines = ["ffconcat version 1.0"]
        last_frame_path: Path | None = None
        for index, (content, frame_duration) in enumerate(timeline):
            frame_path = temp_dir / f"frame-{index:04d}.png"
            frame_path.write_bytes(content)
            escaped_path = frame_path.resolve().as_posix().replace("'", "'\\''")
            concat_lines.append(f"file '{escaped_path}'")
            concat_lines.append(f"duration {frame_duration:.6f}")
            last_frame_path = frame_path
        if last_frame_path is None:
            raise RuntimeError("Não foi possível montar os quadros do vídeo de prova social.")
        escaped_last = last_frame_path.resolve().as_posix().replace("'", "'\\''")
        concat_lines.append(f"file '{escaped_last}'")
        concat_path = temp_dir / "timeline.ffconcat"
        concat_path.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")

        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
        ]
        audio_map = "1:a:0"
        filter_complex = ""
        if notification_sound and notification_times:
            for _ in notification_times:
                command.extend(
                    [
                        "-f",
                        "lavfi",
                        "-i",
                        "sine=frequency=1040:sample_rate=48000:duration=0.160",
                    ]
                )
            filters: list[str] = []
            labels: list[str] = []
            for index, start in enumerate(notification_times, 1):
                label = f"pop{index}"
                delay_ms = max(0, round(start * 1000))
                filters.append(
                    f"[{index}:a]volume={notification_volume:.3f},"
                    "afade=t=in:st=0:d=0.008,"
                    "afade=t=out:st=0.035:d=0.125,"
                    f"adelay={delay_ms}:all=1[{label}]"
                )
                labels.append(f"[{label}]")
            if len(labels) == 1:
                filters.append(
                    f"{labels[0]}apad=whole_dur={duration:.6f}[socialaudio]"
                )
            else:
                filters.append(
                    "".join(labels)
                    + f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
                    + f"apad=whole_dur={duration:.6f}[socialaudio]"
                )
            filter_complex = ";".join(filters)
            audio_map = "[socialaudio]"
        else:
            command.extend(
                [
                    "-f",
                    "lavfi",
                    "-t",
                    f"{duration:.6f}",
                    "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=48000",
                ]
            )

        if filter_complex:
            command.extend(["-filter_complex", filter_complex])
        command.extend(
            [
                "-map",
                "0:v:0",
                "-map",
                audio_map,
                "-t",
                f"{duration:.6f}",
                "-vf",
                "fps=30,format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-threads:v",
                "2",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-movflags",
                "+faststart",
                str(target),
            ]
        )
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(
                "FFmpeg não conseguiu gerar o vídeo de prova social:\n"
                + completed.stderr.strip()
            )

    return SocialProofVideoResult(
        path=target,
        duration=duration,
        comment_count=len(values),
        page_count=len(pages),
    )


def plan_feedback_pages(
    candidates: Iterable[FeedbackCandidate],
    *,
    page_sizes: Iterable[int] | None = None,
) -> list[list[FeedbackCandidate]]:
    values = list(candidates)
    if not values:
        return []
    if page_sizes is None:
        return _paginate_candidates(values)
    sizes = [int(value) for value in page_sizes]
    if not sizes:
        raise ValueError("Informe ao menos uma quantidade para a paginação manual.")
    if any(value < 1 or value > MAX_COMMENTS_PER_PAGE for value in sizes):
        raise ValueError(
            f"Cada página precisa ter entre 1 e {MAX_COMMENTS_PER_PAGE} comentários."
        )
    if sum(sizes) != len(values):
        raise ValueError(
            f"A distribuição soma {sum(sizes)}, mas {len(values)} depoimentos estão selecionados."
        )
    pages: list[list[FeedbackCandidate]] = []
    cursor = 0
    for size in sizes:
        pages.append(values[cursor:cursor + size])
        cursor += size
    return pages


def _validate_video_timing(
    comment_interval: float,
    page_pause: float,
    final_hold: float,
) -> None:
    if comment_interval < VIDEO_FADE_SECONDS + 0.05:
        raise ValueError(
            f"O intervalo entre comentários precisa ser de pelo menos "
            f"{VIDEO_FADE_SECONDS + 0.05:.2f} segundo."
        )
    if page_pause < 0.1:
        raise ValueError("A pausa entre páginas precisa ser de pelo menos 0,1 segundo.")
    if final_hold < 0.1:
        raise ValueError("A pausa final precisa ser de pelo menos 0,1 segundo.")


def _feedback_video_timeline(
    pages: list[list[FeedbackCandidate]],
    feedback_date: date,
    *,
    comment_interval: float,
    page_pause: float,
    final_hold: float,
) -> tuple[list[tuple[bytes, float]], list[float], float]:
    timeline: list[tuple[bytes, float]] = []
    notification_times: list[float] = []
    cursor = 0.0
    for page_index, page in enumerate(pages, 1):
        states = [
            _render_feedback_page(
                page,
                feedback_date,
                page_index=page_index,
                page_count=len(pages),
                visible_count=visible_count,
            )
            for visible_count in range(len(page) + 1)
        ]
        timeline.append((states[0], VIDEO_PAGE_INTRO_SECONDS))
        cursor += VIDEO_PAGE_INTRO_SECONDS
        for candidate_index in range(1, len(states)):
            notification_times.append(cursor)
            for fade_step in range(1, VIDEO_FADE_STEPS + 1):
                timeline.append(
                    (
                        _blend_pngs(
                            states[candidate_index - 1],
                            states[candidate_index],
                            fade_step / VIDEO_FADE_STEPS,
                        ),
                        VIDEO_FADE_SECONDS / VIDEO_FADE_STEPS,
                    )
                )
            cursor += VIDEO_FADE_SECONDS
            is_page_last = candidate_index == len(page)
            is_video_last = is_page_last and page_index == len(pages)
            if is_video_last:
                hold = final_hold
            elif is_page_last:
                hold = page_pause
            else:
                hold = comment_interval - VIDEO_FADE_SECONDS
            timeline.append((states[candidate_index], hold))
            cursor += hold
    return timeline, notification_times, cursor


def _blend_pngs(before: bytes, after: bytes, amount: float) -> bytes:
    with Image.open(BytesIO(before)) as before_source:
        before_image = before_source.convert("RGB")
    with Image.open(BytesIO(after)) as after_source:
        after_image = after_source.convert("RGB")
    blended = Image.blend(before_image, after_image, max(0.0, min(1.0, amount)))
    output = BytesIO()
    blended.save(output, format="PNG", optimize=True)
    return output.getvalue()


def feedback_page_occupancy(candidates: Iterable[FeedbackCandidate]) -> float:
    values = list(candidates)
    if not values:
        return 0.0
    font = _font(34)
    used = sum(_feedback_block_height(item, font) for item in values)
    return used / (CONTENT_BOTTOM - CONTENT_TOP)


def render_safe_area_preview(content: bytes) -> bytes:
    """Overlay non-exported guides that reveal social-network dead zones."""
    with Image.open(BytesIO(content)) as source:
        image = source.convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    dead_fill = (220, 38, 38, 58)
    guide = (248, 113, 113, 210)
    draw.rectangle((0, 0, OUTPUT_SIZE[0], SAFE_TOP), fill=dead_fill)
    draw.rectangle((0, SAFE_BOTTOM, OUTPUT_SIZE[0], OUTPUT_SIZE[1]), fill=dead_fill)
    draw.rectangle((0, SAFE_TOP, SAFE_LEFT, SAFE_BOTTOM), fill=dead_fill)
    draw.rectangle((SAFE_RIGHT, SAFE_TOP, OUTPUT_SIZE[0], SAFE_BOTTOM), fill=dead_fill)
    draw.line((SAFE_LEFT, SAFE_TOP, SAFE_RIGHT, SAFE_TOP), fill=guide, width=4)
    draw.line((SAFE_LEFT, SAFE_BOTTOM, SAFE_RIGHT, SAFE_BOTTOM), fill=guide, width=4)
    draw.line((SAFE_LEFT, SAFE_TOP, SAFE_LEFT, SAFE_BOTTOM), fill=guide, width=4)
    draw.line((SAFE_RIGHT, SAFE_TOP, SAFE_RIGHT, SAFE_BOTTOM), fill=guide, width=4)
    label_font = _font(22, bold=True)
    draw.text(
        (SAFE_LEFT + 20, 24),
        "ZONA MORTA · NÃO EXPORTADA",
        font=label_font,
        fill="#FFFFFF",
    )
    draw.text(
        (SAFE_LEFT + 20, SAFE_BOTTOM + 24),
        "ZONA MORTA · NÃO EXPORTADA",
        font=label_font,
        fill="#FFFFFF",
    )
    image = Image.alpha_composite(image, overlay).convert("RGB")
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def render_individual_feedback(
    candidate: FeedbackCandidate,
    feedback_date: date,
) -> bytes:
    if feedback_page_occupancy([candidate]) > 1.0:
        raise ValueError("Este depoimento é longo demais para a área segura da arte individual.")
    return _render_feedback_page([candidate], feedback_date, page_index=1, page_count=1)


def save_approved_feedbacks(
    target: str | Path,
    candidates: Iterable[FeedbackCandidate],
    feedback_date: date,
    *,
    source_chat: str | Path,
) -> Path:
    output = Path(target)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(
        approved_feedbacks_json(candidates, feedback_date, source_chat=source_chat)
    )
    return output


def approved_feedbacks_json(
    candidates: Iterable[FeedbackCandidate],
    feedback_date: date,
    *,
    source_chat: str | Path,
) -> bytes:
    payload = {
        "version": 1,
        "date": feedback_date.isoformat(),
        "source_chat": str(Path(source_chat).resolve()),
        "feedbacks": [item.to_dict() for item in candidates],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _score_feedback_text(
    normalized_text: str,
    config: SocialProofConfig,
    teacher_aliases: Iterable[str],
) -> tuple[float, float, list[str]]:
    score = 0.0
    positive_score = 0.0
    reasons: list[str] = []
    for rule in config.rules:
        if not rule.enabled:
            continue
        expression = _normalize(rule.expression)
        if expression and expression in normalized_text:
            score += rule.score
            if rule.score > 0:
                positive_score += rule.score
            sign = "+" if rule.score > 0 else ""
            reasons.append(f'{sign}{rule.score:g} “{rule.expression}”')
    if any(_contains_phrase(normalized_text, alias) for alias in teacher_aliases):
        score += config.teacher_mention_bonus
        reasons.append(f"+{config.teacher_mention_bonus:g} menção a professor")
    return score, positive_score, reasons


def _group_messages(
    messages: list[ZoomChatMessage],
    group_seconds: float,
) -> list[list[ZoomChatMessage]]:
    groups: list[list[ZoomChatMessage]] = []
    for message in messages:
        author_key = _normalize(message.author)
        if (
            groups
            and _normalize(groups[-1][0].author) == author_key
            and message.elapsed - groups[-1][-1].elapsed <= group_seconds
        ):
            groups[-1].append(message)
        else:
            groups.append([message])
    return groups


def _paginate_candidates(values: list[FeedbackCandidate]) -> list[list[FeedbackCandidate]]:
    font = _font(34)
    maximum_height = CONTENT_BOTTOM - CONTENT_TOP
    pages: list[list[FeedbackCandidate]] = []
    used_heights: list[int] = []
    for candidate in values:
        height = _feedback_block_height(candidate, font)
        target_index = next(
            (
                index
                for index, page in enumerate(pages)
                if len(page) < MAX_COMMENTS_PER_PAGE
                and used_heights[index] + height <= maximum_height
            ),
            None,
        )
        if target_index is None:
            pages.append([candidate])
            used_heights.append(height)
        else:
            pages[target_index].append(candidate)
            used_heights[target_index] += height
    return pages


def _render_feedback_page(
    candidates: list[FeedbackCandidate],
    feedback_date: date,
    *,
    page_index: int,
    page_count: int,
    visible_count: int | None = None,
) -> bytes:
    image = Image.new("RGB", OUTPUT_SIZE, "#101316")
    draw = ImageDraw.Draw(image)
    gold = "#F5A623"
    white = "#F5F7FA"
    muted = "#AAB2BD"
    blue = "#4DA3FF"
    draw.rectangle((0, 0, OUTPUT_SIZE[0], 12), fill=gold)
    draw.text(
        (SAFE_LEFT, 250),
        "SALA RAFAEL FOSSALUSSA",
        font=_font(25, bold=True),
        fill=gold,
    )
    draw.text((SAFE_LEFT, 296), "RESULTADOS DA SALA", font=_font(58, bold=True), fill=white)
    date_text = (
        f"{feedback_date.day:02d} DE {_PORTUGUESE_MONTHS[feedback_date.month - 1]} "
        f"DE {feedback_date.year}"
    )
    draw.text((SAFE_LEFT, 372), date_text, font=_font(27, bold=True), fill=muted)
    badge_box = (710, 246, SAFE_RIGHT, 298)
    draw.rounded_rectangle(badge_box, radius=16, fill="#20262C", outline="#374151", width=2)
    draw.text((815, 272), "CHAT DO ZOOM", font=_font(20, bold=True), fill=blue, anchor="mm")
    draw.line((SAFE_LEFT, 430, SAFE_RIGHT, 430), fill="#2A3138", width=2)

    message_font = _font(34)
    header_font = _font(24)
    small_font = _font(21)
    used_height = sum(_feedback_block_height(item, message_font) for item in candidates)
    available_height = CONTENT_BOTTOM - CONTENT_TOP
    distributed_gap = max(0.0, (available_height - used_height) / (len(candidates) + 1))
    y = CONTENT_TOP + distributed_gap
    visible_candidates = (
        candidates if visible_count is None else candidates[:max(0, visible_count)]
    )
    for candidate in visible_candidates:
        avatar_x, avatar_y = AVATAR_X, y + 38
        avatar_size = 68
        color = candidate.avatar_color
        draw.rounded_rectangle(
            (avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size),
            radius=16,
            fill=color,
        )
        draw.text(
            (avatar_x + avatar_size / 2, avatar_y + avatar_size / 2),
            _avatar_text(candidate.display_name),
            font=_font(25, bold=True),
            fill="#FFFFFF",
            anchor="mm",
        )
        header_x = BUBBLE_LEFT + 8
        draw.text((header_x, y), candidate.display_name, font=header_font, fill="#D6DADE")
        name_width = draw.textlength(candidate.display_name, font=header_font)
        everyone_x = header_x + name_width + 10
        draw.text((everyone_x, y), "to Everyone", font=small_font, fill=blue)
        everyone_width = draw.textlength("to Everyone", font=small_font)
        draw.text(
            (everyone_x + everyone_width + 10, y),
            candidate.wall_time.strftime("%H:%M"),
            font=small_font,
            fill="#929AA3",
        )

        lines = _wrap_pixel(candidate.text, message_font, MESSAGE_TEXT_WIDTH)
        line_height = 43
        bubble_height = max(68, len(lines) * line_height + 30)
        bubble = (BUBBLE_LEFT, y + 36, SAFE_RIGHT, y + 36 + bubble_height)
        draw.rounded_rectangle(bubble, radius=22, fill="#2B2D2F")
        text_y = y + 49
        for line in lines:
            draw.text((TEXT_LEFT, text_y), line, font=message_font, fill="#FFFFFF")
            text_y += line_height
        y = bubble[3] + 34 + distributed_gap

    footer_y = 1570
    draw.line((SAFE_LEFT, footer_y, SAFE_RIGHT, footer_y), fill="#2A3138", width=2)
    draw.text(
        (SAFE_LEFT, footer_y + 34),
        "Recriado a partir do chat original da sala",
        font=_font(22),
        fill="#89929C",
    )
    if page_count > 1:
        draw.text(
            (SAFE_RIGHT, footer_y + 34),
            f"{page_index}/{page_count}",
            font=_font(24, bold=True),
            fill=gold,
            anchor="ra",
        )
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _message_height(text: str, font: ImageFont.ImageFont, width: int) -> int:
    return max(68, len(_wrap_pixel(text, font, width)) * 43 + 30)


def _feedback_block_height(
    candidate: FeedbackCandidate,
    font: ImageFont.ImageFont,
) -> int:
    return _message_height(candidate.text, font, MESSAGE_TEXT_WIDTH) + 70


def _wrap_pixel(text: str, font: ImageFont.ImageFont, width: int) -> list[str]:
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            proposed = f"{current} {word}"
            if probe.textlength(proposed, font=font) <= width:
                current = proposed
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines or [""]


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = _FONT_BOLD if bold else _FONT_REGULAR
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    fallback = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(fallback, size=size)
    except OSError:
        return ImageFont.load_default(size=size)


def _participant_color_map(authors: Iterable[str]) -> dict[str, str]:
    unique_authors = sorted(set(authors), key=lambda value: _normalize(value))
    used_by_first_name: dict[str, set[int]] = {}
    colors: dict[str, str] = {}
    for author in unique_authors:
        first_name = _normalize(_first_name(author))
        used = used_by_first_name.setdefault(first_name, set())
        digest = hashlib.sha1(_normalize(author).encode("utf-8")).digest()
        color_index = digest[0] % len(ZOOM_COLORS)
        for _ in ZOOM_COLORS:
            if color_index not in used:
                break
            color_index = (color_index + 1) % len(ZOOM_COLORS)
        used.add(color_index)
        colors[author] = ZOOM_COLORS[color_index]
    return colors


def _avatar_text(display_name: str) -> str:
    value = display_name.strip()
    return value[:1].upper() if value else "?"


def _first_name(full_name: str) -> str:
    values = full_name.strip().split()
    return values[0] if values else "Participante"


def _contains_phrase(text: str, expression: str) -> bool:
    return bool(expression and re.search(rf"(?<!\w){re.escape(expression)}(?!\w)", text))


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", normalized).strip()


def _parse_elapsed(value: str) -> float:
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def _elapsed_text(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _digest(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def _clean_value(value: Any) -> str:
    if value is None:
        return ""
    try:
        if value != value:
            return ""
    except TypeError:
        pass
    return str(value).strip()
