"""Database utilities for task persistence.

Smoke check:
  - Without DATABASE_URL: start the app, POST /api/tasks, then GET /api/tasks/{task_id}.
  - With DATABASE_URL set: POST /api/tasks, restart server, then GET /api/tasks/{task_id}.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


def is_enabled() -> bool:
    return _pool is not None


async def init_db(database_url: str) -> None:
    global _pool

    if _pool is not None:
        return

    _pool = await asyncpg.create_pool(dsn=database_url, min_size=1, max_size=5)
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id UUID PRIMARY KEY,
                user_id TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                progress DOUBLE PRECISION NOT NULL DEFAULT 0,
                current_stage TEXT NULL,
                codex_version TEXT NULL,
                client_ip TEXT NULL,
                result JSONB NULL,
                error TEXT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at TIMESTAMPTZ NULL
            );
            """
        )
    logger.info("Database initialized for task persistence")


async def close_db() -> None:
    global _pool

    if _pool is None:
        return

    await _pool.close()
    _pool = None
    logger.info("Database pool closed")


def _coerce_task_id(task_id: str) -> uuid.UUID:
    return task_id if isinstance(task_id, uuid.UUID) else uuid.UUID(task_id)


def _row_to_dict(row: Optional[asyncpg.Record]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return dict(row)


async def create_task_row(
    *,
    task_id: str,
    user_id: str,
    description: str,
    status: str,
    progress: float,
    current_stage: Optional[str],
    codex_version: Optional[str],
    client_ip: Optional[str],
) -> Dict[str, Any]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")

    row = await _pool.fetchrow(
        """
        INSERT INTO tasks (
            id, user_id, description, status, progress, current_stage, codex_version, client_ip
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING *;
        """,
        _coerce_task_id(task_id),
        user_id,
        description,
        status,
        progress,
        current_stage,
        codex_version,
        client_ip,
    )
    return _row_to_dict(row) or {}


async def update_task_row(task_id: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")

    allowed_fields = {
        "user_id",
        "description",
        "status",
        "progress",
        "current_stage",
        "codex_version",
        "client_ip",
        "result",
        "error",
        "completed_at",
    }
    updates = {key: value for key, value in fields.items() if key in allowed_fields}

    if not updates:
        return await get_task_row(task_id)

    set_clauses = []
    values: List[Any] = []
    for idx, (key, value) in enumerate(updates.items(), start=1):
        set_clauses.append(f"{key} = ${idx}")
        values.append(value)
    set_clauses.append("updated_at = NOW()")

    values.append(_coerce_task_id(task_id))
    query = f"UPDATE tasks SET {', '.join(set_clauses)} WHERE id = ${len(values)} RETURNING *;"

    row = await _pool.fetchrow(query, *values)
    return _row_to_dict(row)


async def get_task_row(task_id: str) -> Optional[Dict[str, Any]]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")

    row = await _pool.fetchrow(
        "SELECT * FROM tasks WHERE id = $1;",
        _coerce_task_id(task_id),
    )
    return _row_to_dict(row)


async def list_tasks_for_user(user_id: str, limit: int) -> List[Dict[str, Any]]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")

    rows = await _pool.fetch(
        """
        SELECT * FROM tasks
        WHERE user_id = $1
        ORDER BY created_at DESC
        LIMIT $2;
        """,
        user_id,
        limit,
    )
    return [dict(row) for row in rows]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
