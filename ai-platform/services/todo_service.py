"""Todo service - business logic layer."""

from __future__ import annotations

from typing import List, Optional

from models.todo import Todo, TodoCreate, TodoUpdate
from repositories.todo_repository import TodoRepository

__all__ = [
    "TodoService",
    "create_todo",
    "delete_todo",
    "get_default_repository",
    "get_default_service",
    "get_todo_by_id",
    "get_todos",
    "search_todos",
    "update_todo",
]


class TodoService:
    """Service for todo business logic."""

    def __init__(self, repository: Optional[TodoRepository] = None) -> None:
        self.repository = repository or TodoRepository()

    def get_todos(self, *, skip: int = 0, limit: int = 100) -> List[Todo]:
        """Get all todo items with pagination."""
        return self.repository.get_all(skip=skip, limit=limit)

    def get_all_todos(self, *, skip: int = 0, limit: int = 100) -> List[Todo]:
        """Alias for get_todos."""
        return self.get_todos(skip=skip, limit=limit)

    def get_todo_by_id(self, todo_id: int) -> Optional[Todo]:
        """Get a specific todo by ID."""
        return self.repository.get_by_id(todo_id)

    def get(self, todo_id: int) -> Optional[Todo]:
        """Alias for get_todo_by_id."""
        return self.get_todo_by_id(todo_id)

    def create_todo(self, todo_data: TodoCreate) -> Todo:
        """Create a new todo item."""
        if not todo_data.title.strip():
            raise ValueError("Todo title cannot be empty")
        return self.repository.create(todo_data)

    def create(self, todo_data: TodoCreate) -> Todo:
        """Alias for create_todo."""
        return self.create_todo(todo_data)

    def update_todo(self, todo_id: int, todo_data: TodoUpdate) -> Optional[Todo]:
        """Update an existing todo item."""
        existing_todo = self.repository.get_by_id(todo_id)
        if not existing_todo:
            return None
        if todo_data.title is not None and not todo_data.title.strip():
            raise ValueError("Todo title cannot be empty")
        return self.repository.update(todo_id, todo_data)

    def update(self, todo_id: int, todo_data: TodoUpdate) -> Optional[Todo]:
        """Alias for update_todo."""
        return self.update_todo(todo_id, todo_data)

    def delete_todo(self, todo_id: int) -> bool:
        """Delete a todo item."""
        return self.repository.delete(todo_id)

    def delete(self, todo_id: int) -> bool:
        """Alias for delete_todo."""
        return self.delete_todo(todo_id)

    def search_todos(self, query: str) -> List[Todo]:
        """Search todos by title or description."""
        return self.repository.search(query)

    def search(self, query: str) -> List[Todo]:
        """Alias for search_todos."""
        return self.search_todos(query)


_repository = TodoRepository()
_service = TodoService(_repository)


def get_default_repository() -> TodoRepository:
    """Return the default in-memory repository instance."""
    return _repository


def get_default_service() -> TodoService:
    """Return the default todo service instance."""
    return _service


def create_todo(todo_data: TodoCreate) -> Todo:
    """Create a new todo item."""
    return _service.create_todo(todo_data)


def get_todos(*, skip: int = 0, limit: int = 100) -> List[Todo]:
    """Get all todo items with pagination."""
    return _service.get_todos(skip=skip, limit=limit)


def get_todo_by_id(todo_id: int) -> Optional[Todo]:
    """Get a specific todo by ID."""
    return _service.get_todo_by_id(todo_id)


def update_todo(todo_id: int, todo_data: TodoUpdate) -> Optional[Todo]:
    """Update an existing todo item."""
    return _service.update_todo(todo_id, todo_data)


def delete_todo(todo_id: int) -> bool:
    """Delete a todo item."""
    return _service.delete_todo(todo_id)


def search_todos(query: str) -> List[Todo]:
    """Search todos by title or description."""
    return _service.search_todos(query)
