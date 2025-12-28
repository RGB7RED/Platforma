"""In-memory database for demo purposes."""

from dataclasses import dataclass, field
from typing import Dict

from models.todo import Todo


@dataclass
class InMemoryDatabase:
    """Simple in-memory storage."""

    todos: Dict[int, Todo] = field(default_factory=dict)
    next_id: int = 1

    def reset(self) -> None:
        """Reset the database to an empty state."""
        self.todos.clear()
        self.next_id = 1


db = InMemoryDatabase()
