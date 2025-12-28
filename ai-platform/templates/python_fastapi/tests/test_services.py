"""Service layer tests."""

from database import InMemoryDatabase
from models.todo import TodoCreate, TodoUpdate
from repositories.todo_repository import TodoRepository
from services.todo_service import TodoService


def test_service_create_and_update() -> None:
    """Create and update a todo through the service."""
    database = InMemoryDatabase()
    repository = TodoRepository(database)
    service = TodoService(repository)

    todo = service.create_todo(TodoCreate(title="Original"))
    assert todo.id == 1

    updated = service.update_todo(todo.id, TodoUpdate(title="Updated", completed=True))
    assert updated is not None
    assert updated.title == "Updated"
    assert updated.completed is True


def test_service_delete() -> None:
    """Delete a todo through the service."""
    database = InMemoryDatabase()
    service = TodoService(TodoRepository(database))

    todo = service.create_todo(TodoCreate(title="Delete me"))
    assert service.delete_todo(todo.id) is True
    assert service.get_todo_by_id(todo.id) is None
