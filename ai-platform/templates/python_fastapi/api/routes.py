from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_todo_service
from api.models import Todo, TodoCreate, TodoUpdate
from services.todo_service import TodoService

router = APIRouter()


@router.get("/todos", response_model=List[Todo])
def list_todos(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1),
    service: TodoService = Depends(get_todo_service),
) -> List[Todo]:
    return service.get_all_todos(skip=skip, limit=limit)


@router.post("/todos", response_model=Todo, status_code=201)
def create_todo(
    todo_data: TodoCreate,
    service: TodoService = Depends(get_todo_service),
) -> Todo:
    try:
        return service.create_todo(todo_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/todos/{todo_id}", response_model=Todo)
def get_todo(
    todo_id: int,
    service: TodoService = Depends(get_todo_service),
) -> Todo:
    todo = service.get_todo_by_id(todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


@router.put("/todos/{todo_id}", response_model=Todo)
def update_todo(
    todo_id: int,
    todo_data: TodoUpdate,
    service: TodoService = Depends(get_todo_service),
) -> Todo:
    todo = service.update_todo(todo_id, todo_data)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


@router.delete("/todos/{todo_id}", status_code=204)
def delete_todo(
    todo_id: int,
    service: TodoService = Depends(get_todo_service),
) -> None:
    success = service.delete_todo(todo_id)
    if not success:
        raise HTTPException(status_code=404, detail="Todo not found")


@router.get("/todos/search", response_model=List[Todo])
def search_todos(
    query: str = Query(..., min_length=1),
    service: TodoService = Depends(get_todo_service),
) -> List[Todo]:
    return service.search_todos(query)
