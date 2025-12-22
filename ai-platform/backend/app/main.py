"""
Основной FastAPI сервер для Telegram Mini App
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager
import uuid
import json
import asyncio
from typing import Dict, Optional, List
import logging
import os
from pathlib import Path

from .models import Container
from .orchestrator import AIOrchestrator

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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

storage = Storage()

# WebSocket менеджер
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, task_id: str):
        await websocket.accept()
        self.active_connections[task_id] = websocket
        logger.info(f"WebSocket connected for task {task_id}")
    
    def disconnect(self, task_id: str):
        if task_id in self.active_connections:
            del self.active_connections[task_id]
            logger.info(f"WebSocket disconnected for task {task_id}")
    
    async def send_progress(self, task_id: str, data: dict):
        if task_id in self.active_connections:
            try:
                await self.active_connections[task_id].send_json(data)
                return True
            except Exception as e:
                logger.error(f"Error sending WebSocket message: {e}")
                self.disconnect(task_id)
        return False

manager = ConnectionManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    logger.info("Starting AI Platform Backend...")
    
    # Создаем директории если их нет
    os.makedirs("data/tasks", exist_ok=True)
    os.makedirs("data/logs", exist_ok=True)
    
    yield
    
    logger.info("Shutting down AI Platform Backend...")
    # Очистка ресурсов

app = FastAPI(
    title="AI Collaboration Platform API",
    description="Backend для платформы коллаборации ИИ с Telegram Mini App",
    version="1.0.0-mvp",
    lifespan=lifespan
)

# CORS для Telegram Mini App и локальной разработки
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://telegram.org",
        "https://web.telegram.org",
        "http://localhost:3000",
        "http://localhost:8000",
        "*"  # Для разработки, в продакшене укажите конкретные домены
    ],
    allow_credentials=True,
    allow_methods=["*"],
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

@app.post("/api/tasks", response_model=TaskResponse)
async def create_task(request: TaskRequest, req: Request):
    """Создание новой задачи для обработки ИИ"""
    task_id = str(uuid.uuid4())
    user_id = request.user_id or f"user_{uuid.uuid4().hex[:8]}"
    
    logger.info(f"Creating new task {task_id} for user {user_id}")
    
    # Сохраняем задачу
    storage.active_tasks[task_id] = {
        "id": task_id,
        "description": request.description,
        "user_id": user_id,
        "status": "created",
        "progress": 0.0,
        "created_at": asyncio.get_event_loop().time(),
        "codex_version": request.codex_version,
        "client_ip": req.client.host if req.client else None
    }
    
    # Сохраняем связь пользователь -> задача
    if user_id not in storage.user_sessions:
        storage.user_sessions[user_id] = []
    storage.user_sessions[user_id].append(task_id)
    
    # Запускаем обработку в фоне
    asyncio.create_task(process_task_background(task_id, request.description))
    
    return TaskResponse(
        task_id=task_id,
        status="created",
        message="Task started processing",
        progress=0.0,
        estimated_time=60  # Примерное время в секундах
    )

@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Получение статуса задачи"""
    if task_id not in storage.active_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task_data = storage.active_tasks[task_id]
    
    # Если есть контейнер, добавляем информацию о файлах
    if task_id in storage.containers:
        container = storage.containers[task_id]
        task_data["files_count"] = len(container.files)
        task_data["artifacts_count"] = sum(len(a) for a in container.artifacts.values())
    
    return task_data

@app.get("/api/tasks/{task_id}/files")
async def get_task_files(task_id: str):
    """Получение списка файлов задачи"""
    if task_id not in storage.containers:
        raise HTTPException(status_code=404, detail="Container not found")
    
    container = storage.containers[task_id]
    
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

@app.get("/api/tasks/{task_id}/files/{filepath:path}")
async def get_file_content(task_id: str, filepath: str):
    """Получение содержимого файла"""
    if task_id not in storage.containers:
        raise HTTPException(status_code=404, detail="Container not found")
    
    container = storage.containers[task_id]
    
    # Ищем файл (с учетом возможных путей)
    actual_path = None
    for stored_path in container.files.keys():
        if stored_path.endswith(filepath) or filepath in stored_path:
            actual_path = stored_path
            break
    
    if not actual_path or actual_path not in container.files:
        raise HTTPException(status_code=404, detail="File not found")
    
    content = container.files[actual_path]
    
    return {
        "path": actual_path,
        "content": content,
        "size": len(content),
        "language": get_language_from_extension(actual_path)
    }

@app.post("/api/tasks/{task_id}/download")
async def download_task_files(task_id: str):
    """Подготовка файлов задачи для скачивания"""
    if task_id not in storage.containers:
        raise HTTPException(status_code=404, detail="Container not found")
    
    # В реальной реализации здесь создавался бы ZIP архив
    # Для MVP возвращаем информацию о файлах
    container = storage.containers[task_id]
    
    return {
        "task_id": task_id,
        "files_count": len(container.files),
        "download_url": f"/api/tasks/{task_id}/zip",  # Будет реализовано позже
        "instructions": "Use the download_url to get ZIP archive"
    }

@app.get("/api/users/{user_id}/tasks")
async def get_user_tasks(user_id: str, limit: int = 10):
    """Получение задач пользователя"""
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
    await manager.connect(websocket, task_id)
    
    try:
        # Отправляем текущее состояние при подключении
        if task_id in storage.active_tasks:
            await manager.send_progress(task_id, storage.active_tasks[task_id])
        
        # Держим соединение открытым
        while True:
            data = await websocket.receive_text()
            # Можно обрабатывать команды от клиента
            if data == "ping":
                await websocket.send_text("pong")
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for task {task_id}")
        manager.disconnect(task_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(task_id)

async def process_task_background(task_id: str, description: str):
    """Фоновая обработка задачи ИИ-агентами"""
    try:
        logger.info(f"Starting AI processing for task {task_id}")
        
        # Обновляем статус
        storage.active_tasks[task_id].update({
            "status": "processing",
            "progress": 0.1,
            "current_stage": "initializing"
        })
        await manager.send_progress(task_id, storage.active_tasks[task_id])
        
        # Создаем оркестратор и контейнер
        orchestrator = AIOrchestrator()
        container = orchestrator.initialize_project(f"Task-{task_id[:8]}")
        storage.containers[task_id] = container
        
        # Обновляем прогресс
        storage.active_tasks[task_id].update({
            "progress": 0.2,
            "current_stage": "research"
        })
        await manager.send_progress(task_id, storage.active_tasks[task_id])
        
        # Обрабатываем задачу
        result = await orchestrator.process_task(description)
        
        # Сохраняем контейнер в файл (для persistence)
        save_container_to_file(task_id, container)
        
        # Обновляем финальный статус
        storage.active_tasks[task_id].update({
            "status": result["status"],
            "progress": result.get("progress", 1.0),
            "current_stage": "completed",
            "result": result,
            "completed_at": asyncio.get_event_loop().time()
        })
        
        await manager.send_progress(task_id, storage.active_tasks[task_id])
        logger.info(f"Task {task_id} completed with status: {result['status']}")
        
    except Exception as e:
        logger.error(f"Error processing task {task_id}: {e}")
        
        storage.active_tasks[task_id].update({
            "status": "error",
            "error": str(e),
            "progress": 0.0,
            "current_stage": "failed"
        })
        
        await manager.send_progress(task_id, storage.active_tasks[task_id])

def save_container_to_file(task_id: str, container: Container):
    """Сохраняет контейнер в JSON файл"""
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
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
