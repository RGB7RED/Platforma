import json

import pytest

from app.agents import AICoder, ParseError
from app.llm import MockProvider
from app.models import Container


def _build_provider(responses):
    provider = MockProvider()
    calls = {"count": 0}

    async def generate_text(*args, **kwargs):
        calls["count"] += 1
        if not responses:
            raise AssertionError("No more mock responses configured.")
        return responses.pop(0)

    provider.generate_text = generate_text  # type: ignore[method-assign]
    return provider, calls


@pytest.mark.asyncio
async def test_coder_parses_valid_json_first_try(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_CHUNKING_ENABLED", "0")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    responses = [
        {
            "text": json.dumps(
                {
                    "files": [{"path": "main.py", "content": "print('ok')\n"}],
                    "artifacts": {"code_summary": "done"},
                }
            ),
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            "finish_reason": "stop",
        }
    ]
    provider, calls = _build_provider(responses)
    monkeypatch.setattr("app.agents.get_llm_provider", lambda settings: provider)
    coder = AICoder({"rules": {"coder": {}}})
    container = Container("test-project")
    task = {"type": "implement_component", "file": "main.py", "description": "Test"}

    result = await coder.execute(task, container)

    assert result["file"] == "main.py"
    assert "main.py" in container.files
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_coder_retries_after_plain_text(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_CHUNKING_ENABLED", "0")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    responses = [
        {
            "text": "no json yet",
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            "finish_reason": "stop",
        },
        {
            "text": json.dumps(
                {
                    "files": [{"path": "main.py", "content": "print('retry')\n"}],
                    "artifacts": {"code_summary": "retry ok"},
                }
            ),
            "usage": {"input_tokens": 2, "output_tokens": 2, "total_tokens": 4},
            "finish_reason": "stop",
        },
    ]
    provider, calls = _build_provider(responses)
    monkeypatch.setattr("app.agents.get_llm_provider", lambda settings: provider)
    coder = AICoder({"rules": {"coder": {}}})
    container = Container("test-project")
    task = {"type": "implement_component", "file": "main.py", "description": "Test"}

    result = await coder.execute(task, container)

    assert result["file"] == "main.py"
    assert "main.py" in container.files
    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_coder_fails_after_empty_files(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_CHUNKING_ENABLED", "0")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    responses = [
        {
            "text": json.dumps({"files": [], "artifacts": {"code_summary": "empty"}}),
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            "finish_reason": "stop",
        },
        {
            "text": json.dumps({"files": [], "artifacts": {"code_summary": "empty"}}),
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            "finish_reason": "stop",
        },
        {
            "text": json.dumps({"files": [], "artifacts": {"code_summary": "empty"}}),
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            "finish_reason": "stop",
        },
    ]
    provider, calls = _build_provider(responses)
    monkeypatch.setattr("app.agents.get_llm_provider", lambda settings: provider)
    coder = AICoder({"rules": {"coder": {}}})
    container = Container("test-project")
    task = {"type": "implement_component", "file": "main.py", "description": "Test"}

    with pytest.raises(ParseError) as excinfo:
        await coder.execute(task, container)

    error_detail = getattr(excinfo.value, "error", str(excinfo.value))
    assert "files empty" in error_detail
    assert "response_preview=" in error_detail
    assert "provider=mock" in error_detail
    assert "model=test-model" in error_detail
    assert calls["count"] == 3
