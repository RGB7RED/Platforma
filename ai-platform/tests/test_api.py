"""API tests for todo endpoints."""

import sys
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import fixture

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for module_name in list(sys.modules):
    if module_name == "api" or module_name.startswith("api."):
        sys.modules.pop(module_name)

from api.dependencies import get_todo_repository  # noqa: E402
from todo_main import app  # noqa: E402

client = TestClient(app)


@fixture(autouse=True)
def clear_repository() -> None:
    """Reset repository data between tests."""
    repository = get_todo_repository()
    repository.clear()


class TestTodoAPI:
    """Test suite for Todo API endpoints."""

    def test_root_endpoint(self) -> None:
        """Test root endpoint returns API info."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert data["message"] == "Todo API"
        assert "endpoints" in data

    def test_get_todos_empty(self) -> None:
        """Test getting todos when database is empty."""
        response = client.get("/api/todos")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_todo_success(self) -> None:
        """Test successful todo creation."""
        todo_data = {"title": "Test todo", "description": "Test description"}
        response = client.post("/api/todos", json=todo_data)
        assert response.status_code == 201

        todo = response.json()
        assert todo["title"] == todo_data["title"]
        assert todo["description"] == todo_data["description"]
        assert todo["completed"] is False
        assert "id" in todo
        assert "created_at" in todo

    def test_create_todo_invalid(self) -> None:
        """Test todo creation with invalid data."""
        response = client.post("/api/todos", json={"title": ""})
        assert response.status_code == 400

        response = client.post("/api/todos", json={"description": "No title"})
        assert response.status_code == 422

    def test_get_todo_by_id(self) -> None:
        """Test getting a specific todo by ID."""
        create_response = client.post("/api/todos", json={"title": "Test"})
        todo_id = create_response.json()["id"]

        response = client.get(f"/api/todos/{todo_id}")
        assert response.status_code == 200
        assert response.json()["id"] == todo_id

    def test_get_nonexistent_todo(self) -> None:
        """Test getting a todo that doesn't exist."""
        response = client.get("/api/todos/99999")
        assert response.status_code == 404

    def test_update_todo(self) -> None:
        """Test updating a todo."""
        create_response = client.post("/api/todos", json={"title": "Original"})
        todo_id = create_response.json()["id"]

        update_data = {"title": "Updated", "completed": True}
        response = client.put(f"/api/todos/{todo_id}", json=update_data)
        assert response.status_code == 200

        updated_todo = response.json()
        assert updated_todo["title"] == "Updated"
        assert updated_todo["completed"] is True

    def test_delete_todo(self) -> None:
        """Test deleting a todo."""
        create_response = client.post("/api/todos", json={"title": "To delete"})
        todo_id = create_response.json()["id"]

        response = client.delete(f"/api/todos/{todo_id}")
        assert response.status_code == 204

        response = client.get(f"/api/todos/{todo_id}")
        assert response.status_code == 404

    def test_search_todos(self) -> None:
        """Test searching todos."""
        client.post(
            "/api/todos",
            json={"title": "Buy groceries", "description": "Milk and eggs"},
        )
        client.post(
            "/api/todos",
            json={"title": "Call mom", "description": "Weekly call"},
        )

        response = client.get("/api/todos/search?query=grocery")
        assert response.status_code == 200
        results = response.json()
        assert len(results) > 0
        assert any(
            any(term in todo["title"].lower() for term in ("grocery", "groceries"))
            for todo in results
        )
