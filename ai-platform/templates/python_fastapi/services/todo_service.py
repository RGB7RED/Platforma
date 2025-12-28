"""Business logic for todos."""

from typing import List, Optional

from models.todo import Todo, TodoCreate, TodoUpdate
from repositories.todo_repository import TodoRepository


class TodoService:
    """Service layer for todo operations."""

    def __init__(self, repository: TodoRepository) -> None:
        self._repository = repository

    def get_all_todos(self, *, skip: int = 0, limit: int = 100) -> List[Todo]:
        """Get all todo items."""
        return self._repository.get_all(skip=skip, limit=limit)

    def get_todo_by_id(self, todo_id: int) -> Optional[Todo]:
        """Get a todo by ID."""
        return self._repository.get_by_id(todo_id)

    def create_todo(self, todo_data: TodoCreate) -> Todo:
        """Create a new todo item."""
        if not todo_data.title.strip():
            raise ValueError("Todo title cannot be empty")
        return self._repository.create(todo_data)

    def update_todo(self, todo_id: int, todo_data: TodoUpdate) -> Optional[Todo]:
        """Update an existing todo."""
        if todo_data.title is not None and not todo_data.title.strip():
            raise ValueError("Todo title cannot be empty")
        return self._repository.update(todo_id, todo_data)

    def delete_todo(self, todo_id: int) -> bool:
        """Delete a todo by ID."""
        return self._repository.delete(todo_id)

    def search_todos(self, query: str) -> List[Todo]:
        """Search todos by query."""
        return self._repository.search(query)
