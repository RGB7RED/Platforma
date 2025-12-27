"""Database utilities for task persistence.

Smoke check:
  - Without DATABASE_URL: start the app, POST /api/tasks, then GET /api/tasks/{task_id}.
  - With DATABASE_URL set: POST /api/tasks, restart server, then GET /api/tasks/{task_id}.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None
_rate_limits: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
_usage_daily: Dict[Tuple[str, date], Dict[str, Any]] = {}


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
                owner_user_id TEXT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                progress DOUBLE PRECISION NOT NULL DEFAULT 0,
                current_stage TEXT NULL,
                codex_version TEXT NULL,
                template_id TEXT NULL,
                template_hash TEXT NULL,
                client_ip TEXT NULL,
                owner_key_hash TEXT NULL,
                pending_questions JSONB NULL,
                provided_answers JSONB NULL,
                resume_from_stage TEXT NULL,
                result JSONB NULL,
                container_state JSONB NULL,
                error TEXT NULL,
                failure_reason TEXT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at TIMESTAMPTZ NULL
            );
            """
        )
        await conn.execute(
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS owner_key_hash TEXT;"
        )
        await conn.execute(
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS owner_user_id TEXT;"
        )
        await conn.execute(
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS failure_reason TEXT;"
        )
        await conn.execute(
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS template_id TEXT;"
        )
        await conn.execute(
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS template_hash TEXT;"
        )
        await conn.execute(
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS pending_questions JSONB;"
        )
        await conn.execute(
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS provided_answers JSONB;"
        )
        await conn.execute(
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS resume_from_stage TEXT;"
        )
        await _ensure_jsonb_column(conn, table="tasks", column="result")
        await _ensure_jsonb_column(conn, table="tasks", column="container_state")
        await _ensure_jsonb_column(conn, table="tasks", column="pending_questions")
        await _ensure_jsonb_column(conn, table="tasks", column="provided_answers")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_rate_limits (
                key_hash TEXT NOT NULL,
                scope TEXT NOT NULL,
                window_start TIMESTAMPTZ NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (key_hash, scope, window_start)
            );
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_usage_daily (
                key_hash TEXT NOT NULL,
                usage_date DATE NOT NULL,
                tokens_in BIGINT NOT NULL DEFAULT 0,
                tokens_out BIGINT NOT NULL DEFAULT 0,
                command_runs INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (key_hash, usage_date)
            );
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_users (
                id UUID PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                email_verified_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        await conn.execute(
            "ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ;"
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_refresh_sessions (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                expires_at TIMESTAMPTZ NOT NULL,
                revoked_at TIMESTAMPTZ NULL,
                rotated_at TIMESTAMPTZ NULL,
                last_used_at TIMESTAMPTZ NULL,
                user_agent TEXT NULL,
                ip_address TEXT NULL
            );
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS auth_refresh_sessions_user_id_idx
            ON auth_refresh_sessions (user_id);
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS email_verify_tokens (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS email_verify_tokens_user_id_idx
            ON email_verify_tokens (user_id);
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS password_reset_tokens_user_id_idx
            ON password_reset_tokens (user_id);
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_oauth_accounts (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
                provider TEXT NOT NULL,
                provider_account_id TEXT NOT NULL,
                email TEXT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (provider, provider_account_id),
                UNIQUE (user_id, provider)
            );
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS auth_oauth_accounts_user_id_idx
            ON auth_oauth_accounts (user_id);
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


def _coerce_user_id(user_id: str) -> uuid.UUID:
    return user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(user_id)


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
            CREATE TABLE IF NOT EXISTS task_events (
                id UUID PRIMARY KEY,
                task_id UUID NOT NULL,
                type TEXT NOT NULL,
                payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        await _ensure_jsonb_column(conn, table="task_events", column="payload_json", nullable=False)
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS events_task_id_created_at_idx
            ON task_events (task_id, created_at);
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_artifacts (
                id UUID PRIMARY KEY,
                task_id UUID NOT NULL,
                type TEXT NOT NULL,
                produced_by TEXT NULL,
                payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        await _ensure_jsonb_column(conn, table="task_artifacts", column="payload_json", nullable=False)
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS artifacts_task_id_created_at_idx
            ON task_artifacts (task_id, created_at);
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS artifacts_task_id_type_idx
            ON task_artifacts (task_id, type);
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_state (
                task_id UUID PRIMARY KEY,
                state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        await _ensure_jsonb_column(conn, table="task_state", column="state_json", nullable=False)
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_files (
                task_id UUID NOT NULL,
                path TEXT NOT NULL,
                content TEXT NULL,
                content_bytes BYTEA NULL,
                mime_type TEXT NULL,
                sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (task_id, path)
            );
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS task_files_task_id_idx
            ON task_files (task_id);
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_container_snapshots (
                task_id UUID PRIMARY KEY,
                snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        await _ensure_jsonb_column(
            conn,
            table="task_container_snapshots",
            column="snapshot_json",
            nullable=False,
        )
    logger.info("Database initialized for container persistence")


async def create_task_row(
    *,
    task_id: str,
    user_id: str,
    owner_user_id: Optional[str],
    description: str,
    status: str,
    progress: float,
    current_stage: Optional[str],
    codex_version: Optional[str],
    template_id: Optional[str],
    template_hash: Optional[str],
    client_ip: Optional[str],
    owner_key_hash: str,
) -> Dict[str, Any]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")

    try:
        row = await _pool.fetchrow(
            """
            INSERT INTO tasks (
                id,
                user_id,
                owner_user_id,
                description,
                status,
                progress,
                current_stage,
                codex_version,
                template_id,
                template_hash,
                client_ip,
                owner_key_hash
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            RETURNING *;
            """,
            _coerce_task_id(task_id),
            user_id,
            owner_user_id,
            description,
            status,
            progress,
            current_stage,
            codex_version,
            template_id,
            template_hash,
            client_ip,
            owner_key_hash,
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
            INSERT INTO task_events (id, task_id, type, payload_json)
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
            INSERT INTO task_artifacts (id, task_id, type, payload_json, produced_by)
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
        SELECT id, type, payload_json, created_at
        FROM task_events
        WHERE task_id = $1
        ORDER BY created_at {direction}
        LIMIT $2;
    """
    rows = await _pool.fetch(query, _coerce_task_id(task_id), limit)
    events = [dict(row) for row in rows]
    for event in events:
        event["payload"] = _coerce_json_value(event.pop("payload_json", None))
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
            SELECT id, type, produced_by, payload_json, created_at
            FROM task_artifacts
            WHERE task_id = $1 AND type = $2
            ORDER BY created_at {direction}
            LIMIT $3;
        """
        rows = await _pool.fetch(query, _coerce_task_id(task_id), type, limit)
    else:
        query = f"""
            SELECT id, type, produced_by, payload_json, created_at
            FROM task_artifacts
            WHERE task_id = $1
            ORDER BY created_at {direction}
            LIMIT $2;
        """
        rows = await _pool.fetch(query, _coerce_task_id(task_id), limit)

    artifacts = [dict(row) for row in rows]
    for artifact in artifacts:
        artifact["payload"] = _coerce_json_value(artifact.pop("payload_json", None))
    return artifacts


async def set_container_state(task_id: str, state: Optional[Dict[str, Any]] = None) -> None:
    if _pool is None:
        logger.debug("Database not enabled; skipping set_container_state for task %s", task_id)
        return

    try:
        await _pool.execute(
            """
            INSERT INTO task_state (task_id, state_json)
            VALUES ($1, $2::jsonb)
            ON CONFLICT (task_id)
            DO UPDATE SET state_json = EXCLUDED.state_json, updated_at = NOW();
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
        "SELECT task_id, state_json, updated_at FROM task_state WHERE task_id = $1;",
        _coerce_task_id(task_id),
    )
    data = _row_to_dict(row)
    if data:
        data["state"] = _coerce_json_value(data.pop("state_json", None))
    return data


async def upsert_task_file(
    task_id: str,
    path: str,
    *,
    content: Optional[str],
    content_bytes: Optional[bytes],
    mime_type: Optional[str],
    sha256: str,
    size_bytes: int,
    max_bytes: Optional[int] = None,
    max_files: Optional[int] = None,
) -> None:
    if _pool is None:
        logger.debug("Database not enabled; skipping upsert_task_file for task %s", task_id)
        return

    try:
        async with _pool.acquire() as conn:
            async with conn.transaction():
                existing = await conn.fetchrow(
                    """
                    SELECT size_bytes
                    FROM task_files
                    WHERE task_id = $1 AND path = $2;
                    """,
                    _coerce_task_id(task_id),
                    path,
                )
                stats = await conn.fetchrow(
                    """
                    SELECT COUNT(*) AS count, COALESCE(SUM(size_bytes), 0) AS total
                    FROM task_files
                    WHERE task_id = $1;
                    """,
                    _coerce_task_id(task_id),
                )
                current_count = int(stats["count"]) if stats else 0
                current_total = int(stats["total"]) if stats else 0
                previous_size = int(existing["size_bytes"]) if existing else 0
                new_count = current_count if existing else current_count + 1
                new_total = current_total - previous_size + size_bytes

                if max_files is not None and max_files > 0 and new_count > max_files:
                    raise ValueError(
                        f"Task file count limit exceeded ({new_count} > {max_files})"
                    )
                if max_bytes is not None and max_bytes > 0 and new_total > max_bytes:
                    raise ValueError(
                        f"Task storage limit exceeded ({new_total} > {max_bytes} bytes)"
                    )

                await conn.execute(
                    """
                    INSERT INTO task_files (
                        task_id,
                        path,
                        content,
                        content_bytes,
                        mime_type,
                        sha256,
                        size_bytes,
                        updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                    ON CONFLICT (task_id, path)
                    DO UPDATE SET
                        content = EXCLUDED.content,
                        content_bytes = EXCLUDED.content_bytes,
                        mime_type = EXCLUDED.mime_type,
                        sha256 = EXCLUDED.sha256,
                        size_bytes = EXCLUDED.size_bytes,
                        updated_at = NOW();
                    """,
                    _coerce_task_id(task_id),
                    path,
                    content,
                    content_bytes,
                    mime_type,
                    sha256,
                    size_bytes,
                )
    except Exception:
        _log_db_error(
            "upsert_task_file",
            {
                "task_id": task_id,
                "path": path,
                "size_bytes": size_bytes,
                "mime_type": mime_type,
            },
        )
        raise


async def delete_task_file(task_id: str, path: str) -> None:
    if _pool is None:
        logger.debug("Database not enabled; skipping delete_task_file for task %s", task_id)
        return

    try:
        await _pool.execute(
            """
            DELETE FROM task_files
            WHERE task_id = $1 AND path = $2;
            """,
            _coerce_task_id(task_id),
            path,
        )
    except Exception:
        _log_db_error(
            "delete_task_file",
            {"task_id": task_id, "path": path},
        )
        raise


async def list_task_files(task_id: str) -> List[Dict[str, Any]]:
    if _pool is None:
        logger.debug("Database not enabled; returning empty task files for task %s", task_id)
        return []

    rows = await _pool.fetch(
        """
        SELECT path, mime_type, sha256, size_bytes, updated_at
        FROM task_files
        WHERE task_id = $1
        ORDER BY path ASC;
        """,
        _coerce_task_id(task_id),
    )
    return [dict(row) for row in rows]


async def get_task_file(task_id: str, path: str) -> Optional[Dict[str, Any]]:
    if _pool is None:
        logger.debug("Database not enabled; returning empty task file for task %s", task_id)
        return None

    row = await _pool.fetchrow(
        """
        SELECT path, content, content_bytes, mime_type, sha256, size_bytes, updated_at
        FROM task_files
        WHERE task_id = $1 AND path = $2;
        """,
        _coerce_task_id(task_id),
        path,
    )
    return _row_to_dict(row)


async def list_task_files_with_payload(task_id: str) -> List[Dict[str, Any]]:
    if _pool is None:
        logger.debug("Database not enabled; returning empty task files for task %s", task_id)
        return []

    rows = await _pool.fetch(
        """
        SELECT path, content, content_bytes, mime_type, sha256, size_bytes, updated_at
        FROM task_files
        WHERE task_id = $1
        ORDER BY path ASC;
        """,
        _coerce_task_id(task_id),
    )
    return [dict(row) for row in rows]


async def upsert_container_snapshot(task_id: str, snapshot: Dict[str, Any]) -> None:
    if _pool is None:
        logger.debug("Database not enabled; skipping upsert_container_snapshot for task %s", task_id)
        return

    try:
        await _pool.execute(
            """
            INSERT INTO task_container_snapshots (task_id, snapshot_json)
            VALUES ($1, $2::jsonb)
            ON CONFLICT (task_id)
            DO UPDATE SET snapshot_json = EXCLUDED.snapshot_json, updated_at = NOW();
            """,
            _coerce_task_id(task_id),
            _json_payload(snapshot),
        )
    except Exception:
        _log_db_error("upsert_container_snapshot", {"task_id": task_id})
        raise


async def get_container_snapshot(task_id: str) -> Optional[Dict[str, Any]]:
    if _pool is None:
        logger.debug("Database not enabled; returning empty container snapshot for task %s", task_id)
        return None

    row = await _pool.fetchrow(
        """
        SELECT task_id, snapshot_json, updated_at
        FROM task_container_snapshots
        WHERE task_id = $1;
        """,
        _coerce_task_id(task_id),
    )
    data = _row_to_dict(row)
    if data:
        data["snapshot"] = _coerce_json_value(data.pop("snapshot_json", None))
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
        "pending_questions",
        "provided_answers",
        "resume_from_stage",
        "error",
        "failure_reason",
        "completed_at",
    }
    updates = {key: value for key, value in fields.items() if key in allowed_fields}

    if not updates:
        return await get_task_row(task_id)

    set_clauses = []
    values: List[Any] = []
    json_fields = {"result", "container_state", "pending_questions", "provided_answers"}
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
        data["pending_questions"] = _coerce_json_value(data.get("pending_questions"))
        data["provided_answers"] = _coerce_json_value(data.get("provided_answers"))
    return data


async def list_tasks_for_owner_user(
    owner_user_id: str,
    owner_key_hash: Optional[str],
    limit: int,
) -> List[Dict[str, Any]]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")

    if owner_key_hash:
        rows = await _pool.fetch(
            """
            SELECT * FROM tasks
            WHERE owner_user_id = $1
               OR (owner_user_id IS NULL AND owner_key_hash = $2)
            ORDER BY created_at DESC
            LIMIT $3;
            """,
            owner_user_id,
            owner_key_hash,
            limit,
        )
    else:
        rows = await _pool.fetch(
            """
            SELECT * FROM tasks
            WHERE owner_user_id = $1
            ORDER BY created_at DESC
            LIMIT $2;
            """,
            owner_user_id,
            limit,
        )
    tasks = [dict(row) for row in rows]
    for task in tasks:
        task["result"] = _coerce_json_value(task.get("result"))
        task["container_state"] = _coerce_json_value(task.get("container_state"))
    return tasks


async def list_tasks_for_owner_key(
    owner_key_hash: str,
    limit: int,
    *,
    user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")

    if user_id:
        rows = await _pool.fetch(
            """
            SELECT * FROM tasks
            WHERE owner_key_hash = $1 AND user_id = $2
            ORDER BY created_at DESC
            LIMIT $3;
            """,
            owner_key_hash,
            user_id,
            limit,
        )
    else:
        rows = await _pool.fetch(
            """
            SELECT * FROM tasks
            WHERE owner_key_hash = $1
            ORDER BY created_at DESC
            LIMIT $2;
            """,
            owner_key_hash,
            limit,
        )
    tasks = [dict(row) for row in rows]
    for task in tasks:
        task["result"] = _coerce_json_value(task.get("result"))
        task["container_state"] = _coerce_json_value(task.get("container_state"))
    return tasks


async def get_task_status_metrics() -> Dict[str, Any]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")

    row = await _pool.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE status NOT IN ('completed', 'failed', 'error')) AS active_tasks,
            COUNT(*) FILTER (WHERE status = 'completed') AS completed,
            COUNT(*) FILTER (WHERE status IN ('failed', 'error')) AS failed,
            AVG(EXTRACT(EPOCH FROM (completed_at - created_at)))
                FILTER (WHERE completed_at IS NOT NULL) AS avg_duration_seconds
        FROM tasks;
        """
    )
    return _row_to_dict(row) or {}


async def list_task_states() -> List[Dict[str, Any]]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")

    rows = await _pool.fetch(
        """
        SELECT task_id, state_json, updated_at
        FROM task_state;
        """
    )
    states: List[Dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        data["state"] = _coerce_json_value(data.pop("state_json", None))
        states.append(data)
    return states


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _usage_key(key_hash: str, usage_date: date) -> Tuple[str, date]:
    return key_hash, usage_date


def _rate_limit_key(key_hash: str, scope: str, window_start: int) -> Tuple[str, str, int]:
    return key_hash, scope, window_start


async def reset_processing_tasks_to_queued() -> int:
    if _pool is None:
        return 0
    result = await _pool.execute(
        """
        UPDATE tasks
        SET status = 'queued', updated_at = NOW()
        WHERE status = 'processing';
        """
    )
    return int(result.split()[-1])


async def list_queued_tasks(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    if _pool is None:
        return []
    query = """
        SELECT id, description, user_id, created_at
        FROM tasks
        WHERE status = 'queued'
        ORDER BY created_at ASC
    """
    if limit is not None:
        query += " LIMIT $1"
        rows = await _pool.fetch(query, limit)
    else:
        rows = await _pool.fetch(query)
    return [dict(row) for row in rows]


def _window_start_ts(now: datetime, window_seconds: int) -> datetime:
    epoch = int(now.timestamp())
    window_start = epoch - (epoch % window_seconds)
    return datetime.fromtimestamp(window_start, tz=timezone.utc)


async def check_rate_limit(
    key_hash: str,
    scope: str,
    *,
    limit: int,
    window_seconds: int = 60,
) -> Tuple[bool, int]:
    if limit <= 0:
        return True, 0
    now = now_utc()
    window_start = _window_start_ts(now, window_seconds)
    retry_after = max(1, int((window_start + timedelta(seconds=window_seconds) - now).total_seconds()))
    if _pool is None:
        key = _rate_limit_key(key_hash, scope, int(window_start.timestamp()))
        entry = _rate_limits.get(key)
        if entry and entry["window_start"] == window_start:
            if entry["count"] >= limit:
                return False, retry_after
            entry["count"] += 1
        else:
            _rate_limits[key] = {
                "count": 1,
                "window_start": window_start,
                "updated_at": now,
            }
        return True, retry_after

    async with _pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT count
                FROM api_rate_limits
                WHERE key_hash = $1 AND scope = $2 AND window_start = $3
                FOR UPDATE;
                """,
                key_hash,
                scope,
                window_start,
            )
            if row and row["count"] >= limit:
                return False, retry_after
            if row:
                await conn.execute(
                    """
                    UPDATE api_rate_limits
                    SET count = count + 1, updated_at = NOW()
                    WHERE key_hash = $1 AND scope = $2 AND window_start = $3;
                    """,
                    key_hash,
                    scope,
                    window_start,
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO api_rate_limits (key_hash, scope, window_start, count)
                    VALUES ($1, $2, $3, 1);
                    """,
                    key_hash,
                    scope,
                    window_start,
                )
    return True, retry_after


async def record_usage(
    key_hash: str,
    *,
    tokens_in: int = 0,
    tokens_out: int = 0,
    command_runs: int = 0,
) -> None:
    usage_date = now_utc().date()
    if _pool is None:
        key = _usage_key(key_hash, usage_date)
        entry = _usage_daily.setdefault(
            key,
            {
                "tokens_in": 0,
                "tokens_out": 0,
                "command_runs": 0,
                "updated_at": now_utc(),
            },
        )
        entry["tokens_in"] += tokens_in
        entry["tokens_out"] += tokens_out
        entry["command_runs"] += command_runs
        entry["updated_at"] = now_utc()
        return

    await _pool.execute(
        """
        INSERT INTO api_usage_daily (key_hash, usage_date, tokens_in, tokens_out, command_runs)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (key_hash, usage_date)
        DO UPDATE SET
            tokens_in = api_usage_daily.tokens_in + EXCLUDED.tokens_in,
            tokens_out = api_usage_daily.tokens_out + EXCLUDED.tokens_out,
            command_runs = api_usage_daily.command_runs + EXCLUDED.command_runs,
            updated_at = NOW();
        """,
        key_hash,
        usage_date,
        tokens_in,
        tokens_out,
        command_runs,
    )


async def get_usage_for_key(key_hash: str) -> Dict[str, int]:
    usage_date = now_utc().date()
    if _pool is None:
        entry = _usage_daily.get(_usage_key(key_hash, usage_date))
        if not entry:
            return {"tokens_in": 0, "tokens_out": 0, "command_runs": 0}
        return {
            "tokens_in": entry.get("tokens_in", 0),
            "tokens_out": entry.get("tokens_out", 0),
            "command_runs": entry.get("command_runs", 0),
        }

    row = await _pool.fetchrow(
        """
        SELECT tokens_in, tokens_out, command_runs
        FROM api_usage_daily
        WHERE key_hash = $1 AND usage_date = $2;
        """,
        key_hash,
        usage_date,
    )
    if not row:
        return {"tokens_in": 0, "tokens_out": 0, "command_runs": 0}
    return {
        "tokens_in": int(row["tokens_in"]),
        "tokens_out": int(row["tokens_out"]),
        "command_runs": int(row["command_runs"]),
    }


async def get_usage_totals_since(since: datetime) -> Dict[str, int]:
    if _pool is None:
        totals = {"tokens_in": 0, "tokens_out": 0, "command_runs": 0}
        for entry in _usage_daily.values():
            updated_at = entry.get("updated_at")
            if isinstance(updated_at, datetime) and updated_at >= since:
                totals["tokens_in"] += entry.get("tokens_in", 0)
                totals["tokens_out"] += entry.get("tokens_out", 0)
                totals["command_runs"] += entry.get("command_runs", 0)
        return totals

    row = await _pool.fetchrow(
        """
        SELECT
            COALESCE(SUM(tokens_in), 0) AS tokens_in,
            COALESCE(SUM(tokens_out), 0) AS tokens_out,
            COALESCE(SUM(command_runs), 0) AS command_runs
        FROM api_usage_daily
        WHERE updated_at >= $1;
        """,
        since,
    )
    return {
        "tokens_in": int(row["tokens_in"]) if row else 0,
        "tokens_out": int(row["tokens_out"]) if row else 0,
        "command_runs": int(row["command_runs"]) if row else 0,
    }


async def get_top_usage_keys_since(
    since: datetime,
    *,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    if _pool is None:
        totals: Dict[str, Dict[str, Any]] = {}
        for (key_hash, _), entry in _usage_daily.items():
            updated_at = entry.get("updated_at")
            if isinstance(updated_at, datetime) and updated_at >= since:
                bucket = totals.setdefault(
                    key_hash,
                    {"tokens_in": 0, "tokens_out": 0, "command_runs": 0},
                )
                bucket["tokens_in"] += entry.get("tokens_in", 0)
                bucket["tokens_out"] += entry.get("tokens_out", 0)
                bucket["command_runs"] += entry.get("command_runs", 0)
        ranked = sorted(
            totals.items(),
            key=lambda item: item[1]["tokens_in"] + item[1]["tokens_out"],
            reverse=True,
        )
        return [
            {
                "key_hash": key_hash,
                "tokens_in": metrics["tokens_in"],
                "tokens_out": metrics["tokens_out"],
                "total_tokens": metrics["tokens_in"] + metrics["tokens_out"],
                "command_runs": metrics["command_runs"],
            }
            for key_hash, metrics in ranked[:limit]
        ]

    rows = await _pool.fetch(
        """
        SELECT
            key_hash,
            COALESCE(SUM(tokens_in), 0) AS tokens_in,
            COALESCE(SUM(tokens_out), 0) AS tokens_out,
            COALESCE(SUM(command_runs), 0) AS command_runs
        FROM api_usage_daily
        WHERE updated_at >= $1
        GROUP BY key_hash
        ORDER BY (COALESCE(SUM(tokens_in), 0) + COALESCE(SUM(tokens_out), 0)) DESC
        LIMIT $2;
        """,
        since,
        limit,
    )
    return [
        {
            "key_hash": row["key_hash"],
            "tokens_in": int(row["tokens_in"]),
            "tokens_out": int(row["tokens_out"]),
            "total_tokens": int(row["tokens_in"]) + int(row["tokens_out"]),
            "command_runs": int(row["command_runs"]),
        }
        for row in rows
    ]


async def get_failure_reason_counts(limit: int = 5) -> List[Dict[str, Any]]:
    if _pool is None:
        return []
    rows = await _pool.fetch(
        """
        SELECT COALESCE(failure_reason, error) AS reason, COUNT(*) AS count
        FROM tasks
        WHERE status IN ('failed', 'error')
          AND COALESCE(failure_reason, error) IS NOT NULL
        GROUP BY reason
        ORDER BY count DESC
        LIMIT $1;
        """,
        limit,
    )
    return [
        {"reason": row["reason"], "count": int(row["count"])}
        for row in rows
    ]


async def get_task_status_breakdown() -> Dict[str, int]:
    if _pool is None:
        return {}
    row = await _pool.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE status = 'queued') AS queued,
            COUNT(*) FILTER (WHERE status = 'processing') AS running,
            COUNT(*) FILTER (WHERE status = 'completed') AS completed,
            COUNT(*) FILTER (WHERE status IN ('failed', 'error')) AS failed
        FROM tasks;
        """
    )
    return {
        "queued": int(row["queued"] or 0),
        "running": int(row["running"] or 0),
        "completed": int(row["completed"] or 0),
        "failed": int(row["failed"] or 0),
    }


async def list_active_task_ids(limit: int = 5) -> List[str]:
    if _pool is None:
        return []
    rows = await _pool.fetch(
        """
        SELECT id
        FROM tasks
        WHERE status = 'processing'
        ORDER BY updated_at DESC
        LIMIT $1;
        """,
        limit,
    )
    return [str(row["id"]) for row in rows]


async def create_auth_user(*, email: str, password_hash: str) -> Dict[str, Any]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    try:
        row = await _pool.fetchrow(
            """
            INSERT INTO auth_users (id, email, password_hash)
            VALUES ($1, $2, $3)
            RETURNING id, email, password_hash, email_verified_at, created_at, updated_at;
            """,
            uuid.uuid4(),
            email,
            password_hash,
        )
    except Exception:
        _log_db_error("create_auth_user", {"email": email})
        raise
    return _row_to_dict(row) or {}


async def get_auth_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    row = await _pool.fetchrow(
        """
        SELECT id, email, password_hash, email_verified_at, created_at, updated_at
        FROM auth_users
        WHERE email = $1;
        """,
        email,
    )
    return _row_to_dict(row)


async def get_auth_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    row = await _pool.fetchrow(
        """
        SELECT id, email, password_hash, email_verified_at, created_at, updated_at
        FROM auth_users
        WHERE id = $1;
        """,
        _coerce_user_id(user_id),
    )
    return _row_to_dict(row)


async def mark_auth_user_email_verified(*, user_id: str) -> Optional[Dict[str, Any]]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    row = await _pool.fetchrow(
        """
        UPDATE auth_users
        SET email_verified_at = NOW(),
            updated_at = NOW()
        WHERE id = $1
        RETURNING id, email, password_hash, email_verified_at, created_at, updated_at;
        """,
        _coerce_user_id(user_id),
    )
    return _row_to_dict(row)


async def update_auth_user_password(*, user_id: str, password_hash: str) -> Optional[Dict[str, Any]]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    row = await _pool.fetchrow(
        """
        UPDATE auth_users
        SET password_hash = $2,
            updated_at = NOW()
        WHERE id = $1
        RETURNING id, email, password_hash, email_verified_at, created_at, updated_at;
        """,
        _coerce_user_id(user_id),
        password_hash,
    )
    return _row_to_dict(row)


async def get_oauth_account(
    *, provider: str, provider_account_id: str
) -> Optional[Dict[str, Any]]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    row = await _pool.fetchrow(
        """
        SELECT id, user_id, provider, provider_account_id, email, created_at, updated_at
        FROM auth_oauth_accounts
        WHERE provider = $1 AND provider_account_id = $2;
        """,
        provider,
        provider_account_id,
    )
    return _row_to_dict(row)


async def upsert_oauth_account(
    *,
    provider: str,
    provider_account_id: str,
    user_id: str,
    email: Optional[str],
) -> Dict[str, Any]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    row = await _pool.fetchrow(
        """
        INSERT INTO auth_oauth_accounts (
            id,
            user_id,
            provider,
            provider_account_id,
            email
        )
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (provider, provider_account_id)
        DO UPDATE SET
            user_id = EXCLUDED.user_id,
            email = EXCLUDED.email,
            updated_at = NOW()
        RETURNING id, user_id, provider, provider_account_id, email, created_at, updated_at;
        """,
        uuid.uuid4(),
        _coerce_user_id(user_id),
        provider,
        provider_account_id,
        email,
    )
    return _row_to_dict(row) or {}


async def create_refresh_session(
    *,
    user_id: str,
    token_hash: str,
    expires_at: datetime,
    user_agent: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> Dict[str, Any]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    try:
        row = await _pool.fetchrow(
            """
            INSERT INTO auth_refresh_sessions (
                id,
                user_id,
                token_hash,
                expires_at,
                last_used_at,
                user_agent,
                ip_address
            )
            VALUES ($1, $2, $3, $4, NOW(), $5, $6)
            RETURNING *;
            """,
            uuid.uuid4(),
            _coerce_user_id(user_id),
            token_hash,
            expires_at,
            user_agent,
            ip_address,
        )
    except Exception:
        _log_db_error(
            "create_refresh_session",
            {"user_id": user_id, "expires_at": expires_at},
        )
        raise
    return _row_to_dict(row) or {}


async def get_refresh_session_by_hash(token_hash: str) -> Optional[Dict[str, Any]]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    row = await _pool.fetchrow(
        """
        SELECT *
        FROM auth_refresh_sessions
        WHERE token_hash = $1;
        """,
        token_hash,
    )
    return _row_to_dict(row)


async def rotate_refresh_session(
    *,
    session_id: str,
    token_hash: str,
    expires_at: datetime,
) -> Optional[Dict[str, Any]]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    try:
        row = await _pool.fetchrow(
            """
            UPDATE auth_refresh_sessions
            SET token_hash = $2,
                expires_at = $3,
                rotated_at = NOW(),
                last_used_at = NOW(),
                updated_at = NOW()
            WHERE id = $1 AND revoked_at IS NULL
            RETURNING *;
            """,
            _coerce_user_id(session_id),
            token_hash,
            expires_at,
        )
    except Exception:
        _log_db_error("rotate_refresh_session", {"session_id": session_id})
        raise
    return _row_to_dict(row)


async def revoke_refresh_session(*, session_id: str) -> None:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    try:
        await _pool.execute(
            """
            UPDATE auth_refresh_sessions
            SET revoked_at = NOW(), updated_at = NOW()
            WHERE id = $1;
            """,
            _coerce_user_id(session_id),
        )
    except Exception:
        _log_db_error("revoke_refresh_session", {"session_id": session_id})
        raise


async def create_email_verify_token(
    *,
    user_id: str,
    token_hash: str,
    expires_at: datetime,
) -> Dict[str, Any]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    try:
        row = await _pool.fetchrow(
            """
            INSERT INTO email_verify_tokens (id, user_id, token_hash, expires_at)
            VALUES ($1, $2, $3, $4)
            RETURNING *;
            """,
            uuid.uuid4(),
            _coerce_user_id(user_id),
            token_hash,
            expires_at,
        )
    except Exception:
        _log_db_error("create_email_verify_token", {"user_id": user_id})
        raise
    return _row_to_dict(row) or {}


async def consume_email_verify_token(token_hash: str) -> Optional[Dict[str, Any]]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    async with _pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT *
                FROM email_verify_tokens
                WHERE token_hash = $1;
                """,
                token_hash,
            )
            if not row:
                return None
            await conn.execute(
                "DELETE FROM email_verify_tokens WHERE id = $1;",
                row["id"],
            )
    return _row_to_dict(row)


async def create_password_reset_token(
    *,
    user_id: str,
    token_hash: str,
    expires_at: datetime,
) -> Dict[str, Any]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    try:
        row = await _pool.fetchrow(
            """
            INSERT INTO password_reset_tokens (id, user_id, token_hash, expires_at)
            VALUES ($1, $2, $3, $4)
            RETURNING *;
            """,
            uuid.uuid4(),
            _coerce_user_id(user_id),
            token_hash,
            expires_at,
        )
    except Exception:
        _log_db_error("create_password_reset_token", {"user_id": user_id})
        raise
    return _row_to_dict(row) or {}


async def consume_password_reset_token(token_hash: str) -> Optional[Dict[str, Any]]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    async with _pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT *
                FROM password_reset_tokens
                WHERE token_hash = $1;
                """,
                token_hash,
            )
            if not row:
                return None
            await conn.execute(
                "DELETE FROM password_reset_tokens WHERE id = $1;",
                row["id"],
            )
    return _row_to_dict(row)


async def cleanup_expired_data(ttl_days: int) -> Dict[str, int]:
    if _pool is None or ttl_days <= 0:
        return {}
    cutoff = now_utc() - timedelta(days=ttl_days)
    counts: Dict[str, int] = {}
    async with _pool.acquire() as conn:
        task_rows = await conn.fetch(
            "SELECT id FROM tasks WHERE created_at < $1;",
            cutoff,
        )
        task_ids = [row["id"] for row in task_rows]

        if task_ids:
            counts["task_events"] = await conn.fetchval(
                "SELECT COUNT(*) FROM task_events WHERE task_id = ANY($1::uuid[]);",
                task_ids,
            )
            await conn.execute(
                "DELETE FROM task_events WHERE task_id = ANY($1::uuid[]);",
                task_ids,
            )
            counts["task_artifacts"] = await conn.fetchval(
                "SELECT COUNT(*) FROM task_artifacts WHERE task_id = ANY($1::uuid[]);",
                task_ids,
            )
            await conn.execute(
                "DELETE FROM task_artifacts WHERE task_id = ANY($1::uuid[]);",
                task_ids,
            )
            counts["task_files"] = await conn.fetchval(
                "SELECT COUNT(*) FROM task_files WHERE task_id = ANY($1::uuid[]);",
                task_ids,
            )
            await conn.execute(
                "DELETE FROM task_files WHERE task_id = ANY($1::uuid[]);",
                task_ids,
            )
            counts["task_state"] = await conn.fetchval(
                "SELECT COUNT(*) FROM task_state WHERE task_id = ANY($1::uuid[]);",
                task_ids,
            )
            await conn.execute(
                "DELETE FROM task_state WHERE task_id = ANY($1::uuid[]);",
                task_ids,
            )
            counts["task_snapshots"] = await conn.fetchval(
                "SELECT COUNT(*) FROM task_container_snapshots WHERE task_id = ANY($1::uuid[]);",
                task_ids,
            )
            await conn.execute(
                "DELETE FROM task_container_snapshots WHERE task_id = ANY($1::uuid[]);",
                task_ids,
            )

        counts["old_events"] = await conn.fetchval(
            "SELECT COUNT(*) FROM task_events WHERE created_at < $1;",
            cutoff,
        )
        await conn.execute(
            "DELETE FROM task_events WHERE created_at < $1;",
            cutoff,
        )
        counts["old_artifacts"] = await conn.fetchval(
            "SELECT COUNT(*) FROM task_artifacts WHERE created_at < $1;",
            cutoff,
        )
        await conn.execute(
            "DELETE FROM task_artifacts WHERE created_at < $1;",
            cutoff,
        )
        counts["old_files"] = await conn.fetchval(
            "SELECT COUNT(*) FROM task_files WHERE updated_at < $1;",
            cutoff,
        )
        await conn.execute(
            "DELETE FROM task_files WHERE updated_at < $1;",
            cutoff,
        )
        counts["old_state"] = await conn.fetchval(
            "SELECT COUNT(*) FROM task_state WHERE updated_at < $1;",
            cutoff,
        )
        await conn.execute(
            "DELETE FROM task_state WHERE updated_at < $1;",
            cutoff,
        )
        counts["old_snapshots"] = await conn.fetchval(
            "SELECT COUNT(*) FROM task_container_snapshots WHERE updated_at < $1;",
            cutoff,
        )
        await conn.execute(
            "DELETE FROM task_container_snapshots WHERE updated_at < $1;",
            cutoff,
        )
        counts["tasks"] = await conn.fetchval(
            "SELECT COUNT(*) FROM tasks WHERE created_at < $1;",
            cutoff,
        )
        await conn.execute(
            "DELETE FROM tasks WHERE created_at < $1;",
            cutoff,
        )
    return {key: int(value or 0) for key, value in counts.items()}
