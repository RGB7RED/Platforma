from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_features_interactive_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ORCH_INTERACTIVE_RESEARCH", raising=False)
    response = client.get("/api/features")
    assert response.status_code == 200
    payload = response.json()
    assert payload["interactive_research_enabled"] is False


def test_features_interactive_enabled(monkeypatch) -> None:
    monkeypatch.setenv("ORCH_INTERACTIVE_RESEARCH", "true")
    response = client.get("/api/features")
    assert response.status_code == 200
    payload = response.json()
    assert payload["interactive_research_enabled"] is True
