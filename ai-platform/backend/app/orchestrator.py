"""
Оркестратор - управляет полным циклом выполнения задачи через роли ИИ.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime

from .models import Container, ProjectState
from .logging_utils import configure_logging
from .agents import AIResearcher, AIDesigner, AICoder, AIReviewer, BudgetExceededError
from .llm import LLMProviderError


configure_logging()
logger = logging.getLogger(__name__)


class AIOrchestrator:
    """Главный оркестратор, управляющий циклом ИИ-ролей"""
    
    def __init__(self, codex_path: Optional[str] = None):
        self.codex_path = self._resolve_codex_path(codex_path)
        self.codex = self._load_codex(self.codex_path)
        self.codex_hash = self._hash_codex(self.codex)
        self.container: Optional[Container] = None
        self.roles = {}
        self.task_history: List[Dict] = []
        
        logger.info(f"Orchestrator initialized with Codex v{self.codex.get('version', 'unknown')}")
    
    def _resolve_codex_path(self, codex_path: Optional[str]) -> Path:
        if codex_path:
            return Path(codex_path)
        env_path = os.getenv("CODEX_PATH")
        if env_path:
            return Path(env_path)
        return Path(__file__).with_name("codex.json")

    def _load_codex(self, codex_path: Optional[Path]) -> Dict[str, Any]:
        """Загрузить кодекс из файла или использовать дефолтный"""
        if codex_path and codex_path.exists():
            try:
                with open(codex_path, 'r', encoding='utf-8') as f:
                    codex = json.load(f)
                if self._validate_codex(codex):
                    return codex
                logger.error("Codex schema validation failed, using defaults")
            except Exception as e:
                logger.error(f"Error loading codex: {e}")
        
        # Дефолтный кодекс
        return {
            "version": "1.0.0-default",
            "rules": {
                "researcher": {"max_questions": 3},
                "coder": {"testing_required": True}
            },
            "workflow": {
                "stages": ["research", "design", "implementation", "review"],
                "max_iterations": 15,
                "require_review": True,
                "review_required": True
            }
        }

    def _validate_codex(self, codex: Any) -> bool:
        if not isinstance(codex, dict):
            return False
        if not isinstance(codex.get("version"), str):
            return False
        rules = codex.get("rules")
        workflow = codex.get("workflow")
        if not isinstance(rules, dict) or not isinstance(workflow, dict):
            return False
        stages = workflow.get("stages")
        if not isinstance(stages, list) or not stages:
            return False
        max_iterations = workflow.get("max_iterations")
        if max_iterations is not None and (not isinstance(max_iterations, int) or max_iterations <= 0):
            return False
        require_review = workflow.get("require_review")
        review_required = workflow.get("review_required")
        if require_review is not None and not isinstance(require_review, bool):
            return False
        if review_required is not None and not isinstance(review_required, bool):
            return False
        return True

    def _hash_codex(self, codex: Dict[str, Any]) -> str:
        payload = json.dumps(codex, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _codex_summary(self) -> Dict[str, Any]:
        workflow = self.codex.get("workflow", {})
        rules = self.codex.get("rules", {})
        review_required = workflow.get("review_required", workflow.get("require_review", True))
        return {
            "workflow_stages": workflow.get("stages", []),
            "max_iterations": workflow.get("max_iterations"),
            "review_required": review_required,
            "roles": sorted(rules.keys()),
        }
    
    def initialize_project(self, project_name: str) -> Container:
        """Инициализировать новый проект"""
        self.container = Container()
        self.container.metadata["project_name"] = project_name
        self.container.metadata["started_at"] = datetime.now().isoformat()
        self.container.metadata["codex_version"] = self.codex.get("version")
        self.container.metadata["codex_hash"] = self.codex_hash
        max_iterations = self.codex.get("workflow", {}).get("max_iterations")
        if isinstance(max_iterations, int):
            self.container.metadata["max_iterations"] = max_iterations
        
        # Инициализация ролей
        self._ensure_roles()
        
        logger.info(f"Project '{project_name}' initialized with ID: {self.container.project_id}")
        return self.container

    def attach_container(self, container: Container) -> None:
        """Attach an existing container for resuming work."""
        self.container = container
        self._ensure_roles()

    def _ensure_roles(self) -> None:
        if self.roles:
            return
        self.roles = {
            "researcher": AIResearcher(self.codex),
            "designer": AIDesigner(self.codex),
            "coder": AICoder(self.codex),
            "reviewer": AIReviewer(self.codex),
        }

    def _sanitize_question_id(self, text: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", text.strip().lower()).strip("_")
        return normalized or str(uuid.uuid4())

    def _plan_clarification_questions(
        self,
        user_task: str,
        *,
        template_manifest: Optional[Dict[str, Any]] = None,
        provided_answers: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        rules = self.codex.get("rules", {})
        max_questions = (
            rules.get("researcher", {}).get("parameters", {}).get("max_questions")
            or 3
        )
        questions: List[Dict[str, Any]] = []
        answers = provided_answers or {}

        manifest_questions = []
        if isinstance(template_manifest, dict):
            manifest_questions = template_manifest.get("clarification_questions") or []
        if isinstance(manifest_questions, list):
            for entry in manifest_questions:
                if not isinstance(entry, dict):
                    continue
                question_id = entry.get("id") or self._sanitize_question_id(entry.get("text", ""))
                if answers.get(question_id):
                    continue
                questions.append(
                    {
                        "id": question_id,
                        "text": entry.get("text") or "Provide the missing input.",
                        "type": entry.get("type") or "text",
                        "choices": entry.get("choices"),
                        "required": bool(entry.get("required", True)),
                        "rationale": entry.get("rationale") or "Required to proceed.",
                    }
                )

        placeholder_matches = re.findall(r"\{\{([^}]+)\}\}|\[\[([^\]]+)\]\]", user_task)
        placeholders = [match[0] or match[1] for match in placeholder_matches if match[0] or match[1]]
        for placeholder in placeholders:
            question_id = self._sanitize_question_id(placeholder)
            if answers.get(question_id):
                continue
            questions.append(
                {
                    "id": question_id,
                    "text": f"Please clarify: {placeholder.strip()}",
                    "type": "text",
                    "required": True,
                    "rationale": "This placeholder must be resolved before implementation.",
                }
            )

        if len(user_task.split()) < 5:
            question_id = "task_details"
            if not answers.get(question_id):
                questions.append(
                    {
                        "id": question_id,
                        "text": "Please provide more detail about the desired outcome.",
                        "type": "text",
                        "required": True,
                        "rationale": "The task description is too short to infer requirements.",
                    }
                )

        missing_markers = re.findall(r"\b(TBD|TBC|TODO)\b|\?{2,}", user_task, flags=re.IGNORECASE)
        if missing_markers:
            question_id = "open_questions"
            if not answers.get(question_id):
                questions.append(
                    {
                        "id": question_id,
                        "text": "Please resolve the open questions/unknowns in the task description.",
                        "type": "text",
                        "required": True,
                        "rationale": "Open questions must be answered before coding.",
                    }
                )

        if max_questions and len(questions) > max_questions:
            questions = questions[:max_questions]
        return questions
    
    async def _run_hook(
        self,
        callback: Optional[Callable[[Dict[str, Any]], Any]],
        payload: Dict[str, Any],
    ) -> None:
        if not callback:
            return
        result = callback(payload)
        if asyncio.iscoroutine(result):
            await result

    async def process_task(
        self,
        user_task: str,
        callbacks: Optional[Dict[str, Callable[[Dict[str, Any]], Any]]] = None,
        *,
        workspace_path: Optional[Path] = None,
        command_runner: Optional[Any] = None,
        provided_answers: Optional[Dict[str, Any]] = None,
        resume_from_stage: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Основной метод обработки задачи пользователя"""
        if not self.container:
            self.initialize_project("Auto-generated Project")
        else:
            self._ensure_roles()

        if provided_answers:
            existing_answers = self.container.metadata.get("provided_answers", {})
            if not isinstance(existing_answers, dict):
                existing_answers = {}
            existing_answers.update(provided_answers)
            self.container.metadata["provided_answers"] = existing_answers

        if resume_from_stage:
            self.container.metadata["resume_from_stage"] = resume_from_stage

        stages = ["research", "design", "implementation", "review"]
        start_index = 0
        if resume_from_stage in stages:
            start_index = stages.index(resume_from_stage)
        
        logger.info(f"Starting processing of task: {user_task[:50]}...")
        await self._run_hook(
            callbacks.get("codex_loaded") if callbacks else None,
            {
                "version": self.codex.get("version"),
                "hash": self.codex_hash,
                "rules_summary": self._codex_summary(),
            },
        )
        
        try:
            # Фаза 1: Исследование
            if start_index <= stages.index("research"):
                logger.info("Phase 1: Research")
                await self._run_hook(
                    callbacks.get("stage_started") if callbacks else None,
                    {"stage": "research"},
                )
                self.container.update_state(ProjectState.RESEARCH, "Analyzing requirements")

                researcher_result = await self.roles["researcher"].execute(
                    user_task,
                    self.container
                )
                await self._run_hook(
                    callbacks.get("research_complete") if callbacks else None,
                    {"result": researcher_result},
                )

                self.container.add_artifact(
                    "research_summary",
                    researcher_result,
                    "researcher"
                )
            
            # Фаза 2: Проектирование
            if start_index <= stages.index("design"):
                logger.info("Phase 2: Design")
                await self._run_hook(
                    callbacks.get("stage_started") if callbacks else None,
                    {"stage": "design"},
                )
                self.container.update_state(ProjectState.DESIGN, "Creating architecture")

                design_result = await self.roles["designer"].execute(
                    self.container
                )
                await self._run_hook(
                    callbacks.get("design_complete") if callbacks else None,
                    {"result": design_result},
                )

                self.container.target_architecture = design_result
                self.container.add_artifact(
                    "architecture",
                    design_result,
                    "designer"
                )

            if start_index <= stages.index("implementation"):
                template_manifest = self.container.metadata.get("template_manifest")
                clarification_questions = self._plan_clarification_questions(
                    user_task,
                    template_manifest=template_manifest if isinstance(template_manifest, dict) else None,
                    provided_answers=self.container.metadata.get("provided_answers"),
                )
                if clarification_questions:
                    requested_at = datetime.now().isoformat()
                    resume_stage = "implementation"
                    self.container.metadata["pending_questions"] = clarification_questions
                    self.container.metadata["resume_from_stage"] = resume_stage
                    self.container.update_state(ProjectState.NEEDS_INPUT, "Awaiting clarification")
                    await self._run_hook(
                        callbacks.get("clarification_requested") if callbacks else None,
                        {
                            "questions": clarification_questions,
                            "requested_at": requested_at,
                            "resume_from_stage": resume_stage,
                        },
                    )
                    return {
                        "status": "needs_input",
                        "container_id": self.container.project_id,
                        "state": self.container.state.value,
                        "progress": self.container.progress,
                        "questions": clarification_questions,
                        "resume_from_stage": resume_stage,
                    }
            
            # Фаза 3: Итеративная реализация
            if start_index <= stages.index("implementation"):
                logger.info("Phase 3: Implementation")
                await self._run_hook(
                    callbacks.get("stage_started") if callbacks else None,
                    {"stage": "implementation"},
                )
                self.container.update_state(ProjectState.IMPLEMENTATION, "Implementing solution")
            
            iteration = 0
            max_iterations = self.codex.get("workflow", {}).get("max_iterations", 15)
            logger.info("Codex max_iterations=%s", max_iterations)
            failure_reason: Optional[str] = None
            failure_stage: Optional[str] = None
            next_task_override: Optional[Dict[str, Any]] = None

            if start_index <= stages.index("implementation"):
                while not self.container.is_complete() and iteration < max_iterations:
                    iteration += 1
                    logger.info(f"Implementation iteration {iteration}")

                    # 3.1 Получаем следующую задачу от планировщика
                    next_task = next_task_override or self._get_next_task()
                    next_task_override = None
                    if not next_task:
                        logger.warning("No tasks to execute")
                        break

                    self.container.current_task = next_task["description"]
                    self.container.metadata["active_role"] = "coder"

                    # 3.2 Кодер выполняет задачу
                    try:
                        coder_result = await self.roles["coder"].execute(
                            next_task,
                            self.container
                        )
                    except BudgetExceededError:
                        await self._run_hook(
                            callbacks.get("stage_failed") if callbacks else None,
                            {
                                "stage": "implementation",
                                "reason": "quota_exceeded",
                                "error": "quota_exceeded",
                            },
                        )
                        self.container.update_state(ProjectState.ERROR, "quota_exceeded")
                        return {
                            "status": "failed",
                            "container_id": self.container.project_id,
                            "state": self.container.state.value,
                            "progress": self.container.progress,
                            "files_count": len(self.container.files),
                            "artifacts_count": sum(len(a) for a in self.container.artifacts.values()),
                            "iterations": iteration,
                            "max_iterations": max_iterations,
                            "history": self.task_history[-5:],
                            "failure_reason": "quota_exceeded",
                        }
                    except LLMProviderError as exc:
                        await self._run_hook(
                            callbacks.get("stage_failed") if callbacks else None,
                            {
                                "stage": "implementation",
                                "reason": "llm_provider_error",
                                "error": str(exc),
                            },
                        )
                        await self._run_hook(
                            callbacks.get("llm_error") if callbacks else None,
                            {
                                "stage": "implementation",
                                "error": str(exc),
                            },
                        )
                        raise

                    if isinstance(coder_result, dict) and coder_result.get("llm_usage"):
                        await self._run_hook(
                            callbacks.get("llm_usage") if callbacks else None,
                            {
                                "stage": "implementation",
                                "usage": coder_result.get("llm_usage"),
                                "usage_report": coder_result.get("usage_report"),
                            },
                        )
                    await self._run_hook(
                        callbacks.get("coder_finished") if callbacks else None,
                        {"task": next_task, "result": coder_result, "iteration": iteration},
                    )

                    # 3.3 Ревьюер проверяет результат
                    self.container.metadata["active_role"] = "reviewer"
                    await self._run_hook(
                        callbacks.get("review_started") if callbacks else None,
                        {"kind": "iteration", "iteration": iteration},
                    )
                    review_result = await self.roles["reviewer"].execute(
                        self.container,
                        workspace_path=workspace_path,
                        command_runner=command_runner,
                    )
                    await self._run_hook(
                        callbacks.get("review_finished") if callbacks else None,
                        {"result": review_result, "kind": "iteration", "iteration": iteration},
                    )
                    await self._run_hook(
                        callbacks.get("review_result") if callbacks else None,
                        {"result": review_result, "kind": "iteration", "iteration": iteration},
                    )

                    if review_result.get("command_timeout"):
                        failure_reason = "command_timeout"
                        failure_stage = "implementation"
                        logger.warning("Iteration %s halted due to command timeout", iteration)
                        break
                    if review_result.get("passed"):
                        logger.info(f"Iteration {iteration} approved")
                        self.container.update_progress(iteration / max_iterations)
                    else:
                        logger.warning(f"Iteration {iteration} rejected: {review_result.get('issues', [])}")
                        next_task_override = self._build_fix_task(next_task, review_result)
            else:
                iteration = self.container.metadata.get("iterations", 0) or 0

            if failure_reason:
                await self._run_hook(
                    callbacks.get("stage_failed") if callbacks else None,
                    {
                        "stage": failure_stage or "implementation",
                        "reason": failure_reason,
                        "issues": [],
                    },
                )
                self.container.update_state(ProjectState.ERROR, failure_reason)
                self.task_history.append(
                    {
                        "task": user_task,
                        "status": self.container.state.value,
                        "iterations": iteration,
                        "timestamp": datetime.now().isoformat(),
                    }
                )
                status = "failed"
                return {
                    "status": status,
                    "container_id": self.container.project_id,
                    "state": self.container.state.value,
                    "progress": self.container.progress,
                    "files_count": len(self.container.files),
                    "artifacts_count": sum(len(a) for a in self.container.artifacts.values()),
                    "iterations": iteration,
                    "max_iterations": max_iterations,
                    "history": self.task_history[-5:],
                    "failure_reason": failure_reason,
                }

            if iteration >= max_iterations and not self.container.is_complete():
                failure_reason = "max_iterations_exhausted"
                await self._run_hook(
                    callbacks.get("stage_failed") if callbacks else None,
                    {
                        "stage": "implementation",
                        "reason": failure_reason,
                        "issues": [],
                    },
                )
                self.container.update_state(ProjectState.ERROR, failure_reason)
                self.task_history.append(
                    {
                        "task": user_task,
                        "status": self.container.state.value,
                        "iterations": iteration,
                        "timestamp": datetime.now().isoformat(),
                    }
                )
                status = "failed"
                return {
                    "status": status,
                    "container_id": self.container.project_id,
                    "state": self.container.state.value,
                    "progress": self.container.progress,
                    "files_count": len(self.container.files),
                    "artifacts_count": sum(len(a) for a in self.container.artifacts.values()),
                    "iterations": iteration,
                    "max_iterations": max_iterations,
                    "history": self.task_history[-5:],
                    "failure_reason": failure_reason,
                }
            
            # Фаза 4: Финальное ревью
            review_required = self.codex.get("workflow", {}).get(
                "review_required",
                self.codex.get("workflow", {}).get("require_review", True),
            )
            if review_required and start_index <= stages.index("review"):
                logger.info("Phase 4: Final Review")
                await self._run_hook(
                    callbacks.get("stage_started") if callbacks else None,
                    {"stage": "review"},
                )
                self.container.update_state(ProjectState.REVIEW, "Final quality check")
                
                await self._run_hook(
                    callbacks.get("review_started") if callbacks else None,
                    {"kind": "final"},
                )
                final_review = await self.roles["reviewer"].execute(
                    self.container,
                    workspace_path=workspace_path,
                    command_runner=command_runner,
                )
                await self._run_hook(
                    callbacks.get("review_finished") if callbacks else None,
                    {"result": final_review, "kind": "final"},
                )
                await self._run_hook(
                    callbacks.get("review_result") if callbacks else None,
                    {"result": final_review, "kind": "final"},
                )
                
                if final_review.get("passed"):
                    self.container.update_state(ProjectState.COMPLETE, "Project completed")
                    self.container.update_progress(1.0)
                    logger.info("Project completed successfully")
                else:
                    failure_reason = "Final review failed"
                    issues = final_review.get("issues")
                    await self._run_hook(
                        callbacks.get("stage_failed") if callbacks else None,
                        {
                            "stage": "review",
                            "reason": failure_reason,
                            "issues": issues,
                        },
                    )
                    logger.error(f"Project failed final review: {issues}")
                    self.container.update_state(ProjectState.ERROR, "Failed final review")
            else:
                logger.info("Codex allows skipping final review stage")
                self.container.update_state(ProjectState.COMPLETE, "Project completed (review skipped)")
                self.container.update_progress(1.0)
            
            # Сохраняем историю задачи
            self.task_history.append({
                "task": user_task,
                "status": self.container.state.value,
                "iterations": iteration,
                "timestamp": datetime.now().isoformat()
            })
            
            status = "completed" if self.container.state == ProjectState.COMPLETE else "failed"
            return {
                "status": status,
                "container_id": self.container.project_id,
                "state": self.container.state.value,
                "progress": self.container.progress,
                "files_count": len(self.container.files),
                "artifacts_count": sum(len(a) for a in self.container.artifacts.values()),
                "iterations": iteration,
                "max_iterations": max_iterations,
                "history": self.task_history[-5:],  # Последние 5 задач
                "failure_reason": "Final review failed" if status == "failed" else None,
            }
            
        except Exception as e:
            logger.error(f"Error processing task: {e}", exc_info=True)
            if self.container:
                self.container.update_state(ProjectState.ERROR, f"Processing error: {str(e)}")
                self.container.errors.append(str(e))
                await self._run_hook(
                    callbacks.get("stage_failed") if callbacks else None,
                    {
                        "stage": self.container.state.value,
                        "reason": "processing_error",
                        "error": str(e),
                    },
                )
            
            return {
                "status": "error",
                "error": str(e),
                "container_id": self.container.project_id if self.container else None,
                "failure_reason": str(e),
            }
    
    def _get_next_task(self) -> Optional[Dict[str, Any]]:
        """Простой планировщик: определяет следующую задачу"""
        if not self.container or not self.container.target_architecture:
            return None
        
        # Простая эвристика для MVP
        architecture = self.container.target_architecture
        
        if "components" in architecture:
            components = architecture["components"]
            
            # Ищем компонент без файлов
            for component in components:
                component_name = component.get("name", "unknown")
                expected_files = component.get("files", [])
                
                for filepath in expected_files:
                    if filepath not in self.container.files:
                        return {
                            "type": "implement_component",
                            "component": component_name,
                            "file": filepath,
                            "description": f"Implement {filepath} for {component_name}"
                        }
        
        # Если все файлы есть, проверяем тесты
        files_without_tests = [
            f for f in self.container.files.keys() 
            if f.endswith('.py') and not any(
                t in self.container.files.keys() 
                for t in [
                    f.replace('.py', '_test.py'), 
                    f'test_{f}', 
                    f'tests/test_{f.replace(".py", ".py")}'
                ]
            )
        ]
        
        if files_without_tests:
            file_to_test = files_without_tests[0]
            return {
                "type": "write_tests",
                "file": file_to_test,
                "description": f"Write tests for {file_to_test}"
            }
        
        # Всё сделано
        return None

    @staticmethod
    def _build_fix_task(previous_task: Dict[str, Any], review_result: Dict[str, Any]) -> Dict[str, Any]:
        errors = review_result.get("errors") if isinstance(review_result, dict) else None
        warnings = review_result.get("warnings") if isinstance(review_result, dict) else None
        summary = review_result.get("message") if isinstance(review_result, dict) else None
        return {
            "type": "fix_review_issues",
            "description": f"Fix review findings: {summary}" if summary else "Fix review findings",
            "previous_task": previous_task,
            "review_report": review_result,
            "review_errors": errors,
            "review_warnings": warnings,
        }
    
    def save_container(self, filepath: str) -> None:
        """Сохранить контейнер в файл"""
        if not self.container:
            raise ValueError("No container to save")
        
        data = self.container.to_dict()
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
        
        logger.info(f"Container saved to {filepath}")
    
    def load_container(self, filepath: str) -> Container:
        """Загрузить контейнер из файла"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        self.container = Container.from_dict(data)
        logger.info(f"Container loaded from {filepath}")
        return self.container
    
    def get_metrics(self) -> Dict[str, Any]:
        """Получить метрики оркестратора"""
        return {
            "tasks_processed": len(self.task_history),
            "successful_tasks": len([t for t in self.task_history if t.get("status") == "completed"]),
            "failed_tasks": len([t for t in self.task_history if t.get("status") == "failed"]),
            "current_container": self.container.project_id if self.container else None,
            "active_roles": list(self.roles.keys())
        }


if __name__ == "__main__":
    # Тестирование оркестратора
    import asyncio
    
    async def test_orchestrator():
        orchestrator = AIOrchestrator()
        container = orchestrator.initialize_project("Test API Project")
        
        result = await orchestrator.process_task(
            "Create a REST API for managing todo items with CRUD operations"
        )
        
        print(f"Result: {result}")
        print(f"Container state: {container.state.value}")
        print(f"Files created: {list(container.files.keys())}")
        
        # Сохраняем контейнер
        orchestrator.save_container("test_container.json")
        
        # Метрики
        print(f"Metrics: {orchestrator.get_metrics()}")
    
    asyncio.run(test_orchestrator())
