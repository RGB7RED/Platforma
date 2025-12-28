"""Todo domain models."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TodoBase(BaseModel):
    """Shared todo fields."""

    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    completed: bool = False


class TodoCreate(TodoBase):
    """Payload for creating todos."""


class TodoUpdate(BaseModel):
    """Payload for updating todos."""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    completed: Optional[bool] = None


class Todo(TodoBase):
    """Todo item."""

    id: int
    created_at: datetime
    updated_at: datetime
