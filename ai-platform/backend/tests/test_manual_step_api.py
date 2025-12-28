import uuid

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app, hash_api_key, storage


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_storage() -> None:
    storage.active_tasks.clear()
    storage.events.clear()
    storage.state.clear()


def seed_manual_task(awaiting: bool = True) -> tuple[str, str]:
    task_id = str(uuid.uuid4())
    api_key = "test-key"
    owner_hash = hash_api_key(api_key)
    now = db.now_utc()
    storage.active_tasks[task_id] = {
        "id": task_id,
        "description": "Manual step task",
        "user_id": "test-user",
        "status": "needs_input",
        "progress": 0.6,
        "created_at": now,
        "updated_at": now,
        "owner_key_hash": owner_hash,
        "owner_user_id": None,
        "manual_step_enabled": True,
        "awaiting_manual_step": awaiting,
        "manual_step_stage": "post_iteration_review" if awaiting else None,
        "manual_step_options": ["continue", "stop", "retry"],
        "last_review_status": "rejected",
        "last_review_report_artifact_id": "artifact-123",
        "next_task_preview": {"description": "Fix review findings"},
        "resume_phase": "implementation",
        "resume_iteration": 2,
        "resume_payload": {"next_task_override": {"description": "Fix review findings"}},
        "resume_from_stage": "implementation",
        "pending_questions": [],
        "provided_answers": {},
    }
    return task_id, api_key


def test_manual_next_step_continues_task() -> None:
    task_id, api_key = seed_manual_task()
    response = client.post(
        f"/api/tasks/{task_id}/next",
        json={"decision": "continue"},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert storage.active_tasks[task_id]["awaiting_manual_step"] is False
    events = storage.events.get(task_id, [])
    event_types = [event["type"] for event in events]
    assert "manual_step_received" in event_types
    assert "manual_step_applied" in event_types


def test_manual_next_step_rejects_when_not_awaiting() -> None:
    task_id, api_key = seed_manual_task(awaiting=False)
    response = client.post(
        f"/api/tasks/{task_id}/next",
        json={"decision": "continue"},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 409
