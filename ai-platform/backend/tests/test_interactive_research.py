import uuid
import asyncio

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app, hash_api_key, process_task_background, storage
import app.orchestrator as orchestrator_module


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_storage() -> None:
    storage.active_tasks.clear()
    storage.events.clear()
    storage.state.clear()
    storage.artifacts.clear()
    storage.containers.clear()


def seed_interactive_task() -> tuple[str, str]:
    task_id = str(uuid.uuid4())
    api_key = "test-key"
    owner_hash = hash_api_key(api_key)
    now = db.now_utc()
    storage.active_tasks[task_id] = {
        "id": task_id,
        "description": "Build a landing page for a cafe",
        "user_id": "test-user",
        "status": "queued",
        "progress": 0.0,
        "created_at": now,
        "updated_at": now,
        "owner_key_hash": owner_hash,
        "owner_user_id": None,
        "request_id": "req-123",
        "failure_reason": None,
        "pending_questions": [],
        "provided_answers": {},
        "resume_from_stage": None,
        "manual_step_enabled": False,
        "awaiting_manual_step": False,
        "manual_step_stage": None,
        "manual_step_options": None,
        "last_review_status": None,
        "last_review_report_artifact_id": None,
        "next_task_preview": None,
        "resume_phase": None,
        "resume_iteration": None,
        "resume_payload": None,
    }
    return task_id, api_key


class DummyDesigner:
    def __init__(self, codex):
        self.codex = codex

    async def execute(self, container):
        return {"components": []}


class DummyCoder:
    def __init__(self, codex):
        self.codex = codex

    async def execute(self, task, container, **kwargs):
        return {"files": []}


class DummyReviewer:
    def __init__(self, codex):
        self.codex = codex

    async def execute(self, container):
        return {"status": "approved", "passed": True}


class DummyPlanner:
    def __init__(self, codex):
        self.codex = codex

    async def execute(self, container):
        container.metadata["plan_version"] = int(container.metadata.get("plan_version") or 0) + 1
        return {"steps": []}


def test_interactive_research_chat_flow(monkeypatch) -> None:
    monkeypatch.setenv("ORCH_INTERACTIVE_RESEARCH", "true")
    monkeypatch.setenv("ORCH_ENABLE_TRIAGE", "false")
    monkeypatch.setattr(orchestrator_module, "AIDesigner", DummyDesigner)
    monkeypatch.setattr(orchestrator_module, "AIPlanner", DummyPlanner)
    monkeypatch.setattr(orchestrator_module, "AICoder", DummyCoder)
    monkeypatch.setattr(orchestrator_module, "AIReviewer", DummyReviewer)

    task_id, api_key = seed_interactive_task()
    description = storage.active_tasks[task_id]["description"]

    asyncio.run(process_task_background(task_id, description, request_id="req-123"))
    assert storage.active_tasks[task_id]["status"] == "awaiting_user"

    for round_index in range(3):
        response = client.post(
            f"/api/tasks/{task_id}/chat",
            json={"message": f"Ответ пользователя {round_index + 1}"},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200
        asyncio.run(
            process_task_background(
                task_id,
                description,
                request_id="req-123",
                resume_from_stage="research",
            )
        )
        if round_index < 2:
            assert storage.active_tasks[task_id]["status"] == "awaiting_user"

    container = storage.containers[task_id]
    assert container.artifacts["requirements"]
    assert storage.active_tasks[task_id]["status"] != "awaiting_user"
