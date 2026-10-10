"""Direct streaming clients (no agent runtime). Used by the 'direct' engine and as the
automatic fallback when the Agent SDK engine cannot start."""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from app.config import Settings
from app.errors import (ProviderNotConfiguredError, ProviderResponseError, ProviderTimeoutError,
                        ProviderUnavailableError)
from app.llm.providers import ProviderSpec


async def stream_ollama(settings: Settings, spec: ProviderSpec, system: str, messages: list[dict],
                        max_tokens: int) -> AsyncIterator[str]:
    payload = {
        "model": spec.model,
        "messages": [{"role": "system", "content": system}, *messages],
        "stream": True,
        "keep_alive": settings.ollama_keep_alive,
        "options": {"temperature": settings.llm_temperature, "num_ctx": settings.ollama_num_ctx,
                    "num_predict": max_tokens},
    }
    timeout = httpx.Timeout(settings.llm_timeout_s, connect=5.0)
    try:
        async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=timeout) as client:
            async with client.stream("POST", "/api/chat", json=payload) as resp:
                if resp.status_code == 404:
                    raise ProviderUnavailableError(f"Model '{spec.model}' not found in Ollama",
                                                   hint=f"Run: ollama pull {spec.model}")
                if resp.status_code != 200:
                    body = (await resp.aread()).decode(errors="ignore")[:300]
                    raise ProviderResponseError(f"Ollama error {resp.status_code}: {body}")
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if data.get("error"):
                        raise ProviderResponseError(f"Ollama: {data['error']}")
                    piece = (data.get("message") or {}).get("content")
                    if piece:
                        yield piece
                    if data.get("done"):
                        break
    except httpx.TimeoutException as exc:
        raise ProviderTimeoutError(f"Ollama timed out after {settings.llm_timeout_s}s") from exc
    except httpx.ConnectError as exc:
        raise ProviderUnavailableError(f"Cannot reach Ollama at {settings.ollama_base_url}") from exc


async def stream_anthropic(settings: Settings, spec: ProviderSpec, system: str, messages: list[dict],
                           max_tokens: int) -> AsyncIterator[str]:
    if not settings.anthropic_configured:
        raise ProviderNotConfiguredError("ANTHROPIC_API_KEY is not set")
    headers = {"x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    payload = {"model": spec.model, "system": system, "messages": messages, "stream": True,
               "max_tokens": max_tokens, "temperature": settings.llm_temperature}
    timeout = httpx.Timeout(settings.llm_timeout_s, connect=10.0)
    try:
        async with httpx.AsyncClient(base_url=settings.anthropic_base_url, timeout=timeout) as client:
            async with client.stream("POST", "/v1/messages", json=payload, headers=headers) as resp:
                if resp.status_code in (401, 403):
                    raise ProviderNotConfiguredError("Anthropic rejected the API key",
                                                     hint="Check ANTHROPIC_API_KEY in .env.")
                if resp.status_code != 200:
                    body = (await resp.aread()).decode(errors="ignore")[:300]
                    raise ProviderResponseError(f"Anthropic error {resp.status_code}: {body}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = json.loads(line[5:].strip() or "{}")
                    if data.get("type") == "content_block_delta":
                        text = (data.get("delta") or {}).get("text")
                        if text:
                            yield text
                    elif data.get("type") == "error":
                        raise ProviderResponseError(f"Anthropic: {data.get('error')}")
    except httpx.TimeoutException as exc:
        raise ProviderTimeoutError(f"Anthropic timed out after {settings.llm_timeout_s}s") from exc
    except httpx.ConnectError as exc:
        raise ProviderUnavailableError("Cannot reach api.anthropic.com",
                                       hint="Check network access or switch to Ollama.") from exc
