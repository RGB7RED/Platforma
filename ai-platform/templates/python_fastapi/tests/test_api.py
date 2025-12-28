"""API tests for the todo endpoints."""

from fastapi.testclient import TestClient


def test_list_todos_empty(client: TestClient) -> None:
    """GET /api/todos returns an empty list initially."""
    response = client.get("/api/todos")
    assert response.status_code == 200
    assert response.json() == []


def test_create_and_get_todo(client: TestClient) -> None:
    """Create a todo and then fetch it."""
    create_response = client.post("/api/todos", json={"title": "Buy milk"})
    assert create_response.status_code == 201
    todo = create_response.json()
    assert todo["title"] == "Buy milk"

    get_response = client.get(f"/api/todos/{todo['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == todo["id"]


def test_search_todos(client: TestClient) -> None:
    """Search todos by query."""
    client.post("/api/todos", json={"title": "Call mom"})
    response = client.get("/api/todos/search", params={"query": "call"})
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert "call" in results[0]["title"].lower()
