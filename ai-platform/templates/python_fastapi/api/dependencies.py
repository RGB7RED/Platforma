"""Dependency providers for the FastAPI app."""

from fastapi import Depends

from database import InMemoryDatabase, db
from repositories.todo_repository import TodoRepository
from services.todo_service import TodoService


def get_db() -> InMemoryDatabase:
    """Provide the in-memory database instance."""
    return db


def get_todo_repository(
    database: InMemoryDatabase = Depends(get_db),
) -> TodoRepository:
    """Provide the todo repository."""
    return TodoRepository(database)


def get_todo_service(
    repository: TodoRepository = Depends(get_todo_repository),
) -> TodoService:
    """Provide the todo service."""
    return TodoService(repository)
