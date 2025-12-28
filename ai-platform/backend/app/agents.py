"""
Модуль ИИ-агентов (заглушки для MVP).
В реальной системе здесь будет интеграция с LLM API.
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Dict, Any, Optional, List, Callable, Sequence

from .models import Container
from . import db
from .llm import (
    LLMProviderError,
    generate_with_retry,
    get_llm_provider,
    load_llm_settings,
)


logger = logging.getLogger(__name__)

DEFAULT_ALLOWED_COMMANDS = {"ruff", "pytest", "python", "python3"}


class BudgetExceededError(RuntimeError):
    """Raised when an API key exceeds daily usage caps."""


class LLMResponseParseError(ValueError):
    """Raised when parsing an LLM response fails."""

    def __init__(self, message: str, *, raw_text: str, error: Optional[str] = None) -> None:
        super().__init__(message)
        self.raw_text = raw_text
        self.error = error

    @property
    def truncated_text(self) -> str:
        return self.raw_text[:2000]


def _parse_int_env(value: Optional[str]) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


class SafeCommandRunner:
    """Run allowlisted commands inside a workspace with timeouts and output limits."""

    def __init__(
        self,
        workspace_path: Path,
        *,
        allowed_commands: Optional[Sequence[str]] = None,
        timeout_seconds: Optional[int] = None,
        max_output_bytes: Optional[int] = None,
        event_handler: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        artifact_handler: Optional[Callable[[str, Dict[str, Any], Optional[str]], Any]] = None,
    ) -> None:
        self.workspace_path = workspace_path.resolve()
        self.allowed_commands = self._resolve_allowed_commands(allowed_commands)
        self.timeout_seconds = timeout_seconds or int(os.getenv("COMMAND_TIMEOUT_SECONDS", "60"))
        self.max_output_bytes = max_output_bytes or int(os.getenv("COMMAND_MAX_OUTPUT_BYTES", "20000"))
        self.event_handler = event_handler
        self.artifact_handler = artifact_handler

    @staticmethod
    def _resolve_allowed_commands(
        allowed_commands: Optional[Sequence[str]],
    ) -> set[str]:
        if allowed_commands:
            return {str(cmd).strip() for cmd in allowed_commands if str(cmd).strip()}
        env_value = os.getenv("ALLOWED_COMMANDS", "")
        if env_value.strip():
            return {cmd.strip() for cmd in env_value.split(",") if cmd.strip()}
        return set(DEFAULT_ALLOWED_COMMANDS)

    @staticmethod
    def _truncate_output(text: str, max_bytes: int) -> tuple[str, bool]:
        data = text.encode("utf-8", errors="replace")
        if len(data) <= max_bytes:
            return text, False
        truncated = data[:max_bytes]
        return truncated.decode("utf-8", errors="replace"), True

    async def _emit_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        if not self.event_handler:
            return
        result = self.event_handler(event_type, payload)
        if asyncio.iscoroutine(result):
            await result

    async def _emit_artifact(
        self,
        artifact_type: str,
        payload: Dict[str, Any],
        produced_by: Optional[str] = None,
    ) -> None:
        if not self.artifact_handler:
            return
        result = self.artifact_handler(artifact_type, payload, produced_by)
        if asyncio.iscoroutine(result):
            await result

    def _is_allowed(self, command: List[str]) -> bool:
        if not command:
            return False
        executable = Path(command[0]).name
        return executable in self.allowed_commands

    def _ensure_workspace(self, cwd: Path) -> None:
        resolved = cwd.resolve()
        if resolved == self.workspace_path:
            return
        if not resolved.is_relative_to(self.workspace_path):
            raise ValueError("Command cwd must stay within workspace")

    async def run(
        self,
        command: List[str],
        *,
        cwd: Optional[Path] = None,
        purpose: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        run_id = str(uuid.uuid4())
        cwd = (cwd or self.workspace_path).resolve()
        self._ensure_workspace(cwd)

        command_line = " ".join(command)
        started_at = datetime.now().isoformat()
        await self._emit_event(
            "command_started",
            {
                "run_id": run_id,
                "command": command_line,
                "cwd": str(cwd),
                "purpose": purpose,
                "started_at": started_at,
            },
        )

        if not self._is_allowed(command):
            finished_at = datetime.now().isoformat()
            result = {
                "ran": False,
                "command": command_line,
                "exit_code": None,
                "stdout": "",
                "stderr": "",
                "duration_seconds": 0.0,
                "timed_out": False,
                "blocked": True,
                "error": "command_not_allowed",
                "stdout_truncated": False,
                "stderr_truncated": False,
                "run_id": run_id,
                "started_at": started_at,
                "finished_at": finished_at,
            }
            await self._emit_event("command_finished", result)
            await self._emit_artifact("command_log", result, produced_by="runner")
            return result

        started_monotonic = time.monotonic()
        stdout = ""
        stderr = ""
        timed_out = False
        exit_code: Optional[int] = None
        error: Optional[str] = None
        try:
            run_env = os.environ.copy()
            if env:
                run_env.update(env)
            completed = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=run_env,
            )
            exit_code = completed.returncode
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            error = "timeout"
        except FileNotFoundError:
            error = "command_not_found"
        except Exception as exc:
            error = str(exc)

        duration = time.monotonic() - started_monotonic
        stdout, stdout_truncated = self._truncate_output(stdout, self.max_output_bytes)
        stderr, stderr_truncated = self._truncate_output(stderr, self.max_output_bytes)
        finished_at = datetime.now().isoformat()

        result = {
            "ran": error is None and not timed_out,
            "command": command_line,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "duration_seconds": duration,
            "timed_out": timed_out,
            "blocked": False,
            "error": error,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "purpose": purpose,
        }
        await self._emit_event("command_finished", result)
        await self._emit_artifact("command_log", result, produced_by="runner")
        return result


class AIAgent:
    """Базовый класс ИИ-агента"""
    
    def __init__(self, codex: Dict[str, Any], role_name: str):
        self.codex = codex
        self.role_name = role_name
        self.rules = codex.get("rules", {}).get(role_name, {})
        
        logger.info(f"Initialized {role_name} agent")
    
    async def execute(self, *args, **kwargs) -> Dict[str, Any]:
        """Основной метод выполнения задачи"""
        raise NotImplementedError("Subclasses must implement execute()")
    
    def _get_role_rules(self) -> Dict[str, Any]:
        """Получить правила для конкретной роли"""
        return self.rules
    
    def _log_action(self, action: str, details: Dict[str, Any]):
        """Логировать действие агента"""
        logger.info(f"{self.role_name}: {action} - {details}")


class AIResearcher(AIAgent):
    """ИИ-исследователь: анализирует задачу и формирует требования"""
    
    def __init__(self, codex: Dict[str, Any]):
        super().__init__(codex, "researcher")
    
    async def execute(self, user_task: str, container: Container) -> Dict[str, Any]:
        """Анализирует задачу пользователя и создает требования"""
        self._log_action("start_research", {"task": user_task[:100]})
        
        # В реальной системе здесь был бы вызов LLM
        # Для MVP создаем фиктивные требования
        
        requirements = {
            "user_task": user_task,
            "analyzed_at": datetime.now().isoformat(),
            "requirements": [
                {
                    "id": "REQ-001",
                    "description": "Система должна предоставлять REST API",
                    "priority": "high",
                    "category": "functional"
                },
                {
                    "id": "REQ-002",
                    "description": "API должен поддерживать CRUD операции",
                    "priority": "high",
                    "category": "functional"
                },
                {
                    "id": "REQ-003",
                    "description": "Должна быть базовая аутентификация",
                    "priority": "medium",
                    "category": "security"
                }
            ],
            "user_stories": [
                "Как пользователь, я хочу создавать новые элементы через API",
                "Как пользователь, я хочу получать список всех элементов",
                "Как пользователь, я хочу обновлять существующие элементы",
                "Как пользователь, я хочу удалять элементы"
            ],
            "assumptions": [
                "Используется Python и FastAPI",
                "Данные хранятся в памяти для MVP",
                "Документация будет в OpenAPI формате"
            ],
            "questions_to_user": [
                "Нужна ли пагинация для списков?",
                "Какие поля должны быть у элементов?",
                "Нужна ли расширенная аутентификация?"
            ],
            "technical_constraints": [
                "Python 3.11+",
                "FastAPI framework",
                "Pydantic для валидации",
                "Uvicorn для сервера"
            ]
        }
        
        # Добавляем артефакты в контейнер
        container.add_artifact(
            "requirements",
            requirements,
            self.role_name
        )
        
        # Создаем файлы с требованиями
        container.add_file(
            "requirements.md",
            self._generate_markdown(requirements)
        )
        
        container.add_file(
            "user_stories.md",
            "## User Stories\n\n" + "\n".join(f"- {story}" for story in requirements["user_stories"])
        )
        
        self._log_action("research_completed", {
            "requirements_count": len(requirements["requirements"]),
            "user_stories_count": len(requirements["user_stories"])
        })
        
        return requirements
    
    def _generate_markdown(self, requirements: Dict[str, Any]) -> str:
        """Генерировать Markdown из требований"""
        md = f"""# Requirements Analysis

