"""Database utilities for task persistence.

Smoke check:
  - Without DATABASE_URL: start the app, POST /api/tasks, then GET /api/tasks/{task_id}.
  - With DATABASE_URL set: POST /api/tasks, restart server, then GET /api/tasks/{task_id}.
"""

from __future__ import annotations

import json
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
                container_state JSONB NULL,
                error TEXT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at TIMESTAMPTZ NULL
            );
            """
        )
        await _ensure_jsonb_column(conn, table="tasks", column="result")
        await _ensure_jsonb_column(conn, table="tasks", column="container_state")
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


def _json_payload(payload: Any) -> str:
    if payload is None:
        payload = {}
    return json.dumps(payload, default=str)


def _log_db_error(action: str, details: Dict[str, Any]) -> None:
    summary = {key: type(value).__name__ for key, value in details.items()}
    logger.exception("Database %s failed (types=%s)", action, summary)


def _coerce_json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


async def _ensure_jsonb_column(
    conn: asyncpg.Connection,
    *,
    table: str,
    column: str,
    nullable: bool = True,
) -> None:
    data_type = await conn.fetchval(
        """
        SELECT data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = $1
          AND column_name = $2;
        """,
        table,
        column,
    )
    if data_type is None:
        null_sql = "NULL" if nullable else "NOT NULL"
        await conn.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} JSONB {null_sql};"
        )
        return

    if data_type == "jsonb":
        return

    await conn.execute(
        f"""
        ALTER TABLE {table}
        ALTER COLUMN {column} TYPE JSONB
        USING (
            CASE
                WHEN {column} IS NULL THEN NULL
                WHEN {column}::text ~ '^\\s*(\\{{.*\\}}|\\[.*\\])\\s*$' THEN {column}::jsonb
                ELSE to_jsonb({column})
            END
        );
        """
    )


async def init_container_tables(pool: Optional[asyncpg.Pool] = None) -> None:
    pool = pool or _pool
    if pool is None:
        logger.info("Database not enabled; skipping container table initialization")
        return

    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id UUID PRIMARY KEY,
                task_id UUID NOT NULL,
                type TEXT NOT NULL,
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        await _ensure_jsonb_column(conn, table="events", column="payload", nullable=False)
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS events_task_id_created_at_idx
            ON events (task_id, created_at);
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS artifacts (
                id UUID PRIMARY KEY,
                task_id UUID NOT NULL,
                type TEXT NOT NULL,
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                produced_by TEXT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        await _ensure_jsonb_column(conn, table="artifacts", column="payload", nullable=False)
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS artifacts_task_id_created_at_idx
            ON artifacts (task_id, created_at);
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS artifacts_task_id_type_idx
            ON artifacts (task_id, type);
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS container_state (
                task_id UUID PRIMARY KEY,
                state JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        await _ensure_jsonb_column(conn, table="container_state", column="state", nullable=False)
    logger.info("Database initialized for container persistence")


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

    try:
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
    except Exception:
        _log_db_error(
            "create_task_row",
            {
                "task_id": task_id,
                "user_id": user_id,
                "status": status,
                "progress": progress,
            },
        )
        raise
    return _row_to_dict(row) or {}


async def append_event(task_id: str, type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    if _pool is None:
        logger.debug("Database not enabled; skipping append_event for task %s", task_id)
        return

    try:
        await _pool.execute(
            """
            INSERT INTO events (id, task_id, type, payload)
            VALUES ($1, $2, $3, $4::jsonb);
            """,
            uuid.uuid4(),
            _coerce_task_id(task_id),
            type,
            _json_payload(payload),
        )
    except Exception:
        _log_db_error(
            "append_event",
            {"task_id": task_id, "type": type, "payload": payload},
        )
        raise


async def add_artifact(
    task_id: str,
    type: str,
    payload: Optional[Dict[str, Any]] = None,
    produced_by: Optional[str] = None,
) -> None:
    if _pool is None:
        logger.debug("Database not enabled; skipping add_artifact for task %s", task_id)
        return

    try:
        await _pool.execute(
            """
            INSERT INTO artifacts (id, task_id, type, payload, produced_by)
            VALUES ($1, $2, $3, $4::jsonb, $5);
            """,
            uuid.uuid4(),
            _coerce_task_id(task_id),
            type,
            _json_payload(payload),
            produced_by,
        )
    except Exception:
        _log_db_error(
            "add_artifact",
            {"task_id": task_id, "type": type, "payload": payload},
        )
        raise


async def get_events(task_id: str, limit: int = 200, order: str = "desc") -> List[Dict[str, Any]]:
    if _pool is None:
        logger.debug("Database not enabled; returning empty events for task %s", task_id)
        return []

    direction = "DESC" if order.lower() == "desc" else "ASC"
    query = f"""
        SELECT id, type, payload, created_at
        FROM events
        WHERE task_id = $1
        ORDER BY created_at {direction}
        LIMIT $2;
    """
    rows = await _pool.fetch(query, _coerce_task_id(task_id), limit)
    events = [dict(row) for row in rows]
    for event in events:
        event["payload"] = _coerce_json_value(event.get("payload"))
    return events


async def get_artifacts(
    task_id: str,
    type: Optional[str] = None,
    limit: int = 200,
    order: str = "desc",
) -> List[Dict[str, Any]]:
    if _pool is None:
        logger.debug("Database not enabled; returning empty artifacts for task %s", task_id)
        return []

    direction = "DESC" if order.lower() == "desc" else "ASC"
    if type:
        query = f"""
            SELECT id, type, produced_by, payload, created_at
            FROM artifacts
            WHERE task_id = $1 AND type = $2
            ORDER BY created_at {direction}
            LIMIT $3;
        """
        rows = await _pool.fetch(query, _coerce_task_id(task_id), type, limit)
    else:
        query = f"""
            SELECT id, type, produced_by, payload, created_at
            FROM artifacts
            WHERE task_id = $1
            ORDER BY created_at {direction}
            LIMIT $2;
        """
        rows = await _pool.fetch(query, _coerce_task_id(task_id), limit)

    artifacts = [dict(row) for row in rows]
    for artifact in artifacts:
        artifact["payload"] = _coerce_json_value(artifact.get("payload"))
    return artifacts


async def set_container_state(task_id: str, state: Optional[Dict[str, Any]] = None) -> None:
    if _pool is None:
        logger.debug("Database not enabled; skipping set_container_state for task %s", task_id)
        return

    try:
        await _pool.execute(
            """
            INSERT INTO container_state (task_id, state)
            VALUES ($1, $2::jsonb)
            ON CONFLICT (task_id)
            DO UPDATE SET state = EXCLUDED.state, updated_at = NOW();
            """,
            _coerce_task_id(task_id),
            _json_payload(state),
        )
    except Exception:
        _log_db_error("set_container_state", {"task_id": task_id, "state": state})
        raise


async def get_container_state(task_id: str) -> Optional[Dict[str, Any]]:
    if _pool is None:
        logger.debug("Database not enabled; returning empty container state for task %s", task_id)
        return None

    row = await _pool.fetchrow(
        "SELECT task_id, state, updated_at FROM container_state WHERE task_id = $1;",
        _coerce_task_id(task_id),
    )
    data = _row_to_dict(row)
    if data:
        data["state"] = _coerce_json_value(data.get("state"))
    return data


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
        "container_state",
        "error",
        "completed_at",
    }
    updates = {key: value for key, value in fields.items() if key in allowed_fields}

    if not updates:
        return await get_task_row(task_id)

    set_clauses = []
    values: List[Any] = []
    json_fields = {"result", "container_state"}
    for idx, (key, value) in enumerate(updates.items(), start=1):
        if key in json_fields:
            set_clauses.append(f"{key} = ${idx}::jsonb")
            values.append(_json_payload(value))
        else:
            set_clauses.append(f"{key} = ${idx}")
            values.append(value)
    set_clauses.append("updated_at = NOW()")

    values.append(_coerce_task_id(task_id))
    query = f"UPDATE tasks SET {', '.join(set_clauses)} WHERE id = ${len(values)} RETURNING *;"

    try:
        row = await _pool.fetchrow(query, *values)
    except Exception:
        _log_db_error("update_task_row", updates)
        raise
    return _row_to_dict(row)


async def get_task_row(task_id: str) -> Optional[Dict[str, Any]]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")

    row = await _pool.fetchrow(
        "SELECT * FROM tasks WHERE id = $1;",
        _coerce_task_id(task_id),
    )
    data = _row_to_dict(row)
    if data:
        data["result"] = _coerce_json_value(data.get("result"))
        data["container_state"] = _coerce_json_value(data.get("container_state"))
    return data


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
    tasks = [dict(row) for row in rows]
    for task in tasks:
        task["result"] = _coerce_json_value(task.get("result"))
        task["container_state"] = _coerce_json_value(task.get("container_state"))
    return tasks


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
