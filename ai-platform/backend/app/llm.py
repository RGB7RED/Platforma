"""LLM provider abstraction and helpers."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

import httpx

logger = logging.getLogger(__name__)


class LLMProviderError(RuntimeError):
    """Error raised when an LLM provider request fails."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class LLMOutputTruncatedError(RuntimeError):
    """Error raised when LLM output is truncated."""

    def __init__(
        self,
        message: str,
        *,
        usage: Optional[Dict[str, int]] = None,
        finish_reason: Optional[str] = None,
    ):
        super().__init__(message)
        self.usage = usage or {}
        self.finish_reason = finish_reason


class LLMInvalidResponseError(RuntimeError):
    """Error raised when an LLM returns invalid JSON payloads."""

    def __init__(
        self,
        message: str,
        *,
        raw_text: str,
        usage: Optional[Dict[str, int]] = None,
    ) -> None:
        super().__init__(message)
        self.raw_text = raw_text
        self.usage = usage or {}


class LLMProvider(Protocol):
    name: str

    async def generate_text(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate text from provider. Returns dict with text and usage."""


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str
    api_key: Optional[str]
    max_tokens: int
    max_tokens_coder: int
    timeout_seconds: float
    temperature: float
    response_format: str
    chunking_enabled: bool
    max_chunks: int
    max_file_chars: int


def load_llm_settings() -> LLMSettings:
    provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()
    model = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()
    api_key = os.getenv("LLM_API_KEY")
    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "1024"))
    max_tokens_coder = int(os.getenv("LLM_MAX_TOKENS_CODER", str(max_tokens)))
    timeout_seconds = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.2"))
    response_format = os.getenv("LLM_RESPONSE_FORMAT", "json_object").strip().lower()
    chunking_enabled = _parse_bool_env(os.getenv("LLM_CHUNKING_ENABLED", "1"))
    max_chunks = int(os.getenv("LLM_MAX_CHUNKS", "8"))
    max_file_chars = int(os.getenv("LLM_MAX_FILE_CHARS", "12000"))
    return LLMSettings(
        provider=provider,
        model=model,
        api_key=api_key,
        max_tokens=max_tokens,
        max_tokens_coder=max_tokens_coder,
        timeout_seconds=timeout_seconds,
        temperature=temperature,
        response_format=response_format,
        chunking_enabled=chunking_enabled,
        max_chunks=max_chunks,
        max_file_chars=max_file_chars,
    )


class MockProvider:
    name = "mock"

    async def generate_text(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        prompt = messages[-1]["content"] if messages else ""
        expects_chunk = all(
            token in prompt for token in ("content_chunk", "chunk_index", "status")
        )
        path = "generated.py"
        task_line = "Implement requested changes."
        exact_json_only = False
        try:
            payload = json.loads(prompt)
            path = payload.get("Target file") or payload.get("Target file", path)
            task_line = payload.get("Task", task_line)
            contract_payload = payload.get("Output contract") or {}
            if isinstance(contract_payload, dict):
                exact_json_only = bool(contract_payload.get("exact_json_only"))
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
        if exact_json_only:
            response = {"files": [{"path": path.strip(), "content": content}]}
        if expects_chunk:
            response = {
                "status": "complete",
                "chunk_index": 1,
                "content_chunk": content,
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
            "finish_reason": "stop",
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
        response_format: Optional[Dict[str, Any]] = None,
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
        choice = data.get("choices", [{}])[0]
        text = choice.get("message", {}).get("content", "")
        finish_reason = choice.get("finish_reason")
        usage = data.get("usage", {}) or {}
        prompt_chars = sum(len(str(message.get("content", ""))) for message in messages)
        response_chars = len(text or "")
        usage_metrics = {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
        logger.info(
            "OpenAI completion metrics prompt_chars=%s max_tokens=%s finish_reason=%s "
            "response_chars=%s usage=%s",
            prompt_chars,
            max_tokens,
            finish_reason,
            response_chars,
            usage_metrics,
        )
        return {
            "text": text,
            "usage": usage_metrics,
            "finish_reason": finish_reason,
        }


def get_llm_provider(settings: LLMSettings) -> LLMProvider:
    if settings.provider == "openai":
        if not settings.api_key:
            raise LLMProviderError("LLM_API_KEY is required for OpenAI provider.", retryable=False)
        return OpenAIProvider(settings.api_key, settings.timeout_seconds)
    return MockProvider()


async def generate_text_chunks_json(
    provider: LLMProvider,
    settings: LLMSettings,
    *,
    base_messages: List[Dict[str, str]],
    max_tokens: Optional[int] = None,
    max_chunks: Optional[int] = None,
    max_file_chars: Optional[int] = None,
) -> Dict[str, Any]:
    chunk_limit = max_chunks or settings.max_chunks
    char_limit = max_file_chars or settings.max_file_chars
    token_limit = max_tokens or settings.max_tokens
    total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    aggregated = []
    response_format = _resolve_response_format(settings.response_format, True)
    temperature = 0.0

    for chunk_index in range(1, chunk_limit + 1):
        if char_limit > 0 and sum(len(chunk) for chunk in aggregated) >= char_limit:
            raise LLMOutputTruncatedError(
                "llm_output_budget_exceeded",
                usage=total_usage,
                finish_reason="max_file_chars",
            )
        invalid_attempts = 0
        last_error_text = ""
        while True:
            messages = _build_chunk_messages(
                base_messages=base_messages,
                chunk_index=chunk_index,
                remaining_chars=char_limit - sum(len(chunk) for chunk in aggregated)
                if char_limit > 0
                else None,
                tail_text=_tail_text("".join(aggregated)),
                invalid_json=invalid_attempts > 0,
            )
            prepared_messages = _inject_json_system_instruction(messages, provider, True)
            response = await provider.generate_text(
                messages=prepared_messages,
                model=settings.model,
                temperature=temperature,
                max_tokens=token_limit,
                response_format=response_format,
            )
            usage = response.get("usage", {}) or {}
            total_usage = _accumulate_usage(total_usage, usage)
            text = response.get("text", "") or ""
            try:
                payload = _parse_chunk_payload(text, expected_index=chunk_index)
            except ValueError as exc:
                last_error_text = text
                if invalid_attempts >= 2:
                    raise LLMInvalidResponseError(
                        "llm_invalid_json",
                        raw_text=last_error_text,
                        usage=total_usage,
                    ) from exc
                invalid_attempts += 1
                continue
            content_chunk = payload["content_chunk"]
            if content_chunk:
                aggregated.append(content_chunk)
            combined = "".join(aggregated)
            if char_limit > 0 and len(combined) > char_limit:
                raise LLMOutputTruncatedError(
                    "llm_output_budget_exceeded",
                    usage=total_usage,
                    finish_reason="max_file_chars",
                )
            if payload["status"] == "complete":
                return {
                    "text": combined,
                    "usage": total_usage,
                    "chunks": chunk_index,
                    "finish_reason": "complete",
                }
            break

    raise LLMOutputTruncatedError(
        "llm_output_truncated",
        usage=total_usage,
        finish_reason="max_chunks",
    )


async def generate_with_retry(
    provider: LLMProvider,
    messages: List[Dict[str, str]],
    settings: LLMSettings,
    *,
    max_retries: int = 2,
    require_json: bool = False,
    max_tokens_override: Optional[int] = None,
) -> Dict[str, Any]:
    attempt = 0
    delay = 1.0
    response_format = _resolve_response_format(settings.response_format, require_json)
    temperature = 0.0 if require_json else settings.temperature
    prepared_messages = _inject_json_system_instruction(messages, provider, require_json)
    max_tokens = max_tokens_override or settings.max_tokens
    truncation_retries = 0
    max_truncation_retries = 1
    continuation_attempts = 0
    max_continuations = 3
    total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    continuation_messages = prepared_messages
    combined_chunks: List[str] = []
    continuation_prompt = (
        "Continue EXACTLY from where you stopped. Do not repeat. "
        "Output only the remaining content."
    )
    while True:
        try:
            response = await provider.generate_text(
                messages=continuation_messages,
                model=settings.model,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )
            usage = response.get("usage", {}) or {}
            total_usage["input_tokens"] += int(usage.get("input_tokens", 0) or 0)
            total_usage["output_tokens"] += int(usage.get("output_tokens", 0) or 0)
            if usage.get("total_tokens") is not None:
                total_usage["total_tokens"] += int(usage.get("total_tokens", 0) or 0)
            else:
                total_usage["total_tokens"] += int(usage.get("input_tokens", 0) or 0) + int(
                    usage.get("output_tokens", 0) or 0
                )

            finish_reason = response.get("finish_reason")
            text = response.get("text", "") or ""

            if finish_reason == "length":
                if truncation_retries < max_truncation_retries:
                    truncation_retries += 1
                    max_tokens = min(max_tokens * 2, 2000)
                    combined_chunks = []
                    continuation_messages = prepared_messages
                    continue
                combined_chunks.append(text)
                if continuation_attempts < max_continuations:
                    continuation_attempts += 1
                    aggregated_text = "".join(combined_chunks)
                    continuation_messages = prepared_messages + [
                        {"role": "assistant", "content": aggregated_text},
                        {"role": "user", "content": continuation_prompt},
                    ]
                    continue
                raise LLMOutputTruncatedError(
                    "llm_output_truncated",
                    usage=total_usage,
                    finish_reason=finish_reason,
                )
            if combined_chunks:
                combined_chunks.append(text)
                text = "".join(combined_chunks)
            response["finish_reason"] = finish_reason
            response["usage"] = total_usage
            response["text"] = text
            return response
        except LLMProviderError as exc:
            if attempt >= max_retries or not exc.retryable:
                raise
            await asyncio.sleep(delay)
            delay *= 2
            attempt += 1


def _resolve_response_format(
    response_format: str,
    require_json: bool,
) -> Optional[Dict[str, Any]]:
    if not require_json:
        return None
    normalized = response_format.strip().lower()
    if normalized == "json_schema":
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "response",
                "schema": {"type": "object", "additionalProperties": True},
            },
        }
    return {"type": "json_object"}


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


def _build_chunk_messages(
    *,
    base_messages: List[Dict[str, str]],
    chunk_index: int,
    remaining_chars: Optional[int],
    tail_text: str,
    invalid_json: bool,
) -> List[Dict[str, str]]:
    schema = (
        '{\n'
        '  "status": "partial" | "complete",\n'
        '  "chunk_index": 1,\n'
        '  "content_chunk": "string (may be empty)",\n'
        '  "notes": "optional short string"\n'
        "}"
    )
    instructions = [
        "Return ONLY a JSON object that matches this schema exactly:",
        schema,
        "Rules:",
        "- content_chunk must be raw text (no markdown fences).",
        "- status=partial means send the next chunk continuing exactly where you stopped.",
        "- status=complete ends the stream.",
        f"- chunk_index must be {chunk_index}.",
    ]
    if remaining_chars is not None:
        instructions.append(f"- Remaining character budget: {remaining_chars}.")
    if chunk_index == 1:
        instructions.append(
            "- First chunk should include imports/module header and top-level structure."
        )
    if tail_text:
        instructions.append("Continue after this exact tail without repeating it:")
        instructions.append(tail_text)
    else:
        instructions.append("Begin the file content now.")
    if invalid_json:
        instructions.append("Return JSON object only. Do not include any extra text.")
    messages = [dict(message) for message in base_messages]
    messages.append({"role": "user", "content": "\n".join(instructions)})
    return messages


def _parse_chunk_payload(text: str, *, expected_index: Optional[int] = None) -> Dict[str, Any]:
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Chunk payload must be a JSON object.")
    status = payload.get("status")
    if status not in {"partial", "complete"}:
        raise ValueError("Chunk status must be 'partial' or 'complete'.")
    if expected_index is not None:
        chunk_index = payload.get("chunk_index")
        if chunk_index != expected_index:
            raise ValueError(f"chunk_index must be {expected_index}.")
    content_chunk = payload.get("content_chunk")
    if content_chunk is None:
        raise ValueError("content_chunk is required.")
    if not isinstance(content_chunk, str):
        content_chunk = str(content_chunk)
    return {
        "status": status,
        "content_chunk": content_chunk,
    }


def _accumulate_usage(
    total_usage: Dict[str, int],
    usage: Dict[str, Any],
) -> Dict[str, int]:
    total_usage["input_tokens"] += int(usage.get("input_tokens", 0) or 0)
    total_usage["output_tokens"] += int(usage.get("output_tokens", 0) or 0)
    if usage.get("total_tokens") is not None:
        total_usage["total_tokens"] += int(usage.get("total_tokens", 0) or 0)
    else:
        total_usage["total_tokens"] += int(usage.get("input_tokens", 0) or 0) + int(
            usage.get("output_tokens", 0) or 0
        )
    return total_usage


def _parse_bool_env(value: str) -> bool:
    return str(value or "").strip().lower() not in {"0", "false", "no", "off"}


def _tail_text(text: str, max_chars: int = 500) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _extract_between(text: str, start: str, end: str) -> str:
    if start not in text:
        return ""
    after = text.split(start, 1)[1]
    if end in after:
        return after.split(end, 1)[0]
    return after
