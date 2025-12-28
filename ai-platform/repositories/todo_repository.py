"""Todo repository - data access layer."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from models.todo import Todo, TodoCreate, TodoUpdate


class TodoRepository:
    """Repository for todo data access with in-memory storage."""

    def __init__(self) -> None:
        self._todos: dict[int, Todo] = {}
        self._next_id = 1

    def get_all(self, *, skip: int = 0, limit: int = 100) -> List[Todo]:
        """Get all todos with pagination."""
        todos = list(self._todos.values())
        return todos[skip : skip + limit]

    def get_by_id(self, todo_id: int) -> Optional[Todo]:
        """Get todo by ID."""
        return self._todos.get(todo_id)

    def create(self, todo_data: TodoCreate) -> Todo:
        """Create a new todo."""
        now = datetime.now()
        todo = Todo(
            id=self._next_id,
            title=todo_data.title,
            description=todo_data.description,
            completed=todo_data.completed,
            created_at=now,
            updated_at=now,
        )
        self._todos[self._next_id] = todo
        self._next_id += 1
        return todo

    def save(self, todo_data: TodoCreate) -> Todo:
        """Save a new todo (alias for create)."""
        return self.create(todo_data)

    def update(self, todo_id: int, todo_data: TodoUpdate) -> Optional[Todo]:
        """Update an existing todo."""
        todo = self._todos.get(todo_id)
        if not todo:
            return None
        update_data = todo_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(todo, field, value)
        todo.updated_at = datetime.now()
        return todo

    def delete(self, todo_id: int) -> bool:
        """Delete a todo."""
        if todo_id in self._todos:
            del self._todos[todo_id]
            return True
        return False

    def clear(self) -> None:
        """Clear all stored todos (testing helper)."""
        self._todos.clear()
        self._next_id = 1

    def search(self, query: str) -> List[Todo]:
        """Search todos by title or description."""
        if not query:
            return []
        query_folded = query.casefold()
        query_variants = {query_folded}
        if query_folded.endswith("y"):
            query_variants.add(f"{query_folded[:-1]}ies")
        if query_folded.endswith("ies"):
            query_variants.add(f"{query_folded[:-3]}y")

        def matches(text: str) -> bool:
            text_folded = text.casefold()
            return any(variant in text_folded for variant in query_variants)
        results = []
        for todo in self._todos.values():
            if todo.title and matches(todo.title):
                results.append(todo)
                continue
            if todo.description and matches(todo.description):
                results.append(todo)
        return results
