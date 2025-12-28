"""Service layer tests."""

import sys
from pathlib import Path

from pytest import fixture, raises

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models.todo import TodoCreate, TodoUpdate  # noqa: E402
from repositories.todo_repository import TodoRepository  # noqa: E402
from services.todo_service import TodoService  # noqa: E402


@fixture
def todo_service() -> TodoService:
    """Create todo service for testing."""
    repository = TodoRepository()
    return TodoService(repository)


class TestTodoService:
    """Test suite for TodoService."""

    def test_create_and_get_todo(self, todo_service: TodoService) -> None:
        """Test creating and getting a todo."""
        todo_data = TodoCreate(title="Test todo")
        created_todo = todo_service.create_todo(todo_data)

        assert created_todo.id is not None
        assert created_todo.title == "Test todo"
        assert created_todo.completed is False

        retrieved_todo = todo_service.get_todo_by_id(created_todo.id)
        assert retrieved_todo is not None
        assert retrieved_todo.id == created_todo.id

    def test_create_todo_invalid_title(self, todo_service: TodoService) -> None:
        """Test creating todo with invalid title."""
        with raises(ValueError):
            todo_service.create_todo(TodoCreate(title=""))

    def test_get_all_todos(self, todo_service: TodoService) -> None:
        """Test getting all todos."""
        todo_service.create_todo(TodoCreate(title="Todo 1"))
        todo_service.create_todo(TodoCreate(title="Todo 2"))

        todos = todo_service.get_todos()
        assert len(todos) == 2
        assert todos[0].title == "Todo 1"
        assert todos[1].title == "Todo 2"

    def test_get_all_todos_pagination(self, todo_service: TodoService) -> None:
        """Test pagination for getting todos."""
        for i in range(15):
            todo_service.create_todo(TodoCreate(title=f"Todo {i}"))

        page1 = todo_service.get_todos(skip=0, limit=10)
        assert len(page1) == 10

        page2 = todo_service.get_todos(skip=10, limit=10)
        assert len(page2) == 5

    def test_update_todo(self, todo_service: TodoService) -> None:
        """Test updating a todo."""
        todo = todo_service.create_todo(TodoCreate(title="Original"))

        update_data = TodoUpdate(title="Updated", completed=True)
        updated_todo = todo_service.update_todo(todo.id, update_data)

        assert updated_todo is not None
        assert updated_todo.title == "Updated"
        assert updated_todo.completed is True

    def test_update_nonexistent_todo(self, todo_service: TodoService) -> None:
        """Test updating a todo that doesn't exist."""
        update_data = TodoUpdate(title="Updated")
        result = todo_service.update_todo(9999, update_data)
        assert result is None

    def test_delete_todo(self, todo_service: TodoService) -> None:
        """Test deleting a todo."""
        todo = todo_service.create_todo(TodoCreate(title="To delete"))

        result = todo_service.delete_todo(todo.id)
        assert result is True

        deleted_todo = todo_service.get_todo_by_id(todo.id)
        assert deleted_todo is None

    def test_delete_nonexistent_todo(self, todo_service: TodoService) -> None:
        """Test deleting a todo that doesn't exist."""
        result = todo_service.delete_todo(9999)
        assert result is False

    def test_search_todos(self, todo_service: TodoService) -> None:
        """Test searching todos."""
        todo_service.create_todo(
            TodoCreate(title="Buy groceries", description="Milk and eggs")
        )
        todo_service.create_todo(TodoCreate(title="Call mom", description="Weekly call"))

        results = todo_service.search_todos("grocery")
        assert len(results) == 1
        assert any(
            term in results[0].title.lower()
            for term in ("grocery", "groceries")
        )

        results = todo_service.search_todos("call")
        assert len(results) == 1
        assert "call" in results[0].title.lower()

        results = todo_service.search_todos("")
        assert len(results) == 0