## Original Task
{requirements['user_task']}

## Requirements
"""
        
        for req in requirements["requirements"]:
            md += f"\n### {req['id']} ({req['priority'].upper()})\n"
            md += f"{req['description']}\n"
            md += f"*Category: {req['category']}*\n"
        
        md += "\n## User Stories\n"
        for story in requirements["user_stories"]:
            md += f"\n- {story}"
        
        md += "\n\n## Technical Constraints\n"
        for constraint in requirements["technical_constraints"]:
            md += f"\n- {constraint}"
        
        md += "\n\n## Assumptions\n"
        for assumption in requirements["assumptions"]:
            md += f"\n- {assumption}"
        
        md += "\n\n## Questions for Clarification\n"
        for question in requirements["questions_to_user"]:
            md += f"\n- {question}"
        
        md += f"\n\n---\n*Analyzed at: {requirements['analyzed_at']}*"
        
        return md


class AIDesigner(AIAgent):
    """ИИ-проектировщик: создает архитектуру на основе требований"""
    
    def __init__(self, codex: Dict[str, Any]):
        super().__init__(codex, "designer")
    
    async def execute(self, container: Container) -> Dict[str, Any]:
        """Создает архитектурное решение на основе требований"""
        self._log_action("start_design", {})
        
        # Получаем требования из контейнера
        requirements_artifacts = container.artifacts.get("requirements", [])
        if not requirements_artifacts:
            raise ValueError("No requirements found for design")
        
        # Создаем архитектуру (фиктивную для MVP)
        architecture = {
            "name": "Todo REST API",
            "description": "Architecture for a simple todo management API",
            "created_at": datetime.now().isoformat(),
            "components": [
                {
                    "name": "API Layer",
                    "responsibility": "Handle HTTP requests and responses",
                    "technology": "FastAPI",
                    "files": [
                        "main.py",
                        "api/routes.py",
                        "api/dependencies.py",
                        "api/models.py"
                    ],
                    "dependencies": ["Business Logic"],
                    "endpoints": [
                        "GET /todos",
                        "POST /todos",
                        "GET /todos/{id}",
                        "PUT /todos/{id}",
                        "DELETE /todos/{id}"
                    ]
                },
                {
                    "name": "Business Logic",
                    "responsibility": "Implement business rules and workflows",
                    "technology": "Python",
                    "files": [
                        "services/todo_service.py",
                        "models/todo.py"
                    ],
                    "dependencies": ["Data Layer"],
                    "methods": [
                        "create_todo",
                        "get_todos",
                        "get_todo_by_id",
                        "update_todo",
                        "delete_todo"
                    ]
                },
                {
                    "name": "Data Layer",
                    "responsibility": "Handle data storage and retrieval",
                    "technology": "In-memory (MVP), Database (production)",
                    "files": [
                        "repositories/todo_repository.py",
                        "database.py"
                    ],
                    "dependencies": [],
                    "patterns": ["Repository Pattern"]
                },
                {
                    "name": "Testing",
                    "responsibility": "Ensure code quality and correctness",
                    "technology": "pytest",
                    "files": [
                        "tests/test_api.py",
                        "tests/test_services.py",
                        "tests/test_repositories.py",
                        "tests/conftest.py"
                    ],
                    "dependencies": ["API Layer", "Business Logic", "Data Layer"],
                    "coverage_target": 80
                }
            ],
            "api_endpoints": [
                {
                    "method": "GET",
                    "path": "/todos",
                    "description": "Get all todo items",
                    "response_type": "List[Todo]",
                    "authentication": "Optional"
                },
                {
                    "method": "POST",
                    "path": "/todos",
                    "description": "Create a new todo item",
                    "response_type": "Todo",
                    "authentication": "Required"
                },
                {
                    "method": "GET",
                    "path": "/todos/{id}",
                    "description": "Get a specific todo item",
                    "response_type": "Todo",
                    "authentication": "Optional"
                },
                {
                    "method": "PUT",
                    "path": "/todos/{id}",
                    "description": "Update a todo item",
                    "response_type": "Todo",
                    "authentication": "Required"
                },
                {
                    "method": "DELETE",
                    "path": "/todos/{id}",
                    "description": "Delete a todo item",
                    "response_type": "None",
                    "authentication": "Required"
                }
            ],
            "data_model": {
                "Todo": {
                    "id": "int (primary key, auto-increment)",
                    "title": "str (required, max_length=200)",
                    "description": "str (optional, max_length=1000)",
                    "completed": "bool (default: False)",
                    "created_at": "datetime (auto-generated)",
                    "updated_at": "datetime (auto-updated)"
                }
            },
            "dependencies": [
                "fastapi>=0.104.0",
                "uvicorn[standard]>=0.24.0",
                "pydantic>=2.5.0",
                "pytest>=7.4.0"
            ],
            "progress_metrics": {
                "expected_files": 12,
                "required_endpoints": 5,
                "test_coverage_target": 80,
                "success_criteria": ["All tests pass", "API responds correctly"]
            }
        }
        
        # Создаем файлы с архитектурой
        container.add_file(
            "architecture.md",
            self._generate_architecture_md(architecture)
        )
        
        container.add_file(
            "implementation_plan.md",
            self._generate_plan_md(architecture)
        )

        container.target_architecture = architecture
        
        self._log_action("design_completed", {
            "components": len(architecture["components"]),
            "endpoints": len(architecture["api_endpoints"])
        })
        
        return architecture
    
    def _generate_architecture_md(self, architecture: Dict[str, Any]) -> str:
        """Генерировать документацию архитектуры"""
        md = f"""# {architecture['name']}

{architecture['description']}

