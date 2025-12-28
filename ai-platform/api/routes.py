"""API routes for todo management."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from api.dependencies import get_todo_service
from models.todo import Todo, TodoCreate, TodoUpdate
from services.todo_service import TodoService

router = APIRouter()


@router.get("/todos", response_model=List[Todo])
def get_todos(
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of items to return"),
    service: TodoService = Depends(get_todo_service),
) -> List[Todo]:
    """Get all todo items with pagination."""
    return service.get_todos(skip=skip, limit=limit)


@router.get("/todos/search", response_model=List[Todo])
def search_todos(
    query: str = Query(..., min_length=1, description="Search query"),
    service: TodoService = Depends(get_todo_service),
) -> List[Todo]:
    """Search todos by title or description."""
    return service.search_todos(query)


@router.get("/todos/{todo_id}", response_model=Todo)
def get_todo(
    todo_id: int,
    service: TodoService = Depends(get_todo_service),
) -> Todo:
    """Get a specific todo item by ID."""
    todo = service.get_todo_by_id(todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


@router.post("/todos", response_model=Todo, status_code=status.HTTP_201_CREATED)
def create_todo(
    todo_data: TodoCreate,
    service: TodoService = Depends(get_todo_service),
) -> Todo:
    """Create a new todo item."""
    try:
        return service.create_todo(todo_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/todos/{todo_id}", response_model=Todo)
def update_todo(
    todo_id: int,
    todo_data: TodoUpdate,
    service: TodoService = Depends(get_todo_service),
) -> Todo:
    """Update an existing todo item."""
    try:
        todo = service.update_todo(todo_id, todo_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


@router.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_todo(
    todo_id: int,
    service: TodoService = Depends(get_todo_service),
) -> Response:
    """Delete a todo item."""
    success = service.delete_todo(todo_id)
    if not success:
        raise HTTPException(status_code=404, detail="Todo not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

