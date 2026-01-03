"""API routes for todo management."""

from typing import List

from fastapi import APIRouter, HTTPException, Query, Response, status

from models.todo import Todo, TodoCreate, TodoUpdate
from services.todo_service import (
    create_todo as create_todo_item,
    delete_todo as delete_todo_item,
    get_todo_by_id as get_todo_by_id_item,
    get_todos as get_todos_items,
    search_todos as search_todos_items,
    update_todo as update_todo_item,
)

router = APIRouter()


@router.get("/todos", response_model=List[Todo])
def get_todos(
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of items to return"),
) -> List[Todo]:
    """Get all todo items with pagination."""
    return get_todos_items(skip=skip, limit=limit)


@router.get("/todos/search", response_model=List[Todo])
def search_todos(
    query: str = Query(..., min_length=1, description="Search query"),
) -> List[Todo]:
    """Search todos by title or description."""
    return search_todos_items(query)


@router.get("/todos/{todo_id}", response_model=Todo)
def get_todo(
    todo_id: int,
) -> Todo:
    """Get a specific todo item by ID."""
    todo = get_todo_by_id_item(todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


@router.post("/todos", response_model=Todo, status_code=status.HTTP_201_CREATED)
def create_todo(
    todo_data: TodoCreate,
) -> Todo:
    """Create a new todo item."""
    try:
        return create_todo_item(todo_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/todos/{todo_id}", response_model=Todo)
def update_todo(
    todo_id: int,
    todo_data: TodoUpdate,
) -> Todo:
    """Update an existing todo item."""
    try:
        todo = update_todo_item(todo_id, todo_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


@router.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_todo(
    todo_id: int,
) -> Response:
    """Delete a todo item."""
    success = delete_todo_item(todo_id)
    if not success:
        raise HTTPException(status_code=404, detail="Todo not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