## Components
"""
        
        for component in architecture["components"]:
            md += f"\n### {component['name']}\n"
            md += f"**Responsibility**: {component['responsibility']}\n"
            md += f"**Technology**: {component['technology']}\n"
            md += f"**Files**: {', '.join(component['files'])}\n"
            md += f"**Dependencies**: {', '.join(component['dependencies']) if component['dependencies'] else 'None'}\n"
        
        md += "\n## API Endpoints\n"
        for endpoint in architecture["api_endpoints"]:
            md += f"\n### `{endpoint['method']} {endpoint['path']}`\n"
            md += f"{endpoint['description']}\n"
            md += f"*Returns: {endpoint['response_type']}*\n"
            md += f"*Authentication: {endpoint['authentication']}*\n"
        
        md += "\n## Data Model\n"
        for model_name, fields in architecture["data_model"].items():
            md += f"\n### {model_name}\n"
            for field_name, field_type in fields.items():
                md += f"- `{field_name}`: {field_type}\n"
        
        md += "\n## Dependencies\n"
        for dep in architecture["dependencies"]:
            md += f"- {dep}\n"
        
        return md
    
    def _generate_plan_md(self, architecture: Dict[str, Any]) -> str:
        """Генерировать план реализации"""
        md = """# Implementation Plan

## Phase 1: Project Setup
1. Initialize project structure and virtual environment
2. Create requirements.txt with dependencies
3. Set up basic FastAPI application structure
4. Configure development tools (linter, formatter)

## Phase 2: Data Layer Implementation
1. Implement data models using Pydantic
2. Create repository pattern for data access
3. Set up in-memory storage (MVP)
4. Add data validation and error handling

## Phase 3: Business Logic Layer
1. Implement service layer with business rules
2. Add input validation and transformation
3. Create unit tests for business logic
4. Implement error handling and logging

## Phase 4: API Layer Implementation
1. Implement REST endpoints according to specification
2. Add request/response models and validation
3. Implement authentication middleware (if required)
4. Add OpenAPI documentation and Swagger UI

## Phase 5: Testing
1. Write comprehensive unit tests
2. Add integration tests for API endpoints
3. Implement test fixtures and mocking
4. Set up test coverage reporting

## Phase 6: Documentation and Polish
1. Generate comprehensive API documentation
2. Write README with setup instructions
3. Add code comments and docstrings
4. Final review and code cleanup

