import pytest
from fastapi.testclient import TestClient

from app.main import app, storage, task_governor


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_storage() -> None:
    storage.active_tasks.clear()
    storage.events.clear()
    storage.state.clear()
    storage.artifacts.clear()
    storage.containers.clear()


def create_task_for_intake(api_key: str) -> str:
    response = client.post(
        "/api/tasks",
        json={
            "description": "Build a landing page for a cafe",
            "auto_start": False,
        },
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 200
    return response.json()["task_id"]


def test_intake_flow_creates_requirements(monkeypatch) -> None:
    monkeypatch.setenv("ORCH_INTERACTIVE_RESEARCH", "true")
    api_key = "test-key"
    task_id = create_task_for_intake(api_key)

    intake_response = client.post(
        f"/api/tasks/{task_id}/intake/start",
        headers={"X-API-Key": api_key},
    )
    assert intake_response.status_code == 200
    payload = intake_response.json()
    assert payload["status"] == "awaiting_user"
    assert payload["artifacts"]["research_chat"]

    for round_index in range(3):
        response = client.post(
            f"/api/tasks/{task_id}/chat",
            json={"message": f"Ответ пользователя {round_index + 1}"},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200

    status_response = client.get(
        f"/api/tasks/{task_id}",
        headers={"X-API-Key": api_key},
    )
    assert status_response.status_code == 200
    payload = status_response.json()
    assert payload["status"] == "intake_complete"
    assert payload["can_start"] is True
    assert payload["artifacts"]["requirements"]


def test_start_requires_intake_complete(monkeypatch) -> None:
    monkeypatch.setenv("ORCH_INTERACTIVE_RESEARCH", "true")
    api_key = "test-key"
    task_id = create_task_for_intake(api_key)

    intake_response = client.post(
        f"/api/tasks/{task_id}/intake/start",
        headers={"X-API-Key": api_key},
    )
    assert intake_response.status_code == 200

    start_response = client.post(
        f"/api/tasks/{task_id}/start",
        headers={"X-API-Key": api_key},
    )
    assert start_response.status_code == 409

    for round_index in range(3):
        response = client.post(
            f"/api/tasks/{task_id}/chat",
            json={"message": f"Ответ пользователя {round_index + 1}"},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200

    enqueued: list[dict] = []

    async def fake_enqueue(item) -> None:
        enqueued.append({"task_id": item.task_id, "resume_from_stage": item.resume_from_stage})

    monkeypatch.setattr(task_governor, "enqueue", fake_enqueue)

    start_response = client.post(
        f"/api/tasks/{task_id}/start",
        headers={"X-API-Key": api_key},
    )
    assert start_response.status_code == 200
    assert enqueued
