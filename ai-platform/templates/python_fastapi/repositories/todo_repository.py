"""Todo repository implementation."""

from datetime import datetime
from typing import List, Optional

from database import InMemoryDatabase
from models.todo import Todo, TodoCreate, TodoUpdate


class TodoRepository:
    """Repository for todo data access."""

    def __init__(self, database: InMemoryDatabase) -> None:
        self._db = database

    def get_all(self, *, skip: int = 0, limit: int = 100) -> List[Todo]:
        """Return all todos with pagination."""
        todos = list(self._db.todos.values())
        return todos[skip : skip + limit]

    def get_by_id(self, todo_id: int) -> Optional[Todo]:
        """Return a todo by ID."""
        return self._db.todos.get(todo_id)

    def create(self, todo_data: TodoCreate) -> Todo:
        """Create a todo."""
        now = datetime.utcnow()
        todo = Todo(
            id=self._db.next_id,
            title=todo_data.title,
            description=todo_data.description,
            completed=todo_data.completed,
            created_at=now,
            updated_at=now,
        )
        self._db.todos[self._db.next_id] = todo
        self._db.next_id += 1
        return todo

    def update(self, todo_id: int, todo_data: TodoUpdate) -> Optional[Todo]:
        """Update an existing todo."""
        todo = self._db.todos.get(todo_id)
        if not todo:
            return None
        update_data = todo_data.model_dump(exclude_unset=True)
        updated = todo.model_copy(update=update_data | {"updated_at": datetime.utcnow()})
        self._db.todos[todo_id] = updated
        return updated

    def delete(self, todo_id: int) -> bool:
        """Delete a todo."""
        if todo_id in self._db.todos:
            del self._db.todos[todo_id]
            return True
        return False

    def search(self, query: str) -> List[Todo]:
        """Search todos by title or description."""
        if not query:
            return []
        query_lower = query.lower()
        results = []
        for todo in self._db.todos.values():
            title = todo.title.lower() if todo.title else ""
            description = todo.description.lower() if todo.description else ""
            if query_lower in title or query_lower in description:
                results.append(todo)
        return results
