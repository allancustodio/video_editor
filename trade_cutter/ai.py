from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import replace
from typing import Any

from .models import Cue, Operation
from .timecode import format_timecode, parse_timecode
from .vtt import transcript_between


OPERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_operation": {"type": "boolean"},
        "title": {"type": "string"},
        "asset": {"type": "string"},
        "direction": {"type": "string", "enum": ["compra", "venda", ""]},
        "setup_start": {"type": ["string", "null"]},
        "entry_time": {"type": "string"},
        "operation_end": {"type": "string"},
        "result": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "is_operation",
        "title",
        "asset",
        "direction",
        "setup_start",
        "entry_time",
        "operation_end",
        "result",
        "confidence",
        "evidence",
    ],
    "additionalProperties": False,
}


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None, timeout: int = 180) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Erro HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Não foi possível acessar {url}: {error.reason}") from error


def _prompt(operation: Operation, transcript: str) -> str:
    return f"""Você analisa transcrições de uma sala de day trade em português do Brasil.
Valide se o trecho contém uma operação realmente executada pelo apresentador, não apenas uma hipótese, exemplo ou operação de outro participante.

Regras:
- setup_start: início da explicação/preparação relevante.
- entry_time: momento em que a entrada ocorreu ou foi confirmada.
- operation_end: último alvo, stop, zeragem, retirada de risco ou explicação final diretamente ligada à operação.
- Não invente horários; use timestamps presentes no trecho.
- Se não houver operação real, is_operation=false.
- confidence deve refletir a clareza da evidência.

Candidato das regras locais:
- Título: {operation.title}
- Entrada estimada: {format_timecode(operation.entry_time)}
- Resultado estimado: {operation.result}

TRANSCRIÇÃO:
{transcript}
"""


def _ollama(prompt: str, model: str, base_url: str) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": OPERATION_SCHEMA,
        "options": {"temperature": 0},
    }
    result = _post_json(f"{base_url.rstrip('/')}/api/chat", payload)
    content = result.get("message", {}).get("content", "")
    if not content:
        raise RuntimeError("O Ollama não retornou conteúdo.")
    return json.loads(content)


def _gemini(prompt: str, model: str, api_key: str) -> dict[str, Any]:
    if not api_key:
        raise RuntimeError("Defina GEMINI_API_KEY ou informe a chave na interface.")
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": OPERATION_SCHEMA,
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    result = _post_json(url, payload, headers={"x-goog-api-key": api_key})
    try:
        content = result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as error:
        raise RuntimeError(f"Resposta inesperada do Gemini: {result}") from error
    return json.loads(content)


def refine_operations(
    cues: list[Cue],
    operations: list[Operation],
    provider: str,
    model: str,
    *,
    ollama_url: str = "http://localhost:11434",
    gemini_api_key: str = "",
    keep_rejected: bool = False,
) -> list[Operation]:
    refined: list[Operation] = []
    for operation in operations:
        window_start = max(0.0, operation.cut_start - 75)
        window_end = operation.cut_end + 75
        transcript = transcript_between(cues, window_start, window_end)
        prompt = _prompt(operation, transcript)

        if provider == "ollama":
            response = _ollama(prompt, model=model, base_url=ollama_url)
        elif provider == "gemini":
            response = _gemini(prompt, model=model, api_key=gemini_api_key or os.getenv("GEMINI_API_KEY", ""))
        else:
            raise ValueError(f"Provedor desconhecido: {provider}")

        if not response.get("is_operation", False):
            if keep_rejected:
                refined.append(replace(operation, selected=False, source=f"{provider}:rejected"))
            continue

        setup_start = parse_timecode(response.get("setup_start"))
        entry_time = parse_timecode(response.get("entry_time")) or operation.entry_time
        operation_end = parse_timecode(response.get("operation_end")) or operation.operation_end
        cut_start = max(0.0, (setup_start - 10) if setup_start is not None else entry_time - 45)
        cut_end = max(cut_start + 15, operation_end + 25)

        confidence = float(response.get("confidence", operation.confidence))
        evidence = [str(item) for item in response.get("evidence", []) if str(item).strip()][:8]
        refined.append(
            replace(
                operation,
                title=str(response.get("title") or operation.title),
                asset=str(response.get("asset") or operation.asset),
                direction=str(response.get("direction") or operation.direction),
                setup_start=setup_start,
                entry_time=entry_time,
                operation_end=operation_end,
                cut_start=cut_start,
                cut_end=cut_end,
                result=str(response.get("result") or operation.result),
                confidence=max(0.0, min(1.0, confidence)),
                evidence=evidence or operation.evidence,
                selected=confidence >= 0.62,
                source=provider,
            )
        )
    return refined
