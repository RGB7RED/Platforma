#!/usr/bin/env python3
"""
Точка входа для запуска AI Collaboration Platform.
Поддерживает несколько режимов запуска.
"""

import os
import sys
import asyncio
import logging
from pathlib import Path

# Добавляем путь к модулям
sys.path.insert(0, str(Path(__file__).parent))

from app.main import app
from app.telegram_bot import run_bot

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_port() -> int:
    """Return the port the server should bind to."""
    return int(os.getenv("PORT", "8080"))

def get_workers() -> int:
    """Return the number of workers to use for production server."""
    raw_value = os.getenv("WEB_CONCURRENCY", "1")
    try:
        workers = int(raw_value)
    except ValueError:
        logger.warning("Invalid WEB_CONCURRENCY value '%s'; defaulting to 1", raw_value)
        workers = 1
    return max(1, workers)


def log_startup(port: int) -> None:
    """Log a single startup line for process managers."""
    auth_mode = os.getenv("AUTH_MODE", "unset")
    workers = get_workers()
    logger.info(
        "Starting on 0.0.0.0:%s (AUTH_MODE=%s, WORKERS=%s)",
        port,
        auth_mode,
        workers,
    )


async def run_backend():
    """Запуск FastAPI бекенда"""
    import uvicorn

    port = get_port()
    log_startup(port)
    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
        access_log=True
    )
    
    server = uvicorn.Server(config)
    await server.serve()


async def run_all():
    """Запуск всех компонентов"""
    logger.info("Starting all AI Platform components...")
    
    # Запускаем бекенд и бота параллельно
    backend_task = asyncio.create_task(run_backend())
    bot_task = asyncio.create_task(run_bot())
    
    # Ожидаем завершения всех задач
    await asyncio.gather(backend_task, bot_task)


def run_development():
    """Режим разработки"""
    logger.info("Running in development mode...")
    
    # Создаем необходимые директории
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    (data_dir / "tasks").mkdir(exist_ok=True)
    (data_dir / "logs").mkdir(exist_ok=True)
    
    asyncio.run(run_all())


def run_production():
    """Режим production"""
    import uvicorn

    port = get_port()
    workers = get_workers()
    log_startup(port)
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        workers=workers,
        log_level="info"
    )


def run_tests():
    """Запуск тестов"""
    logger.info("Running tests...")
    import subprocess
    
    result = subprocess.run([
        "pytest", "tests/", "-v", 
        "--cov=app", "--cov-report=html",
        "--cov-report=term"
    ], cwd=Path(__file__).parent)
    
    sys.exit(result.returncode)


def show_help():
    """Показать справку"""
    print("""
AI Collaboration Platform - Launch Utility

Usage:
  python run.py [command]

Commands:
  dev        - Run in development mode
  prod       - Run in production mode
  test       - Run tests
  backend    - Run only backend
  bot        - Run only Telegram bot
  all        - Run backend and bot together
  help       - Show this help message

Examples:
  python run.py dev      # Start development server
  python run.py test     # Run all tests
  python run.py prod     # Start production server
    """.strip())


def main():
    """Основная функция"""
    if len(sys.argv) < 2:
        mode = "prod"
    else:
        mode = sys.argv[1].lower()
    
    try:
        if mode == "dev":
            run_development()
        elif mode == "prod":
            run_production()
        elif mode == "test":
            run_tests()
        elif mode == "backend":
            asyncio.run(run_backend())
        elif mode == "bot":
            asyncio.run(run_bot())
        elif mode == "all":
            asyncio.run(run_all())
        elif mode in ["help", "-h", "--help"]:
            show_help()
        else:
            print(f"Unknown mode: {mode}")
            show_help()
            sys.exit(1)
            
    except KeyboardInterrupt:
        logger.info("Shutdown requested...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
