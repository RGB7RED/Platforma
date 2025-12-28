"""LLM provider abstraction and helpers."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

import httpx


class LLMProviderError(RuntimeError):
    """Error raised when an LLM provider request fails."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class LLMProvider(Protocol):
    name: str

    async def generate_text(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        response_format: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Generate text from provider. Returns dict with text and usage."""


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str
    api_key: Optional[str]
    max_tokens: int
    timeout_seconds: float
    temperature: float


def load_llm_settings() -> LLMSettings:
    provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()
    model = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()
    api_key = os.getenv("LLM_API_KEY")
    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "1024"))
    timeout_seconds = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.2"))
    return LLMSettings(
        provider=provider,
        model=model,
        api_key=api_key,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
        temperature=temperature,
    )


class MockProvider:
    name = "mock"

    async def generate_text(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        response_format: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        prompt = messages[-1]["content"] if messages else ""
        path = "generated.py"
        task_line = "Implement requested changes."
        try:
            payload = json.loads(prompt)
            path = payload.get("Target file") or payload.get("Target file", path)
            task_line = payload.get("Task", task_line)
        except json.JSONDecodeError:
            path = _extract_between(prompt, "Target file:", "\n") or path
            task_line = _extract_between(prompt, "Task:", "\n") or task_line
        content = f'''"""
Auto-generated mock implementation.
"""

# Task: {task_line.strip()}

def placeholder():
    """Mock implementation placeholder."""
    return "mock-response"
'''
        response = {
            "files": [{"path": path.strip(), "content": content}],
            "artifacts": {
                "implementation_plan": (
                    "1. Review task context and requirements.\n"
                    "2. Implement requested changes in the target file.\n"
                    "3. Validate output and update summaries."
                )
            },
        }
        text = json.dumps(response, ensure_ascii=False)
        tokens_in = max(1, len(prompt.split()))
        tokens_out = max(1, len(text.split()))
        return {
            "text": text,
            "usage": {
                "input_tokens": tokens_in,
                "output_tokens": tokens_out,
                "total_tokens": tokens_in + tokens_out,
            },
        }


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, timeout_seconds: float):
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    async def generate_text(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        response_format: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format
        timeout = httpx.Timeout(self.timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async def _post(request_payload: Dict[str, Any]) -> httpx.Response:
                response = await client.post(url, headers=headers, json=request_payload)
                response.raise_for_status()
                return response

            try:
                response = await _post(payload)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response else None
                if response_format and status in {400, 404} and exc.response is not None:
                    body = exc.response.text or ""
                    if "response_format" in body or "json_object" in body:
                        payload.pop("response_format", None)
                        try:
                            response = await _post(payload)
                        except httpx.HTTPStatusError as fallback_exc:
                            fallback_status = (
                                fallback_exc.response.status_code if fallback_exc.response else None
                            )
                            retryable = fallback_status in {408, 429} or (
                                fallback_status is not None and fallback_status >= 500
                            )
                            message = (
                                "OpenAI API error "
                                f"({fallback_status}): "
                                f"{fallback_exc.response.text if fallback_exc.response else fallback_exc}"
                            )
                            raise LLMProviderError(message, retryable=retryable) from fallback_exc
                    else:
                        retryable = status in {408, 429} or (status is not None and status >= 500)
                        message = f"OpenAI API error ({status}): {exc.response.text}"
                        raise LLMProviderError(message, retryable=retryable) from exc
                else:
                    retryable = status in {408, 429} or (status is not None and status >= 500)
                    message = f"OpenAI API error ({status}): {exc.response.text if exc.response else exc}"
                    raise LLMProviderError(message, retryable=retryable) from exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise LLMProviderError(f"OpenAI request failed: {exc}", retryable=True) from exc

        data = response.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage", {}) or {}
        return {
            "text": text,
            "usage": {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
        }


def get_llm_provider(settings: LLMSettings) -> LLMProvider:
    if settings.provider == "openai":
        if not settings.api_key:
            raise LLMProviderError("LLM_API_KEY is required for OpenAI provider.", retryable=False)
        return OpenAIProvider(settings.api_key, settings.timeout_seconds)
    return MockProvider()


async def generate_with_retry(
    provider: LLMProvider,
    messages: List[Dict[str, str]],
    settings: LLMSettings,
    *,
    max_retries: int = 2,
    require_json: bool = False,
) -> Dict[str, Any]:
    attempt = 0
    delay = 1.0
    response_format = {"type": "json_object"} if require_json else None
    temperature = 0.0 if require_json else settings.temperature
    prepared_messages = _inject_json_system_instruction(messages, provider, require_json)
    while True:
        try:
            return await provider.generate_text(
                messages=prepared_messages,
                model=settings.model,
                temperature=temperature,
                max_tokens=settings.max_tokens,
                response_format=response_format,
            )
        except LLMProviderError as exc:
            if attempt >= max_retries or not exc.retryable:
                raise
            await asyncio.sleep(delay)
            delay *= 2
            attempt += 1


def _inject_json_system_instruction(
    messages: List[Dict[str, str]],
    provider: LLMProvider,
    require_json: bool,
) -> List[Dict[str, str]]:
    if not require_json or provider.name != "openai":
        return messages
    instruction = "OUTPUT JSON ONLY. No markdown. No extra keys."
    if not messages:
        return [{"role": "system", "content": instruction}]
    updated = [dict(message) for message in messages]
    if updated[0].get("role") == "system":
        content = updated[0].get("content", "")
        if instruction not in content:
            updated[0]["content"] = f"{content.rstrip()}\n{instruction}"
        return updated
    updated.insert(0, {"role": "system", "content": instruction})
    return updated


def _extract_between(text: str, start: str, end: str) -> str:
    if start not in text:
        return ""
    after = text.split(start, 1)[1]
    if end in after:
        return after.split(end, 1)[0]
    return after
