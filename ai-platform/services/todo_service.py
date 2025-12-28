"""Todo service - business logic layer."""

from __future__ import annotations

from typing import List, Optional

from models.todo import Todo, TodoCreate, TodoUpdate
from repositories.todo_repository import TodoRepository


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

    def create_todo(self, todo_data: TodoCreate) -> Todo:
        """Create a new todo item."""
        if not todo_data.title.strip():
            raise ValueError("Todo title cannot be empty")
        return self.repository.create(todo_data)

    def update_todo(self, todo_id: int, todo_data: TodoUpdate) -> Optional[Todo]:
        """Update an existing todo item."""
        existing_todo = self.repository.get_by_id(todo_id)
        if not existing_todo:
            return None
        if todo_data.title is not None and not todo_data.title.strip():
            raise ValueError("Todo title cannot be empty")
        return self.repository.update(todo_id, todo_data)

    def delete_todo(self, todo_id: int) -> bool:
        """Delete a todo item."""
        return self.repository.delete(todo_id)

    def search_todos(self, query: str) -> List[Todo]:
        """Search todos by title or description."""
        return self.repository.search(query)
