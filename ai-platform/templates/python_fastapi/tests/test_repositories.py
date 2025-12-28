"""Repository tests."""

from database import InMemoryDatabase
from models.todo import TodoCreate, TodoUpdate
from repositories.todo_repository import TodoRepository


def test_repository_crud() -> None:
    """Repository can create, update, and delete todos."""
    database = InMemoryDatabase()
    repository = TodoRepository(database)

    todo = repository.create(TodoCreate(title="Repo todo"))
    assert repository.get_by_id(todo.id) is not None

    updated = repository.update(todo.id, TodoUpdate(completed=True))
    assert updated is not None
    assert updated.completed is True

    assert repository.delete(todo.id) is True
    assert repository.get_by_id(todo.id) is None
