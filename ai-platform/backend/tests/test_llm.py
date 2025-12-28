import json

import pytest

from app.llm import (
    LLMOutputTruncatedError,
    LLMSettings,
    OpenAIProvider,
    generate_text_chunks_json,
    generate_with_retry,
)


class FakeProvider:
    name = "openai"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def generate_text(
        self,
        messages,
        model,
        temperature,
        max_tokens,
        response_format=None,
    ):
        self.calls.append({"max_tokens": max_tokens, "response_format": response_format})
        if not self.responses:
            raise AssertionError("No more responses configured.")
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_generate_with_retry_json_mode_returns_parsable_json():
    provider = FakeProvider(
        [
            {
                "text": "{\"ping\":\"pong\"}",
                "usage": {"input_tokens": 2, "output_tokens": 2, "total_tokens": 4},
                "finish_reason": "stop",
            }
        ]
    )
    settings = LLMSettings(
        provider="openai",
        model="gpt-4o-mini",
        api_key="test",
        max_tokens=100,
        max_tokens_coder=100,
        timeout_seconds=10,
        temperature=0.2,
        response_format="json_object",
        chunking_enabled=True,
        max_chunks=8,
        max_file_chars=12000,
    )

    response = await generate_with_retry(provider, [], settings, require_json=True)

    assert provider.calls[0]["response_format"] == {"type": "json_object"}
    assert json.loads(response["text"]) == {"ping": "pong"}


@pytest.mark.asyncio
async def test_generate_with_retry_retries_on_truncation():
    provider = FakeProvider(
        [
            {
                "text": "{\"partial\":",
                "usage": {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
                "finish_reason": "length",
            },
            {
                "text": "{\"ok\":true}",
                "usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7},
                "finish_reason": "stop",
            },
        ]
    )
    settings = LLMSettings(
        provider="openai",
        model="gpt-4o-mini",
        api_key="test",
        max_tokens=50,
        max_tokens_coder=50,
        timeout_seconds=10,
        temperature=0.2,
        response_format="json_object",
        chunking_enabled=True,
        max_chunks=8,
        max_file_chars=12000,
    )

    response = await generate_with_retry(provider, [], settings, require_json=True)

    assert provider.calls[0]["max_tokens"] == 50
    assert provider.calls[1]["max_tokens"] == 100
    assert response["usage"]["total_tokens"] == 17


@pytest.mark.asyncio
async def test_generate_with_retry_truncation_raises_after_retry():
    provider = FakeProvider(
        [
            {
                "text": "{\"partial\":",
                "usage": {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
                "finish_reason": "length",
            },
            {
                "text": "{\"partial_again\":",
                "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
                "finish_reason": "length",
            },
        ]
    )
    settings = LLMSettings(
        provider="openai",
        model="gpt-4o-mini",
        api_key="test",
        max_tokens=50,
        max_tokens_coder=50,
        timeout_seconds=10,
        temperature=0.2,
        response_format="json_object",
        chunking_enabled=True,
        max_chunks=8,
        max_file_chars=12000,
    )

    with pytest.raises(LLMOutputTruncatedError) as excinfo:
        await generate_with_retry(provider, [], settings, require_json=True)

    assert excinfo.value.usage["total_tokens"] == 15


@pytest.mark.asyncio
async def test_openai_provider_captures_finish_reason(monkeypatch):
    class DummyResponse:
        def __init__(self, data):
            self._data = data
            self.status_code = 200
            self.text = json.dumps(data)

        def raise_for_status(self):
            return None

        def json(self):
            return self._data

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            return DummyResponse(
                {
                    "choices": [
                        {"message": {"content": "{}"}, "finish_reason": "length"}
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
            )

    monkeypatch.setattr("app.llm.httpx.AsyncClient", DummyClient)

    provider = OpenAIProvider("test-key", 10)
    response = await provider.generate_text(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-4o-mini",
        temperature=0.2,
        max_tokens=10,
        response_format=None,
    )

    assert response["finish_reason"] == "length"


@pytest.mark.asyncio
async def test_generate_text_chunks_concatenates_partial_chunks():
    provider = FakeProvider(
        [
            {
                "text": json.dumps(
                    {
                        "status": "partial",
                        "chunk_index": 1,
                        "content_chunk": "hello ",
                    }
                ),
                "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
                "finish_reason": "stop",
            },
            {
                "text": json.dumps(
                    {
                        "status": "partial",
                        "chunk_index": 2,
                        "content_chunk": "world",
                    }
                ),
                "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
                "finish_reason": "stop",
            },
            {
                "text": json.dumps(
                    {
                        "status": "complete",
                        "chunk_index": 3,
                        "content_chunk": "!",
                    }
                ),
                "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
                "finish_reason": "stop",
            },
        ]
    )
    settings = LLMSettings(
        provider="openai",
        model="gpt-4o-mini",
        api_key="test",
        max_tokens=50,
        max_tokens_coder=50,
        timeout_seconds=10,
        temperature=0.2,
        response_format="json_object",
        chunking_enabled=True,
        max_chunks=5,
        max_file_chars=50,
    )

    response = await generate_text_chunks_json(
        provider,
        settings,
        base_messages=[{"role": "system", "content": "test"}],
        max_tokens=20,
        max_chunks=5,
        max_file_chars=50,
    )

    assert response["text"] == "hello world!"
    assert response["chunks"] == 3
    assert response["usage"]["total_tokens"] == 9


@pytest.mark.asyncio
async def test_generate_text_chunks_enforces_char_limit():
    provider = FakeProvider(
        [
            {
                "text": json.dumps(
                    {
                        "status": "complete",
                        "chunk_index": 1,
                        "content_chunk": "too long",
                    }
                ),
                "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
                "finish_reason": "stop",
            }
        ]
    )
    settings = LLMSettings(
        provider="openai",
        model="gpt-4o-mini",
        api_key="test",
        max_tokens=50,
        max_tokens_coder=50,
        timeout_seconds=10,
        temperature=0.2,
        response_format="json_object",
        chunking_enabled=True,
        max_chunks=5,
        max_file_chars=3,
    )

    with pytest.raises(LLMOutputTruncatedError) as excinfo:
        await generate_text_chunks_json(
            provider,
            settings,
            base_messages=[{"role": "system", "content": "test"}],
            max_tokens=20,
            max_chunks=5,
            max_file_chars=3,
        )

    assert str(excinfo.value) == "llm_output_budget_exceeded"


@pytest.mark.asyncio
async def test_generate_text_chunks_retries_invalid_json():
    provider = FakeProvider(
        [
            {
                "text": "not json",
                "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
                "finish_reason": "stop",
            },
            {
                "text": json.dumps(
                    {
                        "status": "complete",
                        "chunk_index": 1,
                        "content_chunk": "ok",
                    }
                ),
                "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
                "finish_reason": "stop",
            },
        ]
    )
    settings = LLMSettings(
        provider="openai",
        model="gpt-4o-mini",
        api_key="test",
        max_tokens=50,
        max_tokens_coder=50,
        timeout_seconds=10,
        temperature=0.2,
        response_format="json_object",
        chunking_enabled=True,
        max_chunks=5,
        max_file_chars=50,
    )

    response = await generate_text_chunks_json(
        provider,
        settings,
        base_messages=[{"role": "system", "content": "test"}],
        max_tokens=20,
        max_chunks=5,
        max_file_chars=50,
    )

    assert response["text"] == "ok"
    assert len(provider.calls) == 2