## Success Criteria
- All tests pass with >80% coverage
- API responds correctly to all endpoints
- Code follows PEP8 and best practices
- Documentation is complete and accurate
"""
        return md


class AICoder(AIAgent):
    """ИИ-кодер: реализует код согласно архитектуре"""
    
    def __init__(self, codex: Dict[str, Any]):
        super().__init__(codex, "coder")
        self.files_created = 0
    
    async def execute(
        self,
        task: Dict[str, Any],
        container: Container,
        *,
        correction_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Реализует конкретную задачу кодирования"""
        self._log_action("start_coding", {"task": task})
        
        task_type = task.get("type", "")
        filepath = task.get("file", "")

        settings = load_llm_settings()
        provider = get_llm_provider(settings)
        rules = self._get_role_rules()
        allowed_paths = task.get("allowed_paths") or container.metadata.get("allowed_paths") or []
        if not isinstance(allowed_paths, list):
            allowed_paths = []
        max_files = rules.get("parameters", {}).get("max_files_per_iteration", 5)

        messages = self._build_messages(
            task=task,
            container=container,
            rules=rules,
            allowed_paths=allowed_paths,
            correction_prompt=correction_prompt,
        )

        owner_key_hash = container.metadata.get("owner_key_hash")
        max_tokens_per_day = _parse_int_env(os.getenv("MAX_TOKENS_PER_DAY"))
        max_command_runs_per_day = _parse_int_env(os.getenv("MAX_COMMAND_RUNS_PER_DAY"))
        if owner_key_hash and (max_tokens_per_day > 0 or max_command_runs_per_day > 0):
            usage = await db.get_usage_for_key(owner_key_hash)
            total_tokens = usage.get("tokens_in", 0) + usage.get("tokens_out", 0)
            if max_tokens_per_day > 0 and total_tokens >= max_tokens_per_day:
                raise BudgetExceededError("max_tokens_per_day exceeded")
            if (
                max_command_runs_per_day > 0
                and usage.get("command_runs", 0) >= max_command_runs_per_day
            ):
                raise BudgetExceededError("max_command_runs_per_day exceeded")

        request_started_at = datetime.now().isoformat()
        try:
            response = await generate_with_retry(
                provider,
                messages,
                settings,
                require_json=True,
            )
        except LLMProviderError as exc:
            self._log_action("llm_failed", {"error": str(exc)})
            raise
        request_finished_at = datetime.now().isoformat()

        response_text = response.get("text", "")
        try:
            parsed = self._parse_llm_response(response_text)
        except LLMResponseParseError as exc:
            container.add_artifact(
                "llm_invalid_json",
                {
                    "reason": "llm_invalid_json",
                    "error": exc.error or str(exc),
                    "response_preview": exc.truncated_text,
                },
                self.role_name,
            )
            raise

        files = parsed.get("files", [])
        if isinstance(parsed.get("file"), dict):
            files.append(parsed["file"])
        if parsed.get("content") and filepath:
            files.append({"path": filepath, "content": parsed["content"]})

        if not files:
            raise ValueError("LLM response did not include any files to write.")

        if len(files) > max_files:
            files = files[:max_files]

        new_paths = {
            str(file_entry.get("path") or file_entry.get("file") or "").strip()
            for file_entry in files
        }
        new_paths.discard("")
        all_paths = set(container.files.keys()) | new_paths
        template_id = self._resolve_template_id(container)

        written_files = []
        file_sizes = {}
        for file_entry in files:
            path = str(file_entry.get("path") or file_entry.get("file") or "").strip()
            content = str(file_entry.get("content") or "")
            if not path:
                continue
            self._assert_safe_path(path, allowed_paths)
            content = self._sanitize_fastapi_root_layout(template_id, path, content, all_paths)
            container.add_file(path, content)
            written_files.append(path)
            file_sizes[path] = len(content)

            container.add_artifact(
                "code",
                {
                    "file": path,
                    "task": task,
                    "generated_at": datetime.now().isoformat(),
                    "size": len(content),
                    "lines": len(content.split('\n')),
                },
                self.role_name,
            )

        artifacts = parsed.get("artifacts") or {}
        if not isinstance(artifacts, dict):
            artifacts = {}
        if not artifacts:
            artifacts = {
                "code_summary": f"Updated files: {', '.join(written_files)}",
            }

        usage = response.get("usage", {}) or {}
        tokens_in = int(usage.get("input_tokens", 0) or 0)
        tokens_out = int(usage.get("output_tokens", 0) or 0)
        container.record_llm_usage(
            stage="implementation",
            provider=provider.name,
            model=settings.model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            metadata={"task_type": task_type},
        )

        usage_report = {
            "stage": "implementation",
            "provider": provider.name,
            "model": settings.model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "total_tokens": tokens_in + tokens_out,
            "started_at": request_started_at,
            "finished_at": request_finished_at,
            "task": task.get("description"),
        }
        container.add_artifact("usage_report", usage_report, self.role_name)
        artifact_type = "implementation_plan" if "implementation_plan" in artifacts else "code_summary"
        container.add_artifact(
            artifact_type,
            artifacts.get(artifact_type),
            self.role_name,
        )
        
        self.files_created += 1
        self._log_action("coding_completed", {
            "files": written_files,
            "task": task_type,
            "files_created": self.files_created
        })
        
        primary_file = written_files[0] if written_files else None
        return {
            "file": primary_file,
            "files": written_files,
            "size": file_sizes.get(primary_file, 0),
            "artifact_type": artifact_type,
            "llm_usage": usage_report,
            "usage_report": usage_report,
        }

    def _build_messages(
        self,
        *,
        task: Dict[str, Any],
        container: Container,
        rules: Dict[str, Any],
        allowed_paths: List[str],
        correction_prompt: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        context = container.get_relevant_context("coder")
        task_description = task.get("description", "")
        target_file = task.get("file", "")
        review_report = task.get("review_report")
        review_errors = task.get("review_errors") or task.get("errors")
        review_warnings = task.get("review_warnings") or task.get("warnings")
        constraints = list(rules.get("constraints", []))
        template_id = self._resolve_template_id(container)
        if template_id == "python_fastapi":
            constraints.append(
                "Use root layout with main.py at the repository root. "
                "Do not create an app/ directory. "
                "Only import modules that exist in the generated files; "
                "do not import api.* unless an api/ package is created."
            )
        system_prompt = (
            "You are the Coder agent. Follow the codex rules strictly.\n"
            "Return JSON only with fields: files (list of {path, content}), "
            "artifacts (object with implementation_plan or code_summary).\n"
            "Do not include secrets or API keys in outputs."
        )
        user_payload = {
            "Task": task_description,
            "Type": task.get("type"),
            "Component": task.get("component"),
            "Target file": target_file,
            "Allowed paths": allowed_paths,
            "Existing files": context.get("files", []),
            "Architecture": context.get("architecture"),
            "Recent changes": context.get("recent_changes"),
            "Review report": review_report,
            "Review errors": review_errors,
            "Review warnings": review_warnings,
            "Constraints": constraints,
        }
        user_prompt = f"{json.dumps(user_payload, ensure_ascii=False, indent=2)}"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        if correction_prompt:
            messages.append({"role": "user", "content": correction_prompt})
        return messages

    def _resolve_template_id(self, container: Container) -> Optional[str]:
        template_id = container.metadata.get("template_id")
        if template_id:
            return template_id
        manifest = container.metadata.get("template_manifest")
        if isinstance(manifest, dict):
            return manifest.get("id")
        return None

    def _sanitize_fastapi_root_layout(
        self,
        template_id: Optional[str],
        path: str,
        content: str,
        all_paths: set[str],
    ) -> str:
        if template_id != "python_fastapi":
            return content
        if path not in {"main.py", "app/main.py"}:
            return content
        has_api_module = any(
            candidate == "api.py" or candidate.startswith("api/")
            for candidate in all_paths
        )
        if has_api_module:
            return content
        lines = content.splitlines()
        filtered_lines = []
        removed = False
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith("from api") or stripped.startswith("import api"):
                removed = True
                continue
            if "api_router" in line:
                removed = True
                continue
            filtered_lines.append(line)
        if not removed:
            return content
        sanitized = "\n".join(filtered_lines)
        if content.endswith("\n"):
            sanitized += "\n"
        return sanitized

    def _parse_llm_response(self, text: str) -> Dict[str, Any]:
        """Parse JSON response, handling optional code fences."""
        cleaned = text.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            stripped = self._strip_markdown_fences(cleaned)
            if stripped != cleaned:
                try:
                    return json.loads(stripped)
                except json.JSONDecodeError:
                    pass
            candidate = self._extract_first_json_payload(stripped)
            if candidate:
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError as nested_exc:
                    raise LLMResponseParseError(
                        "llm_invalid_json",
                        raw_text=text,
                        error=str(nested_exc),
                    ) from nested_exc
            raise LLMResponseParseError("llm_invalid_json", raw_text=text, error=str(exc)) from exc

    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        stripped = text.strip()
        if not stripped.startswith("```"):
            return stripped
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()

    @staticmethod
    def _extract_first_json_payload(text: str) -> Optional[str]:
        in_string = False
        escape = False
        start_index: Optional[int] = None
        stack: List[str] = []
        for index, char in enumerate(text):
            if escape:
                escape = False
                continue
            if in_string and char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char in "{[":
                if start_index is None:
                    start_index = index
                stack.append(char)
            elif char in "]}":
                if not stack:
                    continue
                opener = stack.pop()
                if (opener == "{" and char != "}") or (opener == "[" and char != "]"):
                    continue
                if not stack and start_index is not None:
                    return text[start_index : index + 1]
        return None

    def _assert_safe_path(self, path: str, allowed_paths: List[str]) -> None:
        pure_path = PurePosixPath(path)
        if pure_path.is_absolute() or path.startswith("~"):
            raise ValueError(f"Unsafe path rejected: {path}")
        if ".." in pure_path.parts:
            raise ValueError(f"Path traversal rejected: {path}")
        if allowed_paths:
            normalized_allowed = [PurePosixPath(p) for p in allowed_paths if p]
            if normalized_allowed:
                if not any(self._is_path_within(pure_path, allowed) for allowed in normalized_allowed):
                    raise ValueError(f"Path '{path}' not within allowed paths: {allowed_paths}")

    @staticmethod
    def _is_path_within(path: PurePosixPath, base: PurePosixPath) -> bool:
        try:
            path.relative_to(base)
            return True
        except ValueError:
            return False
    
    def _generate_component_code(self, component: str, filepath: str) -> str:
        """Генерировать код компонента"""
        if filepath == "main.py":
            return self._generate_main_py()
        elif filepath == "models/todo.py":
            return self._generate_todo_model()
        elif "service" in filepath:
            return self._generate_service_code(component, filepath)
        elif "repository" in filepath:
            return self._generate_repository_code()
        elif filepath == "api/routes.py":
            return self._generate_api_routes_code()
        elif filepath == "api/dependencies.py":
            return self._generate_api_dependencies_code()
        elif filepath == "api/models.py":
            return self._generate_api_models_code()
        elif "api" in filepath or "routes" in filepath:
            return self._generate_api_routes_code()
        else:
            return f"# Component: {component}\n# File: {filepath}\n\n# Implementation goes here\n"
    
    def _generate_main_py(self) -> str:
        return '''"""
Main FastAPI application for Todo API
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router as api_router

app = FastAPI(
    title="Todo API",
    description="A simple todo management API with CRUD operations",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router, prefix="/api", tags=["api"])

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Todo API",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": [
            {"method": "GET", "path": "/api/todos", "description": "Get all todos"},
            {"method": "POST", "path": "/api/todos", "description": "Create todo"},
            {"method": "GET", "path": "/api/todos/{id}", "description": "Get todo by ID"},
            {"method": "PUT", "path": "/api/todos/{id}", "description": "Update todo"},
            {"method": "DELETE", "path": "/api/todos/{id}", "description": "Delete todo"}
        ]
    }

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return {"status": "healthy", "timestamp": "{{current_time}}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
'''
    
    def _generate_todo_model(self) -> str:
        return '''"""
Todo data models using Pydantic
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class TodoBase(BaseModel):
    """Base model for todo items"""
    title: str = Field(..., min_length=1, max_length=200, description="Title of the todo")
    description: Optional[str] = Field(None, max_length=1000, description="Detailed description")
    completed: bool = Field(False, description="Completion status")


class TodoCreate(TodoBase):
    """Model for creating new todos"""
    pass


class TodoUpdate(BaseModel):
    """Model for updating existing todos"""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    completed: Optional[bool] = None


class Todo(TodoBase):
    """Complete todo model with system fields"""
    id: int = Field(..., description="Unique identifier")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    model_config = ConfigDict(from_attributes=True)
'''
    
    def _generate_service_code(self, component: str, filepath: str) -> str:
        return f'''"""
{component} Service - Business logic layer
"""

from typing import List, Optional
from models.todo import Todo, TodoCreate, TodoUpdate
from repositories.todo_repository import TodoRepository


class TodoService:
    """Service for todo business logic"""
    
    def __init__(self, repository: TodoRepository):
        self.repository = repository
    
    async def get_all_todos(self, skip: int = 0, limit: int = 100) -> List[Todo]:
        """Get all todo items with pagination"""
        return await self.repository.get_all(skip=skip, limit=limit)
    
    async def get_todo_by_id(self, todo_id: int) -> Optional[Todo]:
        """Get a specific todo by ID"""
        return await self.repository.get_by_id(todo_id)
    
    async def create_todo(self, todo_data: TodoCreate) -> Todo:
        """Create a new todo item"""
        # Business logic validation
        if not todo_data.title.strip():
            raise ValueError("Todo title cannot be empty")
        
        return await self.repository.create(todo_data)
    
    async def update_todo(self, todo_id: int, todo_data: TodoUpdate) -> Optional[Todo]:
        """Update an existing todo item"""
        # Check if todo exists
        existing_todo = await self.repository.get_by_id(todo_id)
        if not existing_todo:
            return None
        
        # Business logic: Validate update data
        if todo_data.title is not None and not todo_data.title.strip():
            raise ValueError("Todo title cannot be empty")
        
        return await self.repository.update(todo_id, todo_data)
    
    async def delete_todo(self, todo_id: int) -> bool:
        """Delete a todo item"""
        return await self.repository.delete(todo_id)
    
    async def search_todos(self, query: str) -> List[Todo]:
        """Search todos by title or description"""
        return await self.repository.search(query)
'''
    
    def _generate_repository_code(self) -> str:
        return '''"""
Todo repository - Data access layer
"""

from typing import List, Optional
from datetime import datetime

from models.todo import Todo, TodoCreate, TodoUpdate


class TodoRepository:
    """Repository for todo data access with in-memory storage"""
    
    def __init__(self):
        self._todos = {}
        self._next_id = 1
    
    async def get_all(self, skip: int = 0, limit: int = 100) -> List[Todo]:
        """Get all todos with pagination"""
        todos = list(self._todos.values())
        return todos[skip:skip + limit]
    
    async def get_by_id(self, todo_id: int) -> Optional[Todo]:
        """Get todo by ID"""
        return self._todos.get(todo_id)
    
    async def create(self, todo_data: TodoCreate) -> Todo:
        """Create a new todo"""
        now = datetime.now()
        todo = Todo(
            id=self._next_id,
            title=todo_data.title,
            description=todo_data.description,
            completed=todo_data.completed,
            created_at=now,
            updated_at=now
        )
        
        self._todos[self._next_id] = todo
        self._next_id += 1
        return todo
    
    async def update(self, todo_id: int, todo_data: TodoUpdate) -> Optional[Todo]:
        """Update an existing todo"""
        todo = self._todos.get(todo_id)
        if not todo:
            return None
        
        update_data = todo_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(todo, field, value)
        
        todo.updated_at = datetime.now()
        return todo
    
    async def delete(self, todo_id: int) -> bool:
        """Delete a todo"""
        if todo_id in self._todos:
            del self._todos[todo_id]
            return True
        return False
    
    async def search(self, query: str) -> List[Todo]:
        """Search todos by title or description"""
        if not query:
            return []
        
        query = query.lower()
        results = []
        
        for todo in self._todos.values():
            if (todo.title and query in todo.title.lower()) or \
               (todo.description and query in todo.description.lower()):
                results.append(todo)
        
        return results
    
    async def count(self) -> int:
        """Get total count of todos"""
        return len(self._todos)
'''
    
    def _generate_api_code(self) -> str:
        return self._generate_api_routes_code()

    def _generate_api_routes_code(self) -> str:
        return '''"""
API routes for todo management
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query

from models.todo import Todo, TodoCreate, TodoUpdate
from services.todo_service import TodoService

from api.dependencies import get_todo_service

router = APIRouter()


@router.get("/todos", response_model=List[Todo])
async def get_todos(
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of items to return"),
    service: TodoService = Depends(get_todo_service)
):
    """Get all todo items with pagination"""
    return await service.get_all_todos(skip=skip, limit=limit)


@router.get("/todos/{todo_id}", response_model=Todo)
async def get_todo(
    todo_id: int,
    service: TodoService = Depends(get_todo_service)
):
    """Get a specific todo item by ID"""
    todo = await service.get_todo_by_id(todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


@router.post("/todos", response_model=Todo, status_code=201)
async def create_todo(
    todo_data: TodoCreate,
    service: TodoService = Depends(get_todo_service)
):
    """Create a new todo item"""
    try:
        return await service.create_todo(todo_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/todos/{todo_id}", response_model=Todo)
async def update_todo(
    todo_id: int,
    todo_data: TodoUpdate,
    service: TodoService = Depends(get_todo_service)
):
    """Update an existing todo item"""
    todo = await service.update_todo(todo_id, todo_data)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


@router.delete("/todos/{todo_id}", status_code=204)
async def delete_todo(
    todo_id: int,
    service: TodoService = Depends(get_todo_service)
):
    """Delete a todo item"""
    success = await service.delete_todo(todo_id)
    if not success:
        raise HTTPException(status_code=404, detail="Todo not found")


@router.get("/todos/search", response_model=List[Todo])
async def search_todos(
    query: str = Query(..., min_length=1, description="Search query"),
    service: TodoService = Depends(get_todo_service)
):
    """Search todos by title or description"""
    return await service.search_todos(query)
'''

    def _generate_api_dependencies_code(self) -> str:
        return '''"""
API dependencies for todo management
"""

from fastapi import Depends, HTTPException

from repositories.todo_repository import TodoRepository
from services.todo_service import TodoService


def get_todo_repository() -> TodoRepository:
    """Dependency for getting todo repository instance"""
    return TodoRepository()


def get_todo_service(
    repository: TodoRepository = Depends(get_todo_repository)
) -> TodoService:
    """Dependency for getting todo service instance"""
    try:
        return TodoService(repository)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
'''

    def _generate_api_models_code(self) -> str:
        return '''"""
API schemas for todo management
"""

from models.todo import Todo, TodoCreate, TodoUpdate

__all__ = ["Todo", "TodoCreate", "TodoUpdate"]
'''
    
    def _generate_test_code(self, filepath: str) -> str:
        if "test_api" in filepath:
            return self._generate_api_tests()
        elif "test_services" in filepath:
            return self._generate_service_tests()
        elif "conftest" in filepath:
            return self._generate_conftest()
        else:
            return f'''"""
Tests for {filepath}
"""

import pytest


def test_placeholder():
    """Placeholder test"""
    assert True


class TestExample:
    """Example test class"""
    
    def test_example(self):
        """Example test method"""
        assert 1 + 1 == 2
'''
    
    def _generate_api_tests(self) -> str:
        return '''"""
API tests for Todo endpoints
"""

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


class TestTodoAPI:
    """Test suite for Todo API endpoints"""
    
    def test_root_endpoint(self):
        """Test root endpoint returns API info"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert data["message"] == "Todo API"
        assert "endpoints" in data
    
    def test_get_todos_empty(self):
        """Test getting todos when database is empty"""
        response = client.get("/api/todos")
        assert response.status_code == 200
        assert response.json() == []
    
    def test_create_todo_success(self):
        """Test successful todo creation"""
        todo_data = {"title": "Test todo", "description": "Test description"}
        response = client.post("/api/todos", json=todo_data)
        assert response.status_code == 201
        
        todo = response.json()
        assert todo["title"] == todo_data["title"]
        assert todo["description"] == todo_data["description"]
        assert todo["completed"] == False
        assert "id" in todo
        assert "created_at" in todo
    
    def test_create_todo_invalid(self):
        """Test todo creation with invalid data"""
        # Empty title
        response = client.post("/api/todos", json={"title": ""})
        assert response.status_code == 400
        
        # Missing title
        response = client.post("/api/todos", json={"description": "No title"})
        assert response.status_code == 422  # Pydantic validation error
    
    def test_get_todo_by_id(self):
        """Test getting a specific todo by ID"""
        # First create a todo
        create_response = client.post("/api/todos", json={"title": "Test"})
        todo_id = create_response.json()["id"]
        
        # Get by ID
        response = client.get(f"/api/todos/{todo_id}")
        assert response.status_code == 200
        assert response.json()["id"] == todo_id
    
    def test_get_nonexistent_todo(self):
        """Test getting a todo that doesn't exist"""
        response = client.get("/api/todos/99999")
        assert response.status_code == 404
    
    def test_update_todo(self):
        """Test updating a todo"""
        # Create todo
        create_response = client.post("/api/todos", json={"title": "Original"})
        todo_id = create_response.json()["id"]
        
        # Update
        update_data = {"title": "Updated", "completed": True}
        response = client.put(f"/api/todos/{todo_id}", json=update_data)
        assert response.status_code == 200
        
        updated_todo = response.json()
        assert updated_todo["title"] == "Updated"
        assert updated_todo["completed"] == True
    
    def test_delete_todo(self):
        """Test deleting a todo"""
        # Create todo
        create_response = client.post("/api/todos", json={"title": "To delete"})
        todo_id = create_response.json()["id"]
        
        # Delete
        response = client.delete(f"/api/todos/{todo_id}")
        assert response.status_code == 204
        
        # Verify deletion
        response = client.get(f"/api/todos/{todo_id}")
        assert response.status_code == 404
    
    def test_search_todos(self):
        """Test searching todos"""
        # Create test todos
        client.post("/api/todos", json={"title": "Buy groceries", "description": "Milk and eggs"})
        client.post("/api/todos", json={"title": "Call mom", "description": "Weekly call"})
        
        # Search
        response = client.get("/api/todos/search?query=grocery")
        assert response.status_code == 200
        results = response.json()
        assert len(results) > 0
        assert any("grocery" in todo["title"].lower() for todo in results)
'''
    
    def _generate_service_tests(self) -> str:
        return '''"""
Service layer tests
"""

import pytest
from models.todo import TodoCreate, TodoUpdate
from services.todo_service import TodoService
from repositories.todo_repository import TodoRepository


@pytest.fixture
def todo_service():
    """Create todo service for testing"""
    repository = TodoRepository()
    return TodoService(repository)


class TestTodoService:
    """Test suite for TodoService"""
    
    @pytest.mark.asyncio
    async def test_create_and_get_todo(self, todo_service):
        """Test creating and getting a todo"""
        todo_data = TodoCreate(title="Test todo")
        created_todo = await todo_service.create_todo(todo_data)
        
        assert created_todo.id is not None
        assert created_todo.title == "Test todo"
        assert created_todo.completed == False
        
        retrieved_todo = await todo_service.get_todo_by_id(created_todo.id)
        assert retrieved_todo is not None
        assert retrieved_todo.id == created_todo.id
    
    @pytest.mark.asyncio
    async def test_create_todo_invalid_title(self, todo_service):
        """Test creating todo with invalid title"""
        with pytest.raises(ValueError):
            await todo_service.create_todo(TodoCreate(title=""))
    
    @pytest.mark.asyncio
    async def test_get_all_todos(self, todo_service):
        """Test getting all todos"""
        await todo_service.create_todo(TodoCreate(title="Todo 1"))
        await todo_service.create_todo(TodoCreate(title="Todo 2"))
        
        todos = await todo_service.get_all_todos()
        assert len(todos) == 2
        assert todos[0].title == "Todo 1"
        assert todos[1].title == "Todo 2"
    
    @pytest.mark.asyncio
    async def test_get_all_todos_pagination(self, todo_service):
        """Test pagination for getting todos"""
        for i in range(15):
            await todo_service.create_todo(TodoCreate(title=f"Todo {i}"))
        
        # First page
        page1 = await todo_service.get_all_todos(skip=0, limit=10)
        assert len(page1) == 10
        
        # Second page
        page2 = await todo_service.get_all_todos(skip=10, limit=10)
        assert len(page2) == 5
    
    @pytest.mark.asyncio
    async def test_update_todo(self, todo_service):
        """Test updating a todo"""
        todo = await todo_service.create_todo(TodoCreate(title="Original"))
        
        update_data = TodoUpdate(title="Updated", completed=True)
        updated_todo = await todo_service.update_todo(todo.id, update_data)
        
        assert updated_todo is not None
        assert updated_todo.title == "Updated"
        assert updated_todo.completed == True
    
    @pytest.mark.asyncio
    async def test_update_nonexistent_todo(self, todo_service):
        """Test updating a todo that doesn't exist"""
        update_data = TodoUpdate(title="Updated")
        result = await todo_service.update_todo(9999, update_data)
        assert result is None
    
    @pytest.mark.asyncio
    async def test_delete_todo(self, todo_service):
        """Test deleting a todo"""
        todo = await todo_service.create_todo(TodoCreate(title="To delete"))
        
        result = await todo_service.delete_todo(todo.id)
        assert result == True
        
        deleted_todo = await todo_service.get_todo_by_id(todo.id)
        assert deleted_todo is None
    
    @pytest.mark.asyncio
    async def test_delete_nonexistent_todo(self, todo_service):
        """Test deleting a todo that doesn't exist"""
        result = await todo_service.delete_todo(9999)
        assert result == False
    
    @pytest.mark.asyncio
    async def test_search_todos(self, todo_service):
        """Test searching todos"""
        await todo_service.create_todo(TodoCreate(title="Buy groceries", description="Milk and eggs"))
        await todo_service.create_todo(TodoCreate(title="Call mom", description="Weekly call"))
        
        results = await todo_service.search_todos("grocery")
        assert len(results) == 1
        assert "grocery" in results[0].title.lower()
        
        results = await todo_service.search_todos("call")
        assert len(results) == 1
        assert "call" in results[0].title.lower()
        
        results = await todo_service.search_todos("")
        assert len(results) == 0
'''
    
    def _generate_conftest(self) -> str:
        return '''"""
Shared pytest fixtures and configuration
"""

import pytest
import asyncio
from typing import AsyncGenerator

from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def client() -> TestClient:
    """Test client for FastAPI app"""
    return TestClient(app)


@pytest.fixture
def sample_todo_data():
    """Sample todo data for testing"""
    return {
        "title": "Test Todo",
        "description": "Test description",
        "completed": False
    }


@pytest.fixture
def sample_todo_update():
    """Sample todo update data for testing"""
    return {
        "title": "Updated Todo",
        "completed": True
    }
'''


class AIReviewer(AIAgent):
    """ИИ-ревьюер: проверяет качество и соответствие"""
    
    def __init__(self, codex: Dict[str, Any]):
        super().__init__(codex, "reviewer")
    
    async def execute(
        self,
        container: Container,
        *,
        workspace_path: Optional[Path] = None,
        command_runner: Optional[SafeCommandRunner] = None,
    ) -> Dict[str, Any]:
        """Проверяет текущее состояние контейнера"""
        self._log_action("start_review", {})
        
        # Получаем правила ревью из кодекса
        rules = self._get_role_rules()
        checklist = rules.get("checklist", [
            "Соответствует ли PEP8?",
            "Есть ли тесты?",
            "Соответствует ли архитектуре?",
            "Нет ли нарушений кодекса?"
        ])
        template_id = self._resolve_template_id(container)
        
        issues = []
        warnings = []
        passed_checks = []

        # Проверяем файлы
        for filepath, content in container.files.items():
            file_issues, file_warnings, file_passed = self._review_file(filepath, content)
            issues.extend(file_issues)
            warnings.extend(file_warnings)
            passed_checks.extend(file_passed)

        # Проверяем соответствие архитектуре
        if container.target_architecture and not self._skip_architecture_compliance(template_id):
            arch_issues, arch_warnings = self._check_architecture_compliance(container)
            issues.extend(arch_issues)
            warnings.extend(arch_warnings)

        # Проверяем наличие тестов
        test_files = [f for f in container.files.keys() if 'test' in f.lower()]
        if not test_files:
            warnings.append("No test files found")
        else:
            passed_checks.append(f"Found {len(test_files)} test files")

        # Проверяем прогресс
        if container.progress < 0.5 and len(container.history) > 10:
            warnings.append(f"Low progress ({container.progress:.0%}) after {len(container.history)} iterations")

        # Проверяем наличие документации
        doc_files = [f for f in container.files.keys() if f.endswith('.md')]
        if not doc_files:
            warnings.append("No documentation files found")
        else:
            passed_checks.append(f"Found {len(doc_files)} documentation files")

        self._apply_template_checks(
            template_id,
            container,
            issues,
            warnings,
            passed_checks,
        )

        ruff_report = {
            "ran": False,
            "command": None,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
        }
        pytest_report = {
            "ran": False,
            "command": None,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
        }
        tool_warnings: List[str] = []
        tool_errors: List[str] = []

        compileall_report = {
            "ran": False,
            "command": None,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
        }
        if container.files:
            if workspace_path is None:
                with tempfile.TemporaryDirectory() as workspace:
                    workspace_path = Path(workspace)
                    self._write_container_files(workspace_path, container.files)
                    runner = command_runner or SafeCommandRunner(workspace_path)
                    (
                        ruff_report,
                        pytest_report,
                        compileall_report,
                        tool_warnings,
                        tool_errors,
                    ) = await self._run_quality_checks(
                        workspace_path,
                        container.files,
                        runner,
                    )
            else:
                self._write_container_files(workspace_path, container.files)
                runner = command_runner or SafeCommandRunner(workspace_path)
                (
                    ruff_report,
                    pytest_report,
                    compileall_report,
                    tool_warnings,
                    tool_errors,
                ) = await self._run_quality_checks(
                    workspace_path,
                    container.files,
                    runner,
                )
        else:
            tool_warnings.append("No files available for quality checks")

        warnings.extend(tool_warnings)
        errors = issues + tool_errors

        timed_out = any(
            report.get("timed_out")
            for report in (ruff_report, pytest_report, compileall_report)
            if isinstance(report, dict)
        )
        passed = len(errors) == 0 and not timed_out
        if passed and warnings:
            status = "approved_with_warnings"
            message = f"Approved with {len(warnings)} warnings"
        elif passed:
            status = "approved"
            message = "All checks passed"
        else:
            status = "rejected"
            message = f"Found {len(errors)} critical issues"

        review_result = {
            "status": status,
            "passed": passed,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "issues": issues,
            "warnings": warnings,
            "errors": errors,
            "passed_checks": passed_checks,
            "files_reviewed": len(container.files),
            "checklist_used": checklist,
            "ruff": ruff_report,
            "pytest": pytest_report,
            "compileall": compileall_report,
            "command_timeout": timed_out,
            "summary": {
                "total_files": len(container.files),
                "total_issues": len(issues),
                "total_warnings": len(warnings),
                "test_coverage": f"{len(test_files)}/{len(container.files)} files",
                "progress": container.progress,
            },
        }

        # Добавляем артефакт ревью
        container.add_artifact(
            "review_report",
            review_result,
            self.role_name
        )

        self._log_action("review_completed", {
            "status": status,
            "issues": len(errors),
            "warnings": len(warnings),
            "passed_checks": len(passed_checks)
        })

        return review_result

    def _resolve_template_id(self, container: Container) -> Optional[str]:
        template_id = container.metadata.get("template_id")
        if template_id:
            return template_id
        manifest = container.metadata.get("template_manifest")
        if isinstance(manifest, dict):
            return manifest.get("id")
        return None

    def _skip_architecture_compliance(self, template_id: Optional[str]) -> bool:
        return template_id in {"python_cli", "python_fastapi"}

    def _apply_template_checks(
        self,
        template_id: Optional[str],
        container: Container,
        issues: List[str],
        warnings: List[str],
        passed_checks: List[str],
    ) -> None:
        if template_id == "python_cli":
            if not self._has_readme(container.files):
                issues.append("README.md is required for python_cli template")
            else:
                passed_checks.append("README.md found")
            return
        if template_id == "python_fastapi":
            missing_deps = self._missing_requirements(
                container.files,
                ("fastapi", "uvicorn[standard]", "pydantic"),
            )
            if missing_deps:
                issues.append(
                    "Missing FastAPI dependencies in requirements.txt: "
                    + ", ".join(missing_deps)
                )
            else:
                passed_checks.append("FastAPI dependencies present in requirements.txt")
            if not self._has_fastapi_app(container.files):
                issues.append("FastAPI app instance not found")
            if not self._has_fastapi_routes(container.files):
                warnings.append("No FastAPI routes detected")
            if not self._has_health_endpoint(container.files):
                issues.append("Missing /health endpoint for FastAPI template")
            else:
                passed_checks.append("Health endpoint found")

    def _has_readme(self, files: Dict[str, str]) -> bool:
        for filepath in files.keys():
            if Path(filepath).name.lower() == "readme.md":
                return True
        return False

    def _missing_requirements(self, files: Dict[str, str], deps: tuple[str, ...]) -> List[str]:
        requirements = files.get("requirements.txt", "")
        missing = []
        for dep in deps:
            if dep not in requirements:
                missing.append(dep)
        return missing

    def _iter_python_files(self, files: Dict[str, str]) -> List[str]:
        return [content for name, content in files.items() if name.endswith(".py")]

    def _has_fastapi_app(self, files: Dict[str, str]) -> bool:
        for content in self._iter_python_files(files):
            if "FastAPI" in content and "FastAPI(" in content:
                return True
        return False

    def _has_fastapi_routes(self, files: Dict[str, str]) -> bool:
        for content in self._iter_python_files(files):
            if "@app." in content or "include_router" in content:
                return True
        return False

    def _has_health_endpoint(self, files: Dict[str, str]) -> bool:
        for content in self._iter_python_files(files):
            if '"/health"' in content or "'/health'" in content:
                return True
        return False
    
    def _review_file(self, filepath: str, content: str):
        """Проверить конкретный файл"""
        issues = []
        warnings = []
        passed = []
        
        lines = content.split('\n')
        
        # Проверка длины строк
        long_lines = []
        for i, line in enumerate(lines, 1):
            if len(line) > 120:
                long_lines.append((i, len(line)))
        
        if long_lines:
            line_info = ", ".join(
                f"line {index}({length} chars)" for index, length in long_lines[:3]
            )
            if len(long_lines) > 3:
                line_info += f" and {len(long_lines)-3} more"
            warnings.append(f"{filepath}: Lines too long: {line_info}")
        else:
            passed.append(f"{filepath}: All lines within 120 characters")
        
        # Проверка на наличие документации
        if filepath.endswith('.py'):
            # Проверка module docstring
            has_module_doc = False
            for line in lines[:5]:
                if line.strip().startswith(('"""', "'''")):
                    has_module_doc = True
                    break
            
            if not has_module_doc:
                warnings.append(f"{filepath}: Missing module docstring")
            else:
                passed.append(f"{filepath}: Has module docstring")
            
            # Проверка функций/классов
            for i, line in enumerate(lines):
                if line.strip().startswith(('def ', 'class ')):
                    # Проверяем следующую строку на docstring
                    if i + 1 < len(lines):
                        next_line = lines[i + 1].strip()
                        if not (next_line.startswith(('"""', "'''")) or 
                               (i + 2 < len(lines) and lines[i + 2].strip().startswith(('"""', "'''")))):
                            function_name = line.strip().split()[1].split('(')[0]
                            warnings.append(f"{filepath}:{i+1}: Function/class '{function_name}' missing docstring")
        
        # Проверка на синтаксические ошибки
        if filepath.endswith('.py'):
            try:
                compile(content, filepath, 'exec')
                passed.append(f"{filepath}: No syntax errors")
            except SyntaxError as e:
                issues.append(f"{filepath}: Syntax error - {e.msg} at line {e.lineno}")
        
        # Проверка импортов
        if filepath.endswith('.py'):
            import_lines = [line for line in lines if line.strip().startswith(('import ', 'from '))]
            if import_lines:
                passed.append(f"{filepath}: Has {len(import_lines)} import statements")
        
        return issues, warnings, passed

    async def _run_quality_checks(
        self,
        workspace_path: Path,
        files: Dict[str, str],
        command_runner: SafeCommandRunner,
    ) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[str], List[str]]:
        ruff_report = {
            "ran": False,
            "command": None,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
        }
        pytest_report = {
            "ran": False,
            "command": None,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
        }
        compileall_report = {
            "ran": False,
            "command": None,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
        }
        warnings: List[str] = []
        errors: List[str] = []

        python_files = [name for name in files.keys() if name.endswith(".py")]
        if python_files:
            if shutil.which("ruff"):
                self._write_container_files(workspace_path, files)
                ruff_report = await command_runner.run(
                    ["ruff", "check", "."],
                    cwd=workspace_path,
                    purpose="ruff",
                )
                if ruff_report.get("error"):
                    errors.append(f"ruff error: {ruff_report['error']}")
                elif ruff_report["exit_code"] != 0:
                    warnings.append(f"ruff reported issues (exit code {ruff_report['exit_code']})")
            else:
                errors.append("ruff executable not found")
            self._write_container_files(workspace_path, files)
            compileall_report = await command_runner.run(
                [sys.executable, "-m", "compileall", "."],
                cwd=workspace_path,
                purpose="compileall",
            )
            if compileall_report.get("error"):
                errors.append(f"compileall error: {compileall_report['error']}")
            elif compileall_report["exit_code"] not in (0, None):
                errors.append(f"compileall failed with exit code {compileall_report['exit_code']}")
        else:
            warnings.append("Ruff skipped: no python files found")
            warnings.append("Compileall skipped: no python files found")

        if self._has_tests(files):
            if shutil.which("pytest"):
                self._write_container_files(workspace_path, files)
                pytest_report = await command_runner.run(
                    [sys.executable, "-m", "pytest", "-q"],
                    cwd=workspace_path,
                    purpose="pytest",
                    env={"PYTHONPATH": str(workspace_path)},
                )
                if pytest_report.get("error"):
                    errors.append(f"pytest error: {pytest_report['error']}")
                elif pytest_report["exit_code"] != 0:
                    errors.append(f"pytest failed with exit code {pytest_report['exit_code']}")
            else:
                errors.append("pytest executable not found")
        else:
            warnings.append("Pytest skipped: no tests found")

        return ruff_report, pytest_report, compileall_report, warnings, errors

    def _has_tests(self, files: Dict[str, str]) -> bool:
        for filepath in files.keys():
            path = Path(filepath)
            if path.suffix != ".py":
                continue
            if path.name.startswith("test_") or path.name.endswith("_test.py") or "tests" in path.parts:
                return True
        return False

    def _write_container_files(self, workspace_path: Path, files: Dict[str, str]) -> None:
        for filepath, content in files.items():
            target_path = self._resolve_workspace_path(workspace_path, filepath)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, (bytes, bytearray)):
                target_path.write_bytes(bytes(content))
            else:
                target_path.write_text(str(content), encoding="utf-8")

    def _resolve_workspace_path(self, workspace_path: Path, filepath: str) -> Path:
        pure_path = PurePosixPath(filepath)
        if pure_path.is_absolute() or ".." in pure_path.parts:
            raise ValueError(f"Unsafe path rejected: {filepath}")
        return workspace_path / pure_path
    
    def _check_architecture_compliance(self, container: Container):
        """Проверить соответствие архитектуре"""
        issues = []
        warnings = []
        
        if not container.target_architecture:
            return issues, warnings
        
        arch = container.target_architecture
        
        # Проверяем наличие всех компонентов
        if "components" in arch:
            for component in arch["components"]:
                component_name = component.get("name", "")
                expected_files = component.get("files", [])
                
                missing_files = []
                for expected_file in expected_files:
                    if expected_file not in container.files:
                        missing_files.append(expected_file)
                
                if missing_files:
                    issues.append(
                        f"Missing {len(missing_files)} files from {component_name}: {', '.join(missing_files[:3])}"
                    )
                else:
                    warnings.append(f"Component '{component_name}' has all required files")
        
        # Проверяем зависимости
        if "dependencies" in arch:
            requirements_file = "requirements.txt"
            if requirements_file in container.files:
                content = container.files[requirements_file]
                for dep in arch["dependencies"]:
                    dep_name = dep.split('>')[0].split('=')[0].strip()
                    if dep_name not in content:
                        warnings.append(f"Dependency '{dep_name}' not found in requirements.txt")
        
        return issues, warnings


