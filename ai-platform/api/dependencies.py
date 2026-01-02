"""API dependencies for todo management."""

from repositories.todo_repository import TodoRepository
from services.todo_service import TodoService, get_default_repository, get_default_service


def get_todo_repository() -> TodoRepository:
    """Dependency for getting todo repository instance."""
    return get_default_repository()


def get_todo_service() -> TodoService:
    """Dependency for getting todo service instance."""
    return get_default_service()
