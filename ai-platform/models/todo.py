"""Todo data models using Pydantic."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TodoBase(BaseModel):
    """Base model for todo items."""

    title: str = Field(..., max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    completed: bool = False


class TodoCreate(TodoBase):
    """Model for creating new todos."""


class TodoUpdate(BaseModel):
    """Model for updating existing todos."""

    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    completed: Optional[bool] = None


class Todo(TodoBase):
    """Complete todo model with system fields."""

    id: int
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    model_config = ConfigDict(from_attributes=True)