if __name__ == "__main__":
    # Тестирование агентов
    import asyncio
    
    async def test_agents():
        # Загружаем кодекс
        codex = {
            "version": "1.0.0-test",
            "rules": {
                "researcher": {"max_questions": 3},
                "reviewer": {"checklist": ["test1", "test2"]}
            }
        }
        
        container = Container()
        
        # Тестируем исследователя
        researcher = AIResearcher(codex)
        result = await researcher.execute("Create a todo API", container)
        print(f"Researcher created {len(result['requirements'])} requirements")
        
        # Тестируем проектировщика
        designer = AIDesigner(codex)
        architecture = await designer.execute(container)
        print(f"Designer created architecture with {len(architecture['components'])} components")
        
        # Тестируем кодера
        coder = AICoder(codex)
        task = {"type": "implement_component", "component": "API", "file": "main.py"}
        code_result = await coder.execute(task, container)
        print(f"Coder created file: {code_result['file']} ({code_result['size']} bytes)")
        
        # Тестируем ревьюера
        reviewer = AIReviewer(codex)
        review = await reviewer.execute(container)
        print(f"Review status: {review['status']}")
        print(f"Review issues: {len(review['issues'])}")
        print(f"Review warnings: {len(review['warnings'])}")
    
    asyncio.run(test_agents())
