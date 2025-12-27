"""
Основной FastAPI сервер для Telegram Mini App
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager
import uuid
import json
import asyncio
import io
import zipfile
from typing import Dict, Optional, List, Any
import logging
import os
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
import hashlib
import mimetypes
import difflib
import platform
import shutil
import subprocess
import sys
import time

from .models import Container, ProjectState
from .orchestrator import AIOrchestrator
from .agents import AIReviewer, SafeCommandRunner
from .schemas import (
    ArtifactsResponse,
    ArtifactItem,
    ContainerStateResponse,
    ContainerStateSnapshot,
    EventsResponse,
    EventItem,
)
from . import db
from .logging_utils import (
    configure_logging,
    get_request_id,
    reset_request_id,
    reset_task_id,
    set_request_id,
    set_task_id,
)

configure_logging()
logger = logging.getLogger(__name__)

# Модели запросов/ответов
class TaskRequest(BaseModel):
    description: str
    user_id: Optional[str] = None
    codex_version: Optional[str] = "1.0.0-mvp"

class TaskResponse(BaseModel):
    task_id: str
    status: str
    message: str
    progress: float = 0.0
    estimated_time: Optional[int] = None

class FileContentRequest(BaseModel):
    filepath: str

# Глобальное хранилище (в продакшене заменить на Redis/БД)
class Storage:
    def __init__(self):
        self.active_tasks: Dict[str, Dict] = {}
        self.containers: Dict[str, Container] = {}
        self.user_sessions: Dict[str, List[str]] = {}  # user_id -> [task_ids]
        self.events: Dict[str, List[Dict[str, Any]]] = {}
        self.artifacts: Dict[str, List[Dict[str, Any]]] = {}
        self.state: Dict[str, Dict[str, Any]] = {}

storage = Storage()
database_url = os.getenv("DATABASE_URL")
TASK_TTL_DAYS = os.getenv("TASK_TTL_DAYS")
APP_API_KEY = os.getenv("APP_API_KEY")
WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "data/workspaces"))
WORKSPACE_TTL_DAYS = os.getenv("WORKSPACE_TTL_DAYS")
COMMAND_TIMEOUT_SECONDS = os.getenv("COMMAND_TIMEOUT_SECONDS")
COMMAND_MAX_OUTPUT_BYTES = os.getenv("COMMAND_MAX_OUTPUT_BYTES")
ALLOWED_COMMANDS = os.getenv("ALLOWED_COMMANDS")

# WebSocket менеджер
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, task_id: str):
        await websocket.accept()
        self.active_connections[task_id] = websocket
        logger.info("WebSocket connected for task_id=%s", task_id)
    
    def disconnect(self, task_id: str):
        if task_id in self.active_connections:
            del self.active_connections[task_id]
            logger.info("WebSocket disconnected for task_id=%s", task_id)
    
    async def send_progress(self, task_id: str, data: dict):
        await record_event(task_id, "ProgressUpdate", normalize_payload(data))
        if task_id in self.active_connections:
            try:
                await self.active_connections[task_id].send_json(jsonable_encoder(data))
                return True
            except Exception as e:
                logger.error("Error sending WebSocket message for task_id=%s: %s", task_id, e)
                self.disconnect(task_id)
        return False

manager = ConnectionManager()
FILE_PERSISTENCE_ENABLED: Optional[bool] = None
FILE_PERSISTENCE_REASON = ""


def enrich_task_data(task_id: str, task_data: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(task_data.get("id"), uuid.UUID):
        task_data["id"] = str(task_data["id"])
    container = resolve_container(task_id)
    if container:
        task_data["files_count"] = len(container.files)
        task_data["artifacts_count"] = sum(len(a) for a in container.artifacts.values())
        task_data["iterations"] = container.metadata.get("iterations")
        task_data["max_iterations"] = container.metadata.get("max_iterations")
        result = task_data.get("result")
        if isinstance(result, dict):
            result["files_count"] = task_data["files_count"]
            result["artifacts_count"] = task_data["artifacts_count"]
            result["iterations"] = task_data.get("iterations", result.get("iterations"))
            result["max_iterations"] = task_data.get("max_iterations", result.get("max_iterations"))
    time_taken_seconds = compute_time_taken_seconds(task_data)
    if time_taken_seconds is not None:
        task_data["time_taken_seconds"] = time_taken_seconds
    if task_data.get("failure_reason") is None and task_data.get("error"):
        task_data["failure_reason"] = task_data.get("error")
    return task_data


def normalize_payload(payload: Any) -> Any:
    return jsonable_encoder(payload)


def build_event_payload(task_id: str, payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    data = normalize_payload(payload or {})
    if isinstance(data, dict):
        data.setdefault("task_id", task_id)
        request_id = get_request_id()
        if request_id:
            data.setdefault("request_id", request_id)
    return data


def get_request_api_key(request: Request) -> Optional[str]:
    key = request.headers.get("X-API-Key")
    if not key:
        return None
    key = key.strip()
    return key or None


def require_api_key(request: Request) -> str:
    key = get_request_api_key(request)
    if not key:
        raise HTTPException(status_code=401, detail="API key required")
    if APP_API_KEY and key != APP_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return key


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


async def ensure_task_owner(task_id: str, request: Request) -> Dict[str, Any]:
    api_key = require_api_key(request)
    api_key_hash = hash_api_key(api_key)
    if db.is_enabled():
        task_data = await db.get_task_row(task_id)
        if task_data is None:
            raise HTTPException(status_code=404, detail="Task not found")
    else:
        task_data = storage.active_tasks.get(task_id)
        if task_data is None:
            raise HTTPException(status_code=404, detail="Task not found")
    owner_hash = task_data.get("owner_key_hash")
    if not owner_hash or owner_hash != api_key_hash:
        raise HTTPException(status_code=403, detail="Invalid API Key or no access to this task.")
    return task_data


def get_websocket_api_key(websocket: WebSocket) -> Optional[str]:
    key = websocket.query_params.get("api_key") or websocket.headers.get("X-API-Key")
    if not key:
        return None
    key = key.strip()
    return key or None


async def ensure_websocket_owner(websocket: WebSocket, task_id: str) -> Optional[str]:
    api_key = get_websocket_api_key(websocket)
    if not api_key:
        await websocket.accept()
        await websocket.close(code=4401, reason="API key required")
        return None
    if APP_API_KEY and api_key != APP_API_KEY:
        await websocket.accept()
        await websocket.close(code=4401, reason="Invalid API key")
        return None
    api_key_hash = hash_api_key(api_key)
    if db.is_enabled():
        task_data = await db.get_task_row(task_id)
        if task_data is None:
            await websocket.accept()
            await websocket.close(code=4404, reason="Task not found")
            return None
    else:
        task_data = storage.active_tasks.get(task_id)
        if task_data is None:
            await websocket.accept()
            await websocket.close(code=4404, reason="Task not found")
            return None
    owner_hash = task_data.get("owner_key_hash")
    if not owner_hash or owner_hash != api_key_hash:
        await websocket.accept()
        await websocket.close(code=4403, reason="Forbidden")
        return None
    return api_key

def to_json_compatible(value: Any) -> Any:
    try:
        return jsonable_encoder(value, custom_encoder={uuid.UUID: str})
    except (TypeError, ValueError):
        return json.loads(json.dumps(value, default=str))


def to_iso_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def normalize_event_item(event: Dict[str, Any]) -> EventItem:
    return EventItem(
        id=str(event.get("id")),
        type=str(event.get("type")),
        payload=to_json_compatible(event.get("payload", {})) or {},
        created_at=to_iso_string(event.get("created_at")) or "",
    )


def normalize_artifact_item(artifact: Dict[str, Any]) -> ArtifactItem:
    return ArtifactItem(
        id=str(artifact.get("id")),
        type=str(artifact.get("type")),
        produced_by=artifact.get("produced_by"),
        payload=to_json_compatible(artifact.get("payload", {})) or {},
        created_at=to_iso_string(artifact.get("created_at")) or "",
    )


def artifact_dedupe_key(artifact: Dict[str, Any]) -> str:
    artifact_id = artifact.get("id") or artifact.get("_id") or artifact.get("artifact_id")
    if artifact_id:
        return f"id:{artifact_id}"
    return "meta:{type}:{produced_by}:{created_at}".format(
        type=artifact.get("type"),
        produced_by=artifact.get("produced_by"),
        created_at=artifact.get("created_at"),
    )


def dedupe_artifacts(artifacts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique: List[Dict[str, Any]] = []
    for artifact in artifacts:
        key = artifact_dedupe_key(artifact)
        if key in seen:
            continue
        seen.add(key)
        unique.append(artifact)
    return unique


def normalize_container_state(raw_state: Any) -> ContainerStateSnapshot:
    state: Dict[str, Any] = raw_state or {}
    if isinstance(state, dict) and isinstance(state.get("state"), dict):
        state = state["state"]

    key_map = {
        "currentStage": "current_stage",
        "activeRole": "active_role",
        "currentTask": "current_task",
        "codexVersion": "codex_version",
        "containerState": "container_state",
        "containerProgress": "container_progress",
    }
    normalized: Dict[str, Any] = {}
    for key, value in state.items():
        normalized[key_map.get(key, key)] = value

    timestamps = normalized.get("timestamps")
    if timestamps is not None:
        normalized["timestamps"] = to_json_compatible(timestamps)

    extras = {
        key: value
        for key, value in normalized.items()
        if key
        not in {
            "status",
            "progress",
            "current_stage",
            "active_role",
            "current_task",
            "codex_version",
            "timestamps",
            "container_state",
            "container_progress",
        }
    }
    if extras:
        normalized.setdefault("timestamps", {})
        normalized["timestamps"]["meta"] = to_json_compatible(extras)

    return ContainerStateSnapshot(
        status=normalized.get("status"),
        progress=normalized.get("progress"),
        current_stage=normalized.get("current_stage"),
        active_role=normalized.get("active_role"),
        current_task=normalized.get("current_task"),
        codex_version=normalized.get("codex_version"),
        timestamps=normalized.get("timestamps"),
        container_state=normalized.get("container_state"),
        container_progress=normalized.get("container_progress"),
    )


def validate_order(order: str) -> str:
    normalized = order.lower()
    if normalized not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="order must be 'asc' or 'desc'")
    return normalized


async def ensure_task_exists(task_id: str) -> Dict[str, Any]:
    task_data = await db.get_task_row(task_id)
    if task_data is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task_data


def ensure_task_exists_in_memory(task_id: str) -> None:
    if task_id not in storage.active_tasks:
        raise HTTPException(status_code=404, detail="Task not found")


def store_in_memory_event(task_id: str, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    events = storage.events.setdefault(task_id, [])
    events.append(
        {
            "id": str(uuid.uuid4()),
            "type": event_type,
            "payload": normalize_payload(payload or {}),
            "created_at": db.now_utc(),
        }
    )


def store_in_memory_artifact(
    task_id: str,
    artifact_type: str,
    payload: Optional[Dict[str, Any]] = None,
    produced_by: Optional[str] = None,
) -> None:
    artifacts = storage.artifacts.setdefault(task_id, [])
    artifacts.append(
        {
            "id": str(uuid.uuid4()),
            "type": artifact_type,
            "produced_by": produced_by,
            "payload": normalize_payload(payload or {}),
            "created_at": db.now_utc(),
        }
    )


def store_in_memory_state(task_id: str, state: Dict[str, Any]) -> None:
    storage.state[task_id] = {
        "task_id": task_id,
        "state": normalize_payload(state),
        "updated_at": db.now_utc(),
    }


async def record_event(task_id: str, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    payload = build_event_payload(task_id, payload)
    if db.is_enabled():
        await db.append_event(task_id, event_type, payload)
    else:
        store_in_memory_event(task_id, event_type, payload)


async def record_artifact(
    task_id: str,
    artifact_type: str,
    payload: Optional[Dict[str, Any]] = None,
    produced_by: Optional[str] = None,
) -> None:
    if db.is_enabled():
        await db.add_artifact(
            task_id,
            artifact_type,
            normalize_payload(payload or {}),
            produced_by=produced_by,
        )
    else:
        store_in_memory_artifact(task_id, artifact_type, payload, produced_by=produced_by)


async def record_state(task_id: str, state: Dict[str, Any]) -> None:
    if db.is_enabled():
        await db.set_container_state(task_id, normalize_payload(state))
    else:
        store_in_memory_state(task_id, state)


def parse_allowed_commands(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    commands = [item.strip() for item in value.split(",") if item.strip()]
    return commands or None


def build_command_runner(task_id: str, workspace_path: Path) -> SafeCommandRunner:
    timeout_seconds = parse_int_env(COMMAND_TIMEOUT_SECONDS, 60)
    max_output_bytes = parse_int_env(COMMAND_MAX_OUTPUT_BYTES, 20000)
    allowed_commands = parse_allowed_commands(ALLOWED_COMMANDS)

    async def handle_event(event_type: str, payload: Dict[str, Any]) -> None:
        await record_event(task_id, event_type, normalize_payload(payload))

    async def handle_artifact(
        artifact_type: str,
        payload: Dict[str, Any],
        produced_by: Optional[str],
    ) -> None:
        await record_artifact(
            task_id,
            artifact_type,
            normalize_payload(payload),
            produced_by=produced_by,
        )

    return SafeCommandRunner(
        workspace_path,
        allowed_commands=allowed_commands,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        event_handler=handle_event,
        artifact_handler=handle_artifact,
    )


async def run_review_for_task(task_id: str, container: Container) -> Dict[str, Any]:
    run_id = str(uuid.uuid4())
    started_at = db.now_utc().isoformat()
    await record_event(
        task_id,
        "review_started",
        normalize_payload({"run_id": run_id, "started_at": started_at}),
    )
    reviewer = AIReviewer(AIOrchestrator().codex)
    workspace = TaskWorkspace(task_id, WORKSPACE_ROOT)
    workspace.materialize(container)
    runner = build_command_runner(task_id, workspace.path)
    review_result = await reviewer.execute(
        container,
        workspace_path=workspace.path,
        command_runner=runner,
    )
    finished_at = db.now_utc().isoformat()
    review_result["run_id"] = run_id
    review_result["started_at"] = started_at
    review_result["finished_at"] = finished_at
    await record_artifact(
        task_id,
        "review_report",
        normalize_payload(review_result),
        produced_by="reviewer",
    )
    await record_event(
        task_id,
        "review_finished",
        normalize_payload(
            {
                "run_id": run_id,
                "started_at": started_at,
                "finished_at": finished_at,
                "passed": review_result.get("passed"),
                "status": review_result.get("status"),
            }
        ),
    )
    await persist_container_snapshot(task_id, container)
    return review_result


def get_in_memory_events(task_id: str, limit: int, order: str) -> List[Dict[str, Any]]:
    events = storage.events.get(task_id, [])
    ordered = sorted(events, key=lambda item: item.get("created_at"), reverse=order == "desc")
    return ordered[:limit]


def get_in_memory_artifacts(
    task_id: str,
    artifact_type: Optional[str],
    limit: int,
    order: str,
) -> List[Dict[str, Any]]:
    artifacts = storage.artifacts.get(task_id, [])
    if artifact_type:
        artifacts = [artifact for artifact in artifacts if artifact.get("type") == artifact_type]
    ordered = sorted(
        artifacts,
        key=lambda item: item.get("created_at"),
        reverse=order == "desc",
    )
    return ordered[:limit]


def get_in_memory_state(task_id: str) -> Optional[Dict[str, Any]]:
    return storage.state.get(task_id)


def build_container_state(
    *,
    status: str,
    progress: float,
    current_stage: Optional[str],
    container: Optional[Container] = None,
    active_role: Optional[str] = None,
    current_task: Optional[str] = None,
    include_created_at: bool = False,
) -> Dict[str, Any]:
    now_iso = db.now_utc().isoformat()
    state = {
        "status": status,
        "progress": progress,
        "current_stage": current_stage,
        "active_role": active_role or (container.metadata.get("active_role") if container else None),
        "current_task": current_task or (container.current_task if container else None),
        "container_state": container.state.value if container else None,
        "container_progress": container.progress if container else None,
        "llm_usage_summary": container.metadata.get("llm_usage_summary") if container else None,
        "timestamps": {
            "updated_at": now_iso,
        },
    }
    if include_created_at:
        state["timestamps"]["created_at"] = now_iso
    return normalize_payload(state)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    logger.info("Starting AI Platform Backend...")
    logger.info(
        "CORS allowlist source=%s; allowed origins=%d",
        cors_source,
        len(allowed_origins),
    )
    
    # Создаем директории если их нет
    os.makedirs("data/tasks", exist_ok=True)
    os.makedirs("data/logs", exist_ok=True)
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    cleanup_workspaces(WORKSPACE_ROOT, WORKSPACE_TTL_DAYS)

    global FILE_PERSISTENCE_ENABLED, FILE_PERSISTENCE_REASON
    FILE_PERSISTENCE_ENABLED, FILE_PERSISTENCE_REASON = resolve_file_persistence_setting()
    logger.info(
        "File persistence %s (%s)",
        "enabled" if FILE_PERSISTENCE_ENABLED else "disabled",
        FILE_PERSISTENCE_REASON,
    )

    if database_url:
        logger.info("DATABASE_URL detected, enabling Postgres persistence")
        try:
            await db.init_db(database_url)
            await db.init_container_tables()
            logger.info("Container persistence enabled")
        except Exception:
            logger.exception("Failed to initialize database connection")
            raise
    else:
        logger.info("DATABASE_URL not set, using in-memory task storage")
    
    yield
    
    logger.info("Shutting down AI Platform Backend...")
    # Очистка ресурсов
    await db.close_db()

app = FastAPI(
    title="AI Collaboration Platform API",
    description="Backend для платформы коллаборации ИИ с Telegram Mini App",
    version="1.0.0-mvp",
    lifespan=lifespan
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request_token = set_request_id(request_id)
    try:
        response = await call_next(request)
    finally:
        reset_request_id(request_token)
    response.headers["X-Request-ID"] = request_id
    return response

def parse_allowed_origins() -> tuple[list[str], str]:
    raw_origins = os.getenv("ALLOWED_ORIGINS")
    raw_value = raw_origins or ""
    parsed_origins = [origin.strip() for origin in raw_value.split(",") if origin.strip()]
    origins = [origin for origin in parsed_origins if origin != "*"]
    if len(origins) != len(parsed_origins):
        logger.warning("Ignoring wildcard '*' entry in ALLOWED_ORIGINS.")
    environment = os.getenv("ENVIRONMENT", "").lower()
    is_production = environment == "production"
    source = "env" if raw_origins is not None else "unset"

    if is_production:
        if not origins:
            source = "empty"
            logger.warning(
                "ALLOWED_ORIGINS is empty in production; CORS will block all cross-origin requests."
            )
    else:
        if not origins:
            origins = [
                "http://localhost",
                "http://127.0.0.1",
                "http://localhost:3000",
                "http://localhost:8000",
            ]
            source = "dev-defaults"

    return origins, source


allowed_origins, cors_source = parse_allowed_origins()

def parse_bool_env(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    return None


def parse_int_env(value: Optional[str], default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid integer env value '%s', using default=%s", value, default)
        return default


def cleanup_workspaces(root: Path, ttl_days: Optional[str]) -> None:
    ttl_value = parse_int_env(ttl_days, 0) if ttl_days else 0
    if ttl_value <= 0:
        return
    cutoff = time.time() - ttl_value * 86400
    if not root.exists():
        return
    for path in root.iterdir():
        if not path.is_dir():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            logger.warning("Failed to inspect workspace path: %s", path)

def resolve_file_persistence_setting() -> tuple[bool, str]:
    env_value = os.getenv("ENABLE_FILE_PERSISTENCE")
    parsed = parse_bool_env(env_value)
    if parsed is not None:
        return parsed, f"ENABLE_FILE_PERSISTENCE set to '{env_value}'"

    environment = os.getenv("ENVIRONMENT", "").lower()
    if environment == "production":
        if env_value is None:
            return False, "ENVIRONMENT=production default disabled"
        return False, f"ENABLE_FILE_PERSISTENCE set to unrecognized value '{env_value}'; default disabled for production"

    if env_value is None:
        return True, f"ENVIRONMENT={environment or 'unset'} default enabled"
    return True, f"ENABLE_FILE_PERSISTENCE set to unrecognized value '{env_value}'; default enabled for non-production"


MAX_TASK_BYTES = parse_int_env(os.getenv("MAX_TASK_BYTES"), 50 * 1024 * 1024)
MAX_TASK_FILES = parse_int_env(os.getenv("MAX_TASK_FILES"), 2000)

def get_file_persistence_setting() -> bool:
    global FILE_PERSISTENCE_ENABLED, FILE_PERSISTENCE_REASON
    if FILE_PERSISTENCE_ENABLED is None:
        FILE_PERSISTENCE_ENABLED, FILE_PERSISTENCE_REASON = resolve_file_persistence_setting()
    return FILE_PERSISTENCE_ENABLED


def parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def compute_time_taken_seconds(task_data: Dict[str, Any]) -> Optional[float]:
    start = parse_datetime(task_data.get("created_at"))
    end = parse_datetime(task_data.get("completed_at")) or parse_datetime(task_data.get("updated_at"))
    if not start or not end:
        return None
    delta = (end - start).total_seconds()
    return max(0.0, delta)


def aggregate_llm_usage(summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
    totals = {
        "total_tokens_in": 0,
        "total_tokens_out": 0,
        "total_tokens": 0,
        "by_stage": {},
        "models": {},
    }
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        totals["total_tokens_in"] += summary.get("total_tokens_in", 0) or 0
        totals["total_tokens_out"] += summary.get("total_tokens_out", 0) or 0
        for stage, values in (summary.get("by_stage") or {}).items():
            stage_bucket = totals["by_stage"].setdefault(
                stage,
                {"tokens_in": 0, "tokens_out": 0, "total_tokens": 0, "models": {}},
            )
            stage_bucket["tokens_in"] += values.get("tokens_in", 0) or 0
            stage_bucket["tokens_out"] += values.get("tokens_out", 0) or 0
            stage_bucket["total_tokens"] += values.get("total_tokens", 0) or 0
            for model, count in (values.get("models") or {}).items():
                stage_bucket["models"][model] = stage_bucket["models"].get(model, 0) + count
        for model, count in (summary.get("models") or {}).items():
            totals["models"][model] = totals["models"].get(model, 0) + count

    totals["total_tokens"] = totals["total_tokens_in"] + totals["total_tokens_out"]
    return totals


def sanitize_zip_path(path: str) -> str:
    normalized = path.replace("\\", "/").lstrip("/")
    posix_path = PurePosixPath(normalized)
    if posix_path.is_absolute() or ".." in posix_path.parts or not posix_path.parts:
        raise HTTPException(status_code=400, detail=f"Invalid file path: {path}")
    return posix_path.as_posix()


def load_container_from_file(task_id: str) -> Optional[Container]:
    if not get_file_persistence_setting():
        return None
    filepath = Path("data/tasks") / f"{task_id}.json"
    if not filepath.exists():
        return None
    try:
        with filepath.open("r", encoding="utf-8") as file:
            data = json.load(file)
        container = Container.from_dict(data)
        storage.containers[task_id] = container
        return container
    except Exception:
        logger.exception("Failed to load container from %s", filepath)
        return None


def resolve_container(task_id: str) -> Optional[Container]:
    container = storage.containers.get(task_id)
    if container:
        return container
    container = load_container_from_file(task_id)
    if container:
        return container
    return None


async def resolve_container_with_db(task_id: str) -> Optional[Container]:
    container = resolve_container(task_id)
    if container:
        return container
    if db.is_enabled():
        return await load_container_from_db(task_id)
    return None


async def load_container_from_db(task_id: str) -> Optional[Container]:
    if not db.is_enabled():
        return None
    snapshot_row = await db.get_container_snapshot(task_id)
    files = await db.list_task_files_with_payload(task_id)
    if not snapshot_row and not files:
        return None

    snapshot = snapshot_row.get("snapshot") if snapshot_row else {}
    container_id = snapshot.get("project_id") if isinstance(snapshot, dict) else None
    container = Container(container_id or task_id)

    if isinstance(snapshot, dict):
        state_value = snapshot.get("state")
        if state_value:
            try:
                container.state = ProjectState(state_value)
            except ValueError:
                logger.warning("Unknown container state '%s' for task %s", state_value, task_id)
        container.progress = snapshot.get("progress", container.progress)
        container.metadata.update(snapshot.get("metadata", {}))
        container.target_architecture = snapshot.get("target_architecture")
        container.history = snapshot.get("history", [])
        created_at = parse_datetime(snapshot.get("created_at"))
        updated_at = parse_datetime(snapshot.get("updated_at"))
        if created_at:
            container.created_at = created_at
        if updated_at:
            container.updated_at = updated_at

    for file_row in files:
        content = file_row.get("content")
        content_bytes = file_row.get("content_bytes")
        if content is None and content_bytes is not None:
            try:
                content = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                content = content_bytes.decode("utf-8", errors="replace")
        if content is not None:
            container.files[file_row["path"]] = content

    storage.containers[task_id] = container
    return container


def build_container_snapshot(container: Container) -> Dict[str, Any]:
    file_entries = []
    for filepath, content in container.files.items():
        payload = content.encode("utf-8") if isinstance(content, str) else content
        file_entries.append(
            {
                "path": filepath,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
                "mime_type": mimetypes.guess_type(filepath)[0],
            }
        )
    return {
        "project_id": container.project_id,
        "state": container.state.value,
        "progress": container.progress,
        "metadata": container.metadata,
        "target_architecture": container.target_architecture,
        "history": container.history,
        "created_at": container.created_at.isoformat(),
        "updated_at": container.updated_at.isoformat(),
        "files": file_entries,
        "codex_hash": container.metadata.get("codex_hash"),
        "iterations": container.metadata.get("iterations"),
    }


def build_file_record(content: Any) -> Dict[str, Any]:
    if isinstance(content, (bytes, bytearray)):
        payload = bytes(content)
        text_content = None
        is_binary = True
    else:
        text_content = str(content)
        payload = text_content.encode("utf-8")
        is_binary = False
    return {
        "content": text_content,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
        "is_binary": is_binary,
    }


def capture_baseline_files(container: Container) -> Dict[str, Dict[str, Any]]:
    return {path: build_file_record(content) for path, content in container.files.items()}


class TaskWorkspace:
    """Workspace for materializing and syncing task files."""

    ignored_dirs = {
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".venv",
    }

    ignored_suffixes = {".pyc"}

    def __init__(self, task_id: str, root: Path):
        self.task_id = task_id
        self.root = root
        self.path = (root / task_id).resolve()

    def ensure(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)

    def _safe_relative_path(self, relative_path: str) -> PurePosixPath:
        pure_path = PurePosixPath(relative_path)
        if pure_path.is_absolute() or ".." in pure_path.parts:
            raise ValueError(f"Unsafe path rejected: {relative_path}")
        return pure_path

    def _resolve_target_path(self, relative_path: str) -> Path:
        pure_path = self._safe_relative_path(relative_path)
        target_path = (self.path / pure_path).resolve()
        if target_path == self.path:
            return target_path
        if not target_path.is_relative_to(self.path):
            raise ValueError(f"Path traversal rejected: {relative_path}")
        return target_path

    def _should_ignore(self, relative_path: Path) -> bool:
        if any(part in self.ignored_dirs for part in relative_path.parts):
            return True
        if relative_path.suffix in self.ignored_suffixes:
            return True
        return False

    def write_file(self, relative_path: str, content: Optional[Any]) -> None:
        target_path = self._resolve_target_path(relative_path)
        if content is None:
            if target_path.exists():
                target_path.unlink()
            return
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, (bytes, bytearray)):
            target_path.write_bytes(bytes(content))
        else:
            target_path.write_text(str(content), encoding="utf-8")

    def materialize(self, container: Container) -> None:
        self.ensure()
        for filepath, content in container.files.items():
            self.write_file(filepath, content)

    def collect_files(self) -> Dict[str, Any]:
        files: Dict[str, Any] = {}
        if not self.path.exists():
            return files
        for path in self.path.rglob("*"):
            if not path.is_file():
                continue
            relative_path = path.relative_to(self.path)
            if self._should_ignore(relative_path):
                continue
            data = path.read_bytes()
            try:
                content: Any = data.decode("utf-8")
            except UnicodeDecodeError:
                content = data
            files[str(relative_path.as_posix())] = content
        return files

    def sync_to_container(self, container: Container) -> Dict[str, List[str]]:
        workspace_files = self.collect_files()
        existing_records = capture_baseline_files(container)
        changed: List[str] = []
        removed: List[str] = []

        hook = container.file_update_hook
        container.file_update_hook = None
        try:
            for path, content in workspace_files.items():
                current_record = existing_records.get(path)
                next_record = build_file_record(content)
                if current_record and current_record["sha256"] == next_record["sha256"]:
                    continue
                container.add_file(path, content)
                changed.append(path)

            for path in list(container.files.keys()):
                if path not in workspace_files:
                    container.remove_file(path)
                    removed.append(path)
        finally:
            container.file_update_hook = hook

        return {"changed": changed, "removed": removed}


def build_patch_diff_payload(
    baseline_files: Dict[str, Dict[str, Any]],
    final_files: Dict[str, Any],
) -> Dict[str, Any]:
    changed_files: List[Dict[str, Any]] = []
    diff_lines: List[str] = []
    stats = {
        "changed_total": 0,
        "added": 0,
        "removed": 0,
        "modified": 0,
        "text_files": 0,
        "binary_files": 0,
        "diff_lines": 0,
    }

    final_records = {path: build_file_record(content) for path, content in final_files.items()}
    all_paths = sorted(set(baseline_files.keys()) | set(final_records.keys()))

    for path in all_paths:
        baseline_record = baseline_files.get(path)
        final_record = final_records.get(path)
        if baseline_record is None:
            change_type = "added"
        elif final_record is None:
            change_type = "removed"
        elif baseline_record["sha256"] != final_record["sha256"]:
            change_type = "modified"
        else:
            continue

        is_binary = bool(
            (baseline_record and baseline_record.get("is_binary"))
            or (final_record and final_record.get("is_binary"))
        )
        changed_files.append(
            {
                "path": path,
                "change_type": change_type,
                "sha256_before": baseline_record["sha256"] if baseline_record else None,
                "sha256_after": final_record["sha256"] if final_record else None,
                "size_before": baseline_record["size_bytes"] if baseline_record else None,
                "size_after": final_record["size_bytes"] if final_record else None,
                "is_binary": is_binary,
            }
        )
        stats[change_type] += 1
        stats["changed_total"] += 1

        if is_binary:
            stats["binary_files"] += 1
            continue

        stats["text_files"] += 1
        before_text = (baseline_record or {}).get("content") or ""
        after_text = (final_record or {}).get("content") or ""
        before_lines = before_text.splitlines()
        after_lines = after_text.splitlines()
        diff = difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
        diff_lines.extend(list(diff))

    stats["diff_lines"] = len(diff_lines)
    diff_text = "\n".join(diff_lines)
    return {
        "diff": diff_text,
        "changed_files": changed_files,
        "stats": stats,
    }


def resolve_latest_review_summary(container: Optional[Container]) -> Dict[str, Any]:
    if not container:
        return {}
    review_reports = container.artifacts.get("review_report", [])
    if not review_reports:
        return {}
    latest = review_reports[-1].content if hasattr(review_reports[-1], "content") else review_reports[-1]
    if not isinstance(latest, dict):
        return {}
    issues = latest.get("issues")
    issues_count = len(issues) if isinstance(issues, list) else 0
    return {
        "passed": latest.get("passed"),
        "status": latest.get("status"),
        "issues_count": issues_count,
        "run_id": latest.get("run_id"),
    }


def get_tool_version(command: List[str]) -> Optional[str]:
    executable = command[0]
    if not shutil.which(executable):
        return None
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    output = (result.stdout or result.stderr or "").strip()
    return output or None


def get_requirements_hash() -> Dict[str, Optional[str]]:
    requirements_path = Path(__file__).resolve().parents[1] / "requirements.txt"
    if requirements_path.exists():
        payload = requirements_path.read_bytes()
        return {
            "requirements_path": str(requirements_path),
            "requirements_sha256": hashlib.sha256(payload).hexdigest(),
            "pip_freeze_sha256": None,
        }
    result = subprocess.run(
        [sys.executable, "-m", "pip", "freeze"],
        capture_output=True,
        text=True,
        check=False,
    )
    output = (result.stdout or "").encode("utf-8")
    return {
        "requirements_path": None,
        "requirements_sha256": None,
        "pip_freeze_sha256": hashlib.sha256(output).hexdigest(),
    }


def build_repro_manifest_payload(
    *,
    task_id: str,
    container: Optional[Container],
    task_data: Optional[Dict[str, Any]],
    review_summary: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    requirements = get_requirements_hash()
    codex_version = container.metadata.get("codex_version") if container else None
    codex_hash = container.metadata.get("codex_hash") if container else None
    created_at = to_iso_string(task_data.get("created_at")) if task_data else None
    completed_at = to_iso_string(task_data.get("completed_at")) if task_data else None
    return {
        "task_id": task_id,
        "generated_at": db.now_utc().isoformat(),
        "created_at": created_at,
        "completed_at": completed_at,
        "python_version": sys.version.replace("\n", " "),
        "platform": platform.platform(),
        "requirements_path": requirements["requirements_path"],
        "requirements_sha256": requirements["requirements_sha256"],
        "pip_freeze_sha256": requirements["pip_freeze_sha256"],
        "ruff_version": get_tool_version(["ruff", "--version"]),
        "pytest_version": get_tool_version(["pytest", "--version"]),
        "codex_version": codex_version,
        "codex_hash": codex_hash,
        "review_summary": review_summary or {},
    }


async def persist_container_snapshot(task_id: str, container: Container) -> None:
    if not db.is_enabled():
        return
    await db.upsert_container_snapshot(task_id, build_container_snapshot(container))


def build_file_payload(filepath: str, content: Any) -> Dict[str, Any]:
    if isinstance(content, bytes):
        payload = content
        content_text = None
        content_bytes = content
    else:
        payload = str(content).encode("utf-8")
        content_text = str(content)
        content_bytes = None
    return {
        "payload": payload,
        "content": content_text,
        "content_bytes": content_bytes,
        "mime_type": mimetypes.guess_type(filepath)[0],
    }


async def persist_container_file(task_id: str, filepath: str, content: Any) -> None:
    if not db.is_enabled():
        return
    file_data = build_file_payload(filepath, content)
    sha256 = hashlib.sha256(file_data["payload"]).hexdigest()
    size_bytes = len(file_data["payload"])
    await db.upsert_task_file(
        task_id,
        filepath,
        content=file_data["content"],
        content_bytes=file_data["content_bytes"],
        mime_type=file_data["mime_type"],
        sha256=sha256,
        size_bytes=size_bytes,
        max_bytes=MAX_TASK_BYTES,
        max_files=MAX_TASK_FILES,
    )


async def persist_all_container_files(task_id: str, container: Container) -> None:
    if not db.is_enabled():
        return
    for filepath, content in container.files.items():
        await persist_container_file(task_id, filepath, content)


async def build_zip_response(task_id: str, request: Request) -> StreamingResponse:
    container = await resolve_container_with_db(task_id)
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    if db.is_enabled():
        task_data = await db.get_task_row(task_id)
        if task_data is None:
            raise HTTPException(status_code=404, detail="Task not found")
    else:
        task_data = storage.active_tasks.get(task_id) or {}

    updated_at = parse_datetime(task_data.get("updated_at")) if task_data else None
    timestamp_source = updated_at or db.now_utc()
    if timestamp_source.tzinfo is None:
        timestamp_source = timestamp_source.replace(tzinfo=timezone.utc)
    timestamp_source = timestamp_source.astimezone(timezone.utc)
    zip_timestamp = (
        timestamp_source.year,
        timestamp_source.month,
        timestamp_source.day,
        timestamp_source.hour,
        timestamp_source.minute,
        timestamp_source.second,
    )

    root_folder = f"task_{task_id}/"
    files_manifest: List[Dict[str, Any]] = []
    files_count = len(container.files)
    artifacts_count = sum(len(items) for items in container.artifacts.values())
    iterations = container.metadata.get("iterations") or 0
    api_base_url = str(request.base_url).rstrip("/")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        root_info = zipfile.ZipInfo(root_folder)
        root_info.flag_bits |= 0x800  # UTF-8 filenames
        root_info.date_time = zip_timestamp
        root_info.external_attr = 0o40775 << 16
        zip_file.writestr(root_info, b"")

        for filepath, content in container.files.items():
            safe_path = sanitize_zip_path(filepath)
            payload = content.encode("utf-8") if isinstance(content, str) else content
            files_manifest.append(
                {
                    "path": safe_path,
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
            archive_path = f"{root_folder}{safe_path}"
            zip_info = zipfile.ZipInfo(archive_path)
            zip_info.flag_bits |= 0x800  # UTF-8 filenames
            zip_info.date_time = zip_timestamp
            zip_file.writestr(zip_info, payload)

        manifest_payload = {
            "task_id": task_id,
            "status": task_data.get("status"),
            "created_at": to_iso_string(task_data.get("created_at") or container.created_at),
            "updated_at": to_iso_string(task_data.get("updated_at") or container.updated_at),
            "iterations": iterations,
            "files_count": files_count,
            "artifacts_count": artifacts_count,
            "api_base_url": api_base_url,
            "files": files_manifest,
        }
        manifest_bytes = json.dumps(manifest_payload, ensure_ascii=False, indent=2).encode("utf-8")
        manifest_info = zipfile.ZipInfo(f"{root_folder}manifest.json")
        manifest_info.flag_bits |= 0x800  # UTF-8 filenames
        manifest_info.date_time = zip_timestamp
        zip_file.writestr(manifest_info, manifest_bytes)

    buffer.seek(0)
    headers = {
        "Content-Disposition": f'attachment; filename="task_{task_id}.zip"'
    }
    return StreamingResponse(buffer, media_type="application/zip", headers=headers)

# CORS для Telegram Mini App и локальной разработки
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Роуты API
@app.get("/")
async def root():
    """Корневой endpoint для проверки работы"""
    return {
        "message": "AI Collaboration Platform API",
        "version": "1.0.0-mvp",
        "status": "operational",
        "endpoints": {
            "api_docs": "/docs",
            "health": "/health",
            "create_task": "/api/tasks (POST)",
            "get_task": "/api/tasks/{task_id} (GET)"
        }
    }

@app.get("/health")
async def health_check():
    """Health check для мониторинга"""
    return {
        "status": "healthy",
        "timestamp": asyncio.get_event_loop().time(),
        "active_tasks": len(storage.active_tasks),
        "active_connections": len(manager.active_connections)
    }


@app.get("/ops/status")
async def ops_status():
    """Operational status endpoint for observability."""
    generated_at = db.now_utc().isoformat()
    if db.is_enabled():
        metrics = await db.get_task_status_metrics()
        states = await db.list_task_states()
        llm_summaries = []
        for state_row in states:
            state = state_row.get("state") or {}
            if isinstance(state, dict):
                summary = state.get("llm_usage_summary")
                if summary:
                    llm_summaries.append(summary)
        success = metrics.get("completed", 0) or 0
        failed = metrics.get("failed", 0) or 0
        total_terminal = success + failed
        return {
            "generated_at": generated_at,
            "active_tasks": metrics.get("active_tasks", 0) or 0,
            "average_duration_seconds": metrics.get("avg_duration_seconds"),
            "success_rate": (success / total_terminal) if total_terminal else None,
            "fail_rate": (failed / total_terminal) if total_terminal else None,
            "success_count": success,
            "fail_count": failed,
            "llm_usage_totals": aggregate_llm_usage(llm_summaries),
        }

    tasks = list(storage.active_tasks.values())
    terminal_statuses = {"completed", "failed", "error"}
    active_tasks = len([task for task in tasks if task.get("status") not in terminal_statuses])
    completed = len([task for task in tasks if task.get("status") == "completed"])
    failed = len([task for task in tasks if task.get("status") in {"failed", "error"}])
    durations = [
        compute_time_taken_seconds(task)
        for task in tasks
        if task.get("status") in terminal_statuses
    ]
    durations = [duration for duration in durations if duration is not None]
    avg_duration = sum(durations) / len(durations) if durations else None
    llm_summaries = []
    for state_row in storage.state.values():
        state = state_row.get("state") or {}
        if isinstance(state, dict):
            summary = state.get("llm_usage_summary")
            if summary:
                llm_summaries.append(summary)
    total_terminal = completed + failed
    return {
        "generated_at": generated_at,
        "active_tasks": active_tasks,
        "average_duration_seconds": avg_duration,
        "success_rate": (completed / total_terminal) if total_terminal else None,
        "fail_rate": (failed / total_terminal) if total_terminal else None,
        "success_count": completed,
        "fail_count": failed,
        "llm_usage_totals": aggregate_llm_usage(llm_summaries),
    }

@app.post("/api/tasks", response_model=TaskResponse)
async def create_task(request: TaskRequest, req: Request):
    """Создание новой задачи для обработки ИИ"""
    api_key = require_api_key(req)
    owner_key_hash = hash_api_key(api_key)
    task_id = str(uuid.uuid4())
    user_id = request.user_id or f"user_{uuid.uuid4().hex[:8]}"
    request_id = get_request_id()
    task_token = set_task_id(task_id)
    try:
        logger.info("Creating new task task_id=%s user_id=%s", task_id, user_id)
    
        client_ip = req.client.host if req.client else None

        if db.is_enabled():
            await db.create_task_row(
                task_id=task_id,
                user_id=user_id,
                description=request.description,
                status="created",
                progress=0.0,
                current_stage=None,
                codex_version=request.codex_version,
                client_ip=client_ip,
                owner_key_hash=owner_key_hash,
            )
        else:
            # Сохраняем задачу
            now = db.now_utc()
            storage.active_tasks[task_id] = {
                "id": task_id,
                "description": request.description,
                "user_id": user_id,
                "status": "created",
                "progress": 0.0,
                "created_at": now,
                "updated_at": now,
                "codex_version": request.codex_version,
                "client_ip": client_ip,
                "owner_key_hash": owner_key_hash,
                "request_id": request_id,
                "failure_reason": None,
            }
            
            # Сохраняем связь пользователь -> задача
            if user_id not in storage.user_sessions:
                storage.user_sessions[user_id] = []
            storage.user_sessions[user_id].append(task_id)

        await record_event(
            task_id,
            "TaskCreated",
            normalize_payload({"user_id": user_id, "codex_version": request.codex_version}),
        )
        await record_state(
            task_id,
            build_container_state(
                status="created",
                progress=0.0,
                current_stage=None,
                include_created_at=True,
            ),
        )
        
        # Запускаем обработку в фоне
        asyncio.create_task(process_task_background(task_id, request.description, request_id))
        
        return TaskResponse(
            task_id=task_id,
            status="created",
            message="Task started processing",
            progress=0.0,
            estimated_time=60  # Примерное время в секундах
        )
    finally:
        reset_task_id(task_token)

@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str, request: Request):
    """Получение статуса задачи"""
    task_token = set_task_id(task_id)
    try:
        task_data = await ensure_task_owner(task_id, request)
        if db.is_enabled():
            await resolve_container_with_db(task_id)
        return enrich_task_data(task_id, task_data)
    finally:
        reset_task_id(task_token)


@app.post("/api/tasks/{task_id}/rerun-review")
async def rerun_review(task_id: str, request: Request):
    """Перезапуск ревью для существующей задачи"""
    task_token = set_task_id(task_id)
    try:
        await ensure_task_owner(task_id, request)
        container = await resolve_container_with_db(task_id)
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")
        review_result = await run_review_for_task(task_id, container)
        return {
            "task_id": task_id,
            "run_id": review_result.get("run_id"),
            "review_report": review_result,
        }
    finally:
        reset_task_id(task_token)


@app.get("/api/tasks/{task_id}/events", response_model=EventsResponse)
async def get_task_events(task_id: str, request: Request, limit: int = 200, order: str = "desc"):
    """Получение событий контейнера"""
    task_token = set_task_id(task_id)
    try:
        normalized_order = validate_order(order)
        await ensure_task_owner(task_id, request)
        if db.is_enabled():
            events = await db.get_events(task_id, limit=limit, order=normalized_order)
        else:
            ensure_task_exists_in_memory(task_id)
            events = get_in_memory_events(task_id, limit=limit, order=normalized_order)
        return {
            "task_id": task_id,
            "total": len(events),
            "events": [normalize_event_item(event) for event in events],
        }
    finally:
        reset_task_id(task_token)


@app.get("/api/tasks/{task_id}/artifacts", response_model=ArtifactsResponse)
async def get_task_artifacts(
    task_id: str,
    request: Request,
    type: Optional[str] = None,
    limit: int = 200,
    order: str = "desc",
):
    """Получение артефактов контейнера"""
    task_token = set_task_id(task_id)
    try:
        normalized_order = validate_order(order)
        await ensure_task_owner(task_id, request)
        if db.is_enabled():
            artifacts = await db.get_artifacts(task_id, type=type, limit=limit, order=normalized_order)
        else:
            ensure_task_exists_in_memory(task_id)
            artifacts = get_in_memory_artifacts(task_id, type, limit=limit, order=normalized_order)
        artifacts = dedupe_artifacts(artifacts)
        return {
            "task_id": task_id,
            "total": len(artifacts),
            "artifacts": [normalize_artifact_item(artifact) for artifact in artifacts],
        }
    finally:
        reset_task_id(task_token)


@app.get("/api/tasks/{task_id}/state", response_model=ContainerStateResponse)
async def get_task_state(task_id: str, request: Request):
    """Получение состояния контейнера"""
    task_token = set_task_id(task_id)
    try:
        await ensure_task_owner(task_id, request)
        if db.is_enabled():
            state_row = await db.get_container_state(task_id)
        else:
            ensure_task_exists_in_memory(task_id)
            state_row = get_in_memory_state(task_id)
        return {
            "task_id": task_id,
            "state": normalize_container_state(state_row["state"]) if state_row else ContainerStateSnapshot(),
            "updated_at": to_iso_string(state_row["updated_at"]) if state_row else None,
        }
    finally:
        reset_task_id(task_token)

@app.get("/api/tasks/{task_id}/files")
async def get_task_files(task_id: str, request: Request):
    """Получение списка файлов задачи"""
    task_token = set_task_id(task_id)
    try:
        await ensure_task_owner(task_id, request)
        container = await resolve_container_with_db(task_id)
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")
    
    # Группируем файлы по типам
    files_by_type = {
        "code": [f for f in container.files.keys() if f.endswith('.py')],
        "config": [f for f in container.files.keys() if any(
            ext in f for ext in ['.json', '.yaml', '.yml', '.toml', '.env']
        )],
        "docs": [f for f in container.files.keys() if any(
            ext in f for ext in ['.md', '.txt', '.rst']
        )],
        "tests": [f for f in container.files.keys() if 'test' in f.lower()],
        "other": [f for f in container.files.keys() if not any(
            pattern in f for pattern in ['.py', '.json', '.yaml', '.md', 'test']
        )]
    }
    
        return {
            "total": len(container.files),
            "by_type": files_by_type,
            "all_files": list(container.files.keys())
        }
    finally:
        reset_task_id(task_token)

@app.get("/api/tasks/{task_id}/files/{filepath:path}")
async def get_file_content(task_id: str, filepath: str, request: Request):
    """Получение содержимого файла"""
    task_token = set_task_id(task_id)
    try:
        await ensure_task_owner(task_id, request)
        container = await resolve_container_with_db(task_id)
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")
    
    # Ищем файл (с учетом возможных путей)
    actual_path = None
    for stored_path in container.files.keys():
        if stored_path.endswith(filepath) or filepath in stored_path:
            actual_path = stored_path
            break
    
    if not actual_path or actual_path not in container.files:
        raise HTTPException(status_code=404, detail="File not found")
    
    content = container.files[actual_path]
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    
        return {
            "path": actual_path,
            "content": content,
            "size": len(content),
            "language": get_language_from_extension(actual_path)
        }
    finally:
        reset_task_id(task_token)

@app.post("/api/tasks/{task_id}/download")
async def download_task_files(task_id: str, request: Request):
    """Скачать файлы задачи ZIP архивом"""
    task_token = set_task_id(task_id)
    try:
        await ensure_task_owner(task_id, request)
        return await build_zip_response(task_id, request)
    finally:
        reset_task_id(task_token)


@app.get("/api/tasks/{task_id}/download.zip")
async def download_task_files_get(task_id: str, request: Request):
    """Скачать файлы задачи ZIP архивом (GET alias)"""
    task_token = set_task_id(task_id)
    try:
        await ensure_task_owner(task_id, request)
        return await build_zip_response(task_id, request)
    finally:
        reset_task_id(task_token)

@app.get("/api/users/{user_id}/tasks")
async def get_user_tasks(user_id: str, limit: int = 10):
    """Получение задач пользователя"""
    if db.is_enabled():
        tasks = await db.list_tasks_for_user(user_id, limit)
        tasks = [enrich_task_data(str(task["id"]), task) for task in tasks]
        return {
            "user_id": user_id,
            "tasks": tasks,
            "total": len(tasks),
            "limit": limit,
        }

    if user_id not in storage.user_sessions:
        return {"tasks": [], "total": 0}
    
    task_ids = storage.user_sessions[user_id][-limit:]  # Последние N задач
    tasks = []
    
    for task_id in task_ids:
        if task_id in storage.active_tasks:
            tasks.append(storage.active_tasks[task_id])
    
    return {
        "user_id": user_id,
        "tasks": tasks,
        "total": len(tasks),
        "limit": limit
    }

@app.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """WebSocket для real-time обновлений прогресса"""
    task_token = set_task_id(task_id)
    try:
        access_key = await ensure_websocket_owner(websocket, task_id)
        if access_key is None:
            return
        await manager.connect(websocket, task_id)
        
        try:
            # Отправляем текущее состояние при подключении
            if db.is_enabled():
                task_data = await db.get_task_row(task_id)
                if task_data:
                    await manager.send_progress(task_id, enrich_task_data(task_id, task_data))
            elif task_id in storage.active_tasks:
                await manager.send_progress(task_id, storage.active_tasks[task_id])
            
            # Держим соединение открытым
            while True:
                data = await websocket.receive_text()
                # Можно обрабатывать команды от клиента
                if data == "ping":
                    await websocket.send_text("pong")
                    
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected for task_id=%s", task_id)
            manager.disconnect(task_id)
        except Exception as e:
            logger.error("WebSocket error for task_id=%s: %s", task_id, e)
            manager.disconnect(task_id)
    finally:
        reset_task_id(task_token)

async def process_task_background(task_id: str, description: str, request_id: Optional[str] = None):
    """Фоновая обработка задачи ИИ-агентами"""
    request_token = set_request_id(request_id)
    task_token = set_task_id(task_id)
    failure_context: Dict[str, Optional[str]] = {"stage": None, "reason": None}
    try:
        logger.info("Starting AI processing for task_id=%s", task_id)

        async def apply_task_update(fields: Dict[str, Any]) -> None:
            if db.is_enabled():
                task_data = await db.update_task_row(task_id, fields)
                if task_data:
                    await manager.send_progress(task_id, enrich_task_data(task_id, task_data))
            else:
                fields.setdefault("updated_at", db.now_utc())
                storage.active_tasks[task_id].update(fields)
                await manager.send_progress(task_id, storage.active_tasks[task_id])

        # Обновляем статус
        await apply_task_update(
            {
                "status": "processing",
                "progress": 0.1,
                "current_stage": "initializing",
            }
        )
        await record_event(
            task_id,
            "StageStarted",
            normalize_payload({"stage": "initializing"}),
        )
        await record_state(
            task_id,
            build_container_state(
                status="processing",
                progress=0.1,
                current_stage="initializing",
            ),
        )
        
        # Создаем оркестратор и контейнер
        orchestrator = AIOrchestrator()
        container = orchestrator.initialize_project(f"Task-{task_id[:8]}")
        baseline_files = capture_baseline_files(container)
        container.metadata["baseline_files"] = baseline_files
        workspace = TaskWorkspace(task_id, WORKSPACE_ROOT)
        workspace.materialize(container)
        container.metadata["workspace_path"] = str(workspace.path)
        container.file_update_hook = workspace.write_file
        command_runner = build_command_runner(task_id, workspace.path)
        await persist_container_snapshot(task_id, container)
        storage.containers[task_id] = container

        stage_progress = {
            "research": 0.2,
            "design": 0.4,
            "implementation": 0.6,
            "review": 0.9,
        }
        stage_role = {
            "research": "researcher",
            "design": "designer",
            "implementation": "coder",
            "review": "reviewer",
        }

        async def handle_stage_started(payload: Dict[str, Any]) -> None:
            stage = payload.get("stage")
            progress = stage_progress.get(stage, 0.1)
            await apply_task_update(
                {
                    "progress": progress,
                    "current_stage": stage,
                }
            )
            await record_event(
                task_id,
                "StageStarted",
                normalize_payload({"stage": stage}),
            )
            await record_state(
                task_id,
                build_container_state(
                    status="processing",
                    progress=progress,
                    current_stage=stage,
                    container=container,
                    active_role=stage_role.get(stage),
                ),
            )
            await persist_container_snapshot(task_id, container)

        async def handle_research_complete(payload: Dict[str, Any]) -> None:
            result = payload.get("result")
            await record_artifact(
                task_id,
                "research_summary",
                normalize_payload(result),
                produced_by="researcher",
            )
            await record_event(
                task_id,
                "ArtifactAdded",
                normalize_payload({"type": "research_summary"}),
            )
            await persist_all_container_files(task_id, container)
            await persist_container_snapshot(task_id, container)

        async def handle_design_complete(payload: Dict[str, Any]) -> None:
            result = payload.get("result")
            await record_artifact(
                task_id,
                "architecture",
                normalize_payload(result),
                produced_by="designer",
            )
            await record_event(
                task_id,
                "ArtifactAdded",
                normalize_payload({"type": "architecture"}),
            )
            await persist_all_container_files(task_id, container)
            await persist_container_snapshot(task_id, container)

        async def handle_review_started(payload: Dict[str, Any]) -> None:
            await record_event(
                task_id,
                "review_started",
                normalize_payload(payload),
            )

        async def handle_coder_finished(payload: Dict[str, Any]) -> None:
            sync_result = workspace.sync_to_container(container)
            changed_files = sync_result.get("changed", [])
            removed_files = sync_result.get("removed", [])
            for path in changed_files:
                content = container.files.get(path)
                if content is not None:
                    await persist_container_file(task_id, path, content)
            if db.is_enabled():
                for path in removed_files:
                    await db.delete_task_file(task_id, path)
            await persist_container_snapshot(task_id, container)

        async def handle_review_finished(payload: Dict[str, Any]) -> None:
            result = payload.get("result") if isinstance(payload, dict) else None
            await record_event(
                task_id,
                "review_finished",
                normalize_payload(
                    {
                        "kind": payload.get("kind") if isinstance(payload, dict) else None,
                        "iteration": payload.get("iteration") if isinstance(payload, dict) else None,
                        "passed": result.get("passed") if isinstance(result, dict) else None,
                        "status": result.get("status") if isinstance(result, dict) else None,
                    }
                ),
            )

        async def handle_review_result(payload: Dict[str, Any]) -> None:
            result = payload.get("result")
            await record_artifact(
                task_id,
                "review_report",
                normalize_payload(result),
                produced_by="reviewer",
            )
            issues = result.get("issues") if isinstance(result, dict) else None
            issues_count = len(issues) if isinstance(issues, list) else 0
            await record_event(
                task_id,
                "ReviewResult",
                normalize_payload(
                    {
                        "status": result.get("status") if isinstance(result, dict) else None,
                        "issues_count": issues_count,
                        "kind": payload.get("kind"),
                    }
                ),
            )
            await persist_all_container_files(task_id, container)
            await persist_container_snapshot(task_id, container)

        async def handle_codex_loaded(payload: Dict[str, Any]) -> None:
            await record_event(
                task_id,
                "codex_loaded",
                normalize_payload(payload),
            )

        async def handle_llm_usage(payload: Dict[str, Any]) -> None:
            usage = payload.get("usage") if isinstance(payload, dict) else payload
            await record_event(
                task_id,
                "llm_usage",
                normalize_payload(usage or {}),
            )
            usage_report = payload.get("usage_report") if isinstance(payload, dict) else None
            if usage_report:
                await record_artifact(
                    task_id,
                    "usage_report",
                    normalize_payload(usage_report),
                    produced_by="coder",
                )
                await record_event(
                    task_id,
                    "ArtifactAdded",
                    normalize_payload({"type": "usage_report"}),
                )
            await record_state(
                task_id,
                build_container_state(
                    status="processing",
                    progress=container.progress,
                    current_stage=container.state.value,
                    container=container,
                    active_role=container.metadata.get("active_role"),
                    current_task=container.current_task,
                ),
            )
            await persist_container_snapshot(task_id, container)

        async def handle_llm_error(payload: Dict[str, Any]) -> None:
            await record_event(
                task_id,
                "llm_error",
                normalize_payload(payload),
            )

        async def handle_stage_failed(payload: Dict[str, Any]) -> None:
            stage = payload.get("stage") if isinstance(payload, dict) else None
            reason = payload.get("reason") if isinstance(payload, dict) else None
            error = payload.get("error") if isinstance(payload, dict) else None
            failure_context["stage"] = stage or failure_context["stage"]
            failure_context["reason"] = reason or error or failure_context["reason"]
            await record_event(
                task_id,
                "stage_failed",
                normalize_payload(
                    {
                        "stage": stage,
                        "reason": reason,
                        "error": error,
                        "status": "failed",
                    }
                ),
            )
        
        # Обрабатываем задачу
        result = await orchestrator.process_task(
            description,
            callbacks={
                "stage_started": handle_stage_started,
                "research_complete": handle_research_complete,
                "design_complete": handle_design_complete,
                "coder_finished": handle_coder_finished,
                "review_started": handle_review_started,
                "review_finished": handle_review_finished,
                "review_result": handle_review_result,
                "codex_loaded": handle_codex_loaded,
                "llm_usage": handle_llm_usage,
                "llm_error": handle_llm_error,
                "stage_failed": handle_stage_failed,
            },
            workspace_path=workspace.path,
            command_runner=command_runner,
        )

        review_summary = resolve_latest_review_summary(container)
        patch_payload = build_patch_diff_payload(
            container.metadata.get("baseline_files") or {},
            container.files,
        )
        container.add_artifact("patch_diff", patch_payload, "system")
        await record_artifact(
            task_id,
            "patch_diff",
            normalize_payload(patch_payload),
            produced_by="system",
        )
        await record_event(
            task_id,
            "ArtifactAdded",
            normalize_payload({"type": "patch_diff"}),
        )

        completed_at = db.now_utc()
        manifest_payload = build_repro_manifest_payload(
            task_id=task_id,
            container=container,
            task_data={
                "created_at": storage.active_tasks.get(task_id, {}).get("created_at")
                if not db.is_enabled()
                else None,
                "completed_at": completed_at,
            },
            review_summary=review_summary,
        )
        if db.is_enabled():
            task_data = await db.get_task_row(task_id)
            if task_data:
                manifest_payload["created_at"] = to_iso_string(task_data.get("created_at"))
        container.add_artifact("repro_manifest", manifest_payload, "system")
        await record_artifact(
            task_id,
            "repro_manifest",
            normalize_payload(manifest_payload),
            produced_by="system",
        )
        await record_event(
            task_id,
            "ArtifactAdded",
            normalize_payload({"type": "repro_manifest"}),
        )
        
        # Сохраняем контейнер в файл (для persistence)
        save_container_to_file(task_id, container)
        await persist_all_container_files(task_id, container)
        await persist_container_snapshot(task_id, container)
        
        # Обновляем финальный статус
        final_status = result.get("status")
        final_progress = result.get("progress", 1.0)
        if final_status in {"completed", "failed"}:
            final_progress = 1.0
        final_stage = "review" if final_status == "failed" else "completed"
        result["progress"] = final_progress
        if result.get("max_iterations") is None:
            result["max_iterations"] = container.metadata.get("max_iterations")
        failure_reason = result.get("failure_reason") or failure_context.get("reason")
        if final_status in {"failed", "error"}:
            if failure_reason:
                result["failure_reason"] = failure_reason
            await record_event(
                task_id,
                "stage_failed",
                normalize_payload(
                    {
                        "stage": failure_context.get("stage") or final_stage,
                        "reason": failure_reason,
                        "status": final_status,
                    }
                ),
            )
        await apply_task_update(
            {
                "status": final_status,
                "progress": final_progress,
                "current_stage": final_stage,
                "result": result,
                "completed_at": completed_at,
                "error": failure_reason,
                "failure_reason": failure_reason,
            }
        )
        await record_event(
            task_id,
            "TaskCompleted",
            normalize_payload(
                {"status": final_status, "progress": final_progress}
            ),
        )
        await record_state(
            task_id,
            build_container_state(
                status=final_status,
                progress=final_progress,
                current_stage=final_stage,
                container=container,
                active_role=container.metadata.get("active_role") if container else None,
                current_task=container.current_task if container else None,
            ),
        )
        logger.info("Task %s completed with status: %s", task_id, final_status)
        
    except Exception as e:
        logger.error(f"Error processing task {task_id}: {e}")
        failure_reason = str(e)
        await record_event(
            task_id,
            "stage_failed",
            normalize_payload(
                {
                    "stage": failure_context.get("stage") or "processing",
                    "reason": failure_reason,
                    "status": "error",
                }
            ),
        )
        await apply_task_update(
            {
                "status": "error",
                "error": failure_reason,
                "failure_reason": failure_reason,
                "progress": 0.0,
                "current_stage": "failed",
            }
        )
        await record_event(
            task_id,
            "TaskFailed",
            normalize_payload({"error": failure_reason}),
        )
        await record_state(
            task_id,
            build_container_state(
                status="error",
                progress=0.0,
                current_stage="failed",
                container=storage.containers.get(task_id),
            ),
        )
    finally:
        reset_task_id(task_token)
        reset_request_id(request_token)

def save_container_to_file(task_id: str, container: Container):
    """Сохраняет контейнер в JSON файл"""
    if not get_file_persistence_setting():
        logger.debug(
            "File persistence disabled; skipping container save for task %s",
            task_id,
        )
        return
    try:
        data = container.to_dict()
        filepath = f"data/tasks/{task_id}.json"
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
        
        logger.info(f"Container saved to {filepath}")
    except Exception as e:
        logger.error(f"Error saving container: {e}")

def get_language_from_extension(filename: str) -> str:
    """Определяет язык программирования по расширению файла"""
    ext_map = {
        '.py': 'python',
        '.js': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',
        '.html': 'html',
        '.css': 'css',
        '.json': 'json',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.md': 'markdown',
        '.txt': 'text',
        '.sh': 'bash',
        '.sql': 'sql',
        '.java': 'java',
        '.cpp': 'cpp',
        '.c': 'c',
        '.go': 'go',
        '.rs': 'rust',
        '.rb': 'ruby',
        '.php': 'php'
    }
    
    for ext, lang in ext_map.items():
        if filename.endswith(ext):
            return lang
    
    return 'text'

# Монтируем статические файлы фронтенда
frontend_path = Path(__file__).parent.parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/app", StaticFiles(directory=frontend_path, html=True), name="frontend")
    
    @app.get("/app/{full_path:path}")
    async def serve_frontend(full_path: str):
        """Сервис для фронтенда"""
        file_path = frontend_path / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(frontend_path / "index.html")

if __name__ == "__main__":
    import uvicorn

    environment = os.getenv("ENVIRONMENT", "").lower()
    port = int(os.getenv("PORT", "8000"))

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=environment != "production",
        log_level="info"
    )
