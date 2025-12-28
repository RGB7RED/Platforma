"""API dependencies for todo management."""

from fastapi import Depends, HTTPException

from repositories.todo_repository import TodoRepository
from services.todo_service import TodoService

_repository = TodoRepository()


def get_todo_repository() -> TodoRepository:
    """Dependency for getting todo repository instance."""
    return _repository


def get_todo_service(
    repository: TodoRepository = Depends(get_todo_repository),
) -> TodoService:
    """Dependency for getting todo service instance."""
    try:
        return TodoService(repository)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
