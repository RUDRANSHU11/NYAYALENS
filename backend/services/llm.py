"""LLM transport: one code path for any OpenAI-compatible chat-completions API.

Gemini (default), OpenAI, Groq, OpenRouter and a local Ollama all speak this
shape, so "configurable LLM provider" is three environment variables rather than
an SDK per vendor. The API key never leaves the server.

Calls are async: a model round trip takes seconds, and holding a worker thread
for each one caps concurrency at the size of the threadpool. On the event loop
the same process can have many requests in flight, all sharing one pooled
connection.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re

import httpx

from backend import config

log = logging.getLogger(__name__)

_RETRY_STATUS = {429, 500, 502, 503, 504}
_JSON_BLOCK = re.compile(r"\{.*\}|\[.*\]", re.DOTALL)

_client: httpx.AsyncClient | None = None
_lock = asyncio.Lock()


class LLMError(RuntimeError):
    """Any failure talking to the model provider, safe to show to a user."""

    def __init__(self, message: str = "The AI service is unavailable right now.") -> None:
        super().__init__(message)


class LLMNotConfigured(LLMError):
    def __init__(self) -> None:
        super().__init__("No AI provider is configured on the server.")


def is_configured() -> bool:
    return bool(config.LLM_API_KEY)


async def aclose() -> None:
    """Close the pooled client. Called from the app's shutdown hook."""
    global _client
    async with _lock:
        if _client is not None:
            await _client.aclose()
        _client = None


async def complete(
    messages: list[dict], *, temperature: float = 0.2, max_tokens: int = 1200
) -> str:
    """Send a chat completion and return the assistant's text."""
    if not is_configured():
        raise LLMNotConfigured()

    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    client = await _http()

    for attempt in range(2):
        try:
            response = await client.post("/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            log.warning("LLM request failed: %s", exc)
            if attempt:
                raise LLMError() from exc
            continue

        if response.status_code in _RETRY_STATUS and attempt == 0:
            await asyncio.sleep(1)
            continue
        if response.status_code >= 400:
            # Provider errors can quote the prompt back; log a short prefix only.
            log.error("LLM returned HTTP %s: %s", response.status_code, response.text[:200])
            raise LLMError()

        try:
            return response.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError("The AI service returned an unexpected response.") from exc

    raise LLMError()


async def complete_json(messages: list[dict], **kwargs) -> dict | list:
    """Send a chat completion whose prompt asks for JSON, and parse it."""
    text = (await complete(messages, **kwargs)).strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
    try:
        return json.loads(text)
    except ValueError:
        pass
    match = _JSON_BLOCK.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except ValueError:
            pass
    raise LLMError("The AI service returned an unreadable response.")


def image_part(png: bytes) -> dict:
    """An OpenAI-style image content part, for OCR of scanned pages."""
    encoded = base64.b64encode(png).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}}


async def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        async with _lock:
            if _client is None:
                _client = httpx.AsyncClient(
                    base_url=config.LLM_BASE_URL,
                    timeout=config.LLM_TIMEOUT,
                    headers={
                        "Authorization": f"Bearer {config.LLM_API_KEY}",
                        "Content-Type": "application/json",
                    },
                )
    return _client
