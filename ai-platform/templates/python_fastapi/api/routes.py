from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException

from api.models import Todo, TodoCreate, TodoUpdate

router = APIRouter()

_todos: dict[int, Todo] = {}
_next_id = 1


@router.get("/todos", response_model=List[Todo])
def list_todos() -> List[Todo]:
    return list(_todos.values())


@router.post("/todos", response_model=Todo, status_code=201)
def create_todo(todo_data: TodoCreate) -> Todo:
    global _next_id
    todo = Todo(
        id=_next_id,
        title=todo_data.title,
        description=todo_data.description,
        completed=todo_data.completed,
        created_at=datetime.utcnow(),
    )
    _todos[_next_id] = todo
    _next_id += 1
    return todo


@router.get("/todos/{todo_id}", response_model=Todo)
def get_todo(todo_id: int) -> Todo:
    todo = _todos.get(todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


@router.put("/todos/{todo_id}", response_model=Todo)
def update_todo(todo_id: int, todo_data: TodoUpdate) -> Todo:
    todo = _todos.get(todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    update_data = todo_data.model_dump(exclude_unset=True)
    updated = todo.model_copy(update=update_data | {"updated_at": datetime.utcnow()})
    _todos[todo_id] = updated
    return updated


@router.delete("/todos/{todo_id}", status_code=204)
def delete_todo(todo_id: int) -> None:
    if todo_id not in _todos:
        raise HTTPException(status_code=404, detail="Todo not found")
    del _todos[todo_id]
