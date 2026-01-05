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
from .planning import TaskMode, build_default_plan, build_task_plan
from .logging_utils import configure_logging
from .agents import (
    AIResearcher,
    AIInterviewer,
    AIDesigner,
    AIPlanner,
    AICoder,
    AIReviewer,
    BudgetExceededError,
    LLMResponseParseError,
)
from .llm import LLMOutputTruncatedError, LLMProviderError


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
                "stages": ["research", "design", "planning", "implementation", "review"],
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
            "interviewer": AIInterviewer(self.codex),
            "designer": AIDesigner(self.codex),
            "planner": AIPlanner(self.codex),
            "coder": AICoder(self.codex),
            "reviewer": AIReviewer(self.codex),
        }

    def _sanitize_question_id(self, text: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", text.strip().lower()).strip("_")
        return normalized or str(uuid.uuid4())

    @staticmethod
    def _get_int_env(name: str, default: int) -> int:
        value = os.getenv(name)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            return default

    @staticmethod
    def _get_bool_env(name: str) -> Optional[bool]:
        value = os.getenv(name)
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
        return None

    def _manual_step_enabled(self, manual_step_enabled: Optional[bool]) -> bool:
        if manual_step_enabled is not None:
            return bool(manual_step_enabled)
        if self.container:
            metadata_value = self.container.metadata.get("manual_step_enabled")
            if isinstance(metadata_value, bool):
                return metadata_value
        env_value = self._get_bool_env("MANUAL_STEP_ENABLED")
        return bool(env_value) if env_value is not None else False

    def _is_triage_enabled(self) -> bool:
        env_value = self._get_bool_env("ORCH_ENABLE_TRIAGE")
        return True if env_value is None else bool(env_value)

    def _is_interactive_research_enabled(self) -> bool:
        env_value = self._get_bool_env("ORCH_INTERACTIVE_RESEARCH")
        return bool(env_value) if env_value is not None else False

    def _get_task_token_usage(self, task_description: Optional[str]) -> int:
        if not task_description:
            return 0
        usage_entries = self.container.metadata.get("llm_usage", [])
        total_tokens = 0
        for entry in usage_entries:
            metadata = entry.get("metadata") or {}
            if metadata.get("task_description") != task_description:
                continue
            total_tokens += int(entry.get("total_tokens", 0) or 0)
        return total_tokens

    @staticmethod
    def _build_next_actions(
        *,
        stage: str,
        iteration: int,
        review_result: Dict[str, Any],
        next_task_preview: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        summary = "Review completed"
        if isinstance(review_result, dict):
            message = review_result.get("message") or review_result.get("summary")
            status = review_result.get("status")
            issues = review_result.get("issues") if isinstance(review_result.get("issues"), list) else None
            if message:
                summary = str(message)
            elif issues:
                summary = f"{len(issues)} issue(s) reported"
            elif status:
                summary = str(status)

        actions: List[Dict[str, Any]] = []
        passed = bool(review_result.get("passed")) if isinstance(review_result, dict) else False
        if next_task_preview:
            action_type = "continue" if passed else "fix"
            priority = "normal" if passed else "high"
            actions.append(
                {
                    "role": "coder",
                    "type": action_type,
                    "priority": priority,
                    "details": next_task_preview.get("description") if isinstance(next_task_preview, dict) else None,
                }
            )
        return {
            "stage": stage,
            "iteration": iteration,
            "based_on": "review_report",
            "summary": summary,
            "actions": actions,
        }

    @staticmethod
    def _preview_task(task: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(task, dict):
            return None
        preview_keys = {"type", "description", "file", "component"}
        return {key: task.get(key) for key in preview_keys if task.get(key) is not None}

    def _latest_artifact_content(self, key: str) -> Optional[Any]:
        if not self.container:
            return None
        artifacts = self.container.artifacts.get(key) or []
        if not artifacts:
            return None
        latest = artifacts[-1]
        return latest.content if hasattr(latest, "content") else latest

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

        if len(user_task.split()) < 3:
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

    async def _execute_planning_stage(
        self,
        callbacks: Optional[Dict[str, Callable[[Dict[str, Any]], Any]]],
    ) -> Dict[str, Any]:
        await self._run_hook(
            callbacks.get("stage_started") if callbacks else None,
            {"stage": "planning"},
        )
        self.container.update_state(ProjectState.DESIGN, "Planning implementation")
        planner_result = await self.roles["planner"].execute(self.container)
        await self._run_hook(
            callbacks.get("planning_complete") if callbacks else None,
            {"result": planner_result},
        )
        self.container.add_artifact(
            "implementation_plan",
            planner_result,
            "planner",
        )
        return planner_result

    async def process_task(
        self,
        user_task: str,
        callbacks: Optional[Dict[str, Callable[[Dict[str, Any]], Any]]] = None,
        *,
        workspace_path: Optional[Path] = None,
        command_runner: Optional[Any] = None,
        provided_answers: Optional[Dict[str, Any]] = None,
        resume_from_stage: Optional[str] = None,
        manual_step_enabled: Optional[bool] = None,
        resume_payload: Optional[Dict[str, Any]] = None,
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
        if manual_step_enabled is not None:
            self.container.metadata["manual_step_enabled"] = manual_step_enabled
        if resume_payload is not None:
            self.container.metadata["resume_payload"] = resume_payload
        triage_enabled = self._is_triage_enabled()
        if triage_enabled:
            plan = await build_task_plan(user_task, self.codex, allow_llm=True)
        else:
            plan = build_default_plan(self.codex)
        self.container.metadata["task_plan"] = plan.model_dump()
        if plan.mode == TaskMode.micro_file:
            if plan.contract.allowed_paths:
                self.container.metadata["allowed_paths"] = plan.contract.allowed_paths
            self.container.metadata["output_contract"] = plan.contract.model_dump()

        stages = plan.stages
        stage_indexes = {stage: idx for idx, stage in enumerate(stages)}
        start_index = 0
        if resume_from_stage in stage_indexes:
            start_index = stage_indexes[resume_from_stage]
        
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
            if "research" in stage_indexes and start_index <= stage_indexes["research"]:
                logger.info("Phase 1: Research")
                await self._run_hook(
                    callbacks.get("stage_started") if callbacks else None,
                    {"stage": "research"},
                )
                self.container.update_state(ProjectState.RESEARCH, "Analyzing requirements")
                if self._is_interactive_research_enabled():
                    researcher_result = await self.roles["interviewer"].execute(
                        user_task,
                        self.container,
                    )
                    if isinstance(researcher_result, dict) and researcher_result.get("status") == "needs_user_input":
                        message = researcher_result.get("message")
                        if message:
                            await self._run_hook(
                                callbacks.get("chat_message") if callbacks else None,
                                {
                                    "role": "assistant",
                                    "content": message,
                                    "round": researcher_result.get("round"),
                                    "questions": researcher_result.get("questions"),
                                },
                            )
                        self.container.update_state(ProjectState.AWAITING_USER, "Awaiting user input")
                        return {
                            "status": "awaiting_user",
                            "container_id": self.container.project_id,
                            "state": self.container.state.value,
                            "progress": self.container.progress,
                            "research_round": researcher_result.get("round"),
                            "chat_message": message,
                            "resume_from_stage": "research",
                        }
                else:
                    researcher_result = await self.roles["researcher"].execute(
                        user_task,
                        self.container,
                    )

                await self._run_hook(
                    callbacks.get("research_complete") if callbacks else None,
                    {"result": researcher_result},
                )

                self.container.add_artifact(
                    "research_summary",
                    researcher_result,
                    "researcher",
                )
            
            # Фаза 2: Проектирование
            if "design" in stage_indexes and start_index <= stage_indexes["design"]:
                logger.info("Phase 2: Design")
                if not self.container.artifacts.get("requirements"):
                    logger.warning("Missing requirements before design; running research fallback.")
                    await self._run_hook(
                        callbacks.get("stage_started") if callbacks else None,
                        {"stage": "research"},
                    )
                    self.container.update_state(ProjectState.RESEARCH, "Analyzing requirements")
                    researcher_result = await self.roles["researcher"].execute(
                        user_task,
                        self.container,
                    )
                    await self._run_hook(
                        callbacks.get("research_complete") if callbacks else None,
                        {"result": researcher_result},
                    )
                    self.container.add_artifact(
                        "research_summary",
                        researcher_result,
                        "researcher",
                    )
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

            if "planning" in stage_indexes and start_index <= stage_indexes["planning"]:
                logger.info("Phase 3: Planning")
                await self._execute_planning_stage(callbacks)

            if "implementation" in stage_indexes and start_index <= stage_indexes["implementation"]:
                template_manifest = self.container.metadata.get("template_manifest")
                clarification_questions = []
                if plan.mode == TaskMode.project:
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
            
            review_cycles = int(self.container.metadata.get("review_cycles", 0) or 0)
            max_review_cycles = self._get_int_env("ORCH_MAX_REVIEW_CYCLES", 3)
            max_iterations = plan.max_iterations
            logger.info("Plan mode=%s max_iterations=%s", plan.mode.value, max_iterations)

            while True:
                # Фаза 3: Итеративная реализация
                if "implementation" in stage_indexes and start_index <= stage_indexes["implementation"]:
                    logger.info("Phase 3: Implementation")
                    await self._run_hook(
                        callbacks.get("stage_started") if callbacks else None,
                        {"stage": "implementation"},
                    )
                    self.container.update_state(ProjectState.IMPLEMENTATION, "Implementing solution")

                iteration = 0
                failure_reason: Optional[str] = None
                failure_stage: Optional[str] = None
                next_task_override: Optional[Dict[str, Any]] = None
                skip_manual_stage: Optional[str] = None
                if isinstance(resume_payload, dict):
                    next_task_override = resume_payload.get("next_task_override")
                    skip_manual_stage = resume_payload.get("skip_manual_step_stage")
                max_llm_calls = self._get_int_env("LLM_MAX_CALLS_PER_TASK", 10)
                max_retries_per_step = self._get_int_env("LLM_MAX_RETRIES_PER_STEP", 1)
                self.container.metadata.setdefault("llm_calls", 0)
                self.container.metadata.setdefault("llm_retries", 0)
                self.container.metadata["iterations"] = iteration
                if plan.mode == TaskMode.micro_file:
                    micro_task = {
                        "type": "micro_file",
                        "description": user_task,
                        "allowed_paths": plan.contract.allowed_paths or [],
                        "output_contract": plan.contract.model_dump(),
                    }
                    if plan.contract.allowed_paths and len(plan.contract.allowed_paths) == 1:
                        micro_task["file"] = plan.contract.allowed_paths[0]
                    next_task_override = micro_task

                if "implementation" in stage_indexes and start_index <= stage_indexes["implementation"]:
                    while iteration < max_iterations:
                        iteration += 1
                        self.container.metadata["iterations"] = iteration
                        logger.info(f"Implementation iteration {iteration}")

                        # 3.1 Получаем следующую задачу от планировщика
                        next_task = (
                            next_task_override
                            or self._get_next_plan_task()
                            or self._get_next_task()
                        )
                        next_task_override = None
                        if not next_task:
                            logger.warning("No tasks to execute")
                            break

                        self.container.current_task = next_task["description"]
                        self.container.metadata["active_role"] = "coder"
                        plan_step_id = next_task.get("plan_step_id")
                        plan_step_index = next_task.get("plan_step_index")
                        if plan_step_id is not None:
                            await self._run_hook(
                                callbacks.get("plan_step_started") if callbacks else None,
                                {
                                    "plan_step_id": plan_step_id,
                                    "plan_step_index": plan_step_index,
                                    "plan_version": next_task.get("plan_version"),
                                    "description": next_task.get("description"),
                                },
                            )

                        # 3.2 Кодер выполняет задачу
                        coder_result = None
                        correction_prompt = None
                        retries_used = 0
                        for attempt in range(max_retries_per_step + 1):
                            try:
                                max_tokens_per_task = self._get_int_env(
                                    "LLM_MAX_TOTAL_TOKENS_PER_TASK",
                                    5000,
                                )
                                if max_tokens_per_task > 0:
                                    used_tokens = self._get_task_token_usage(
                                        next_task.get("description")
                                    )
                                    if used_tokens >= max_tokens_per_task:
                                        await self._run_hook(
                                            callbacks.get("stage_failed") if callbacks else None,
                                            {
                                                "stage": "implementation",
                                                "reason": "llm_budget_exceeded",
                                                "error": "llm_budget_exceeded",
                                            },
                                        )
                                        self.container.update_state(
                                            ProjectState.ERROR,
                                            "llm_budget_exceeded",
                                        )
                                        return {
                                            "status": "failed",
                                            "container_id": self.container.project_id,
                                            "state": self.container.state.value,
                                            "progress": self.container.progress,
                                            "files_count": len(self.container.files),
                                            "artifacts_count": sum(
                                                len(a) for a in self.container.artifacts.values()
                                            ),
                                            "iterations": iteration,
                                            "max_iterations": max_iterations,
                                            "history": self.task_history[-5:],
                                            "failure_reason": "llm_budget_exceeded",
                                        }
                                if (
                                    max_llm_calls > 0
                                    and self.container.metadata.get("llm_calls", 0) >= max_llm_calls
                                ):
                                    await self._run_hook(
                                        callbacks.get("stage_failed") if callbacks else None,
                                        {
                                            "stage": "implementation",
                                            "reason": "llm_budget_exhausted",
                                            "error": "llm_budget_exhausted",
                                        },
                                    )
                                    self.container.update_state(
                                        ProjectState.ERROR,
                                        "llm_budget_exhausted",
                                    )
                                    return {
                                        "status": "failed",
                                        "container_id": self.container.project_id,
                                        "state": self.container.state.value,
                                        "progress": self.container.progress,
                                        "files_count": len(self.container.files),
                                        "artifacts_count": sum(
                                            len(a) for a in self.container.artifacts.values()
                                        ),
                                        "iterations": iteration,
                                        "max_iterations": max_iterations,
                                        "history": self.task_history[-5:],
                                        "failure_reason": "llm_budget_exhausted",
                                    }
                                self.container.metadata["llm_calls"] = (
                                    self.container.metadata.get("llm_calls", 0) + 1
                                )
                                coder_result = await self.roles["coder"].execute(
                                    next_task,
                                    self.container,
                                    correction_prompt=correction_prompt,
                                )
                                break
                            except LLMResponseParseError as exc:
                                parse_retry_limit = min(max_retries_per_step, 1)
                                if retries_used < parse_retry_limit:
                                    retries_used += 1
                                    self.container.metadata["llm_retries"] = (
                                        self.container.metadata.get("llm_retries", 0) + 1
                                    )
                                    correction_prompt = (
                                        "OUTPUT JSON ONLY. "
                                        "No markdown. "
                                        "No extra keys. "
                                        "Must be a single JSON object."
                                    )
                                    continue
                                reason_label = exc.reason or "llm_invalid_json"
                                reason_detail = (exc.error or reason_label).strip()
                                if len(reason_detail) > 200:
                                    reason_detail = f"{reason_detail[:200].rstrip()}..."
                                await self._run_hook(
                                    callbacks.get("stage_failed") if callbacks else None,
                                    {
                                        "stage": "implementation",
                                        "reason": reason_label,
                                        "error": exc.error or str(exc),
                                    },
                                )
                                self.container.update_state(ProjectState.ERROR, reason_label)
                                return {
                                    "status": "failed",
                                    "container_id": self.container.project_id,
                                    "state": self.container.state.value,
                                    "progress": self.container.progress,
                                    "files_count": len(self.container.files),
                                    "artifacts_count": sum(
                                        len(a) for a in self.container.artifacts.values()
                                    ),
                                    "iterations": iteration,
                                    "max_iterations": max_iterations,
                                    "history": self.task_history[-5:],
                                    "failure_reason": f"{reason_label}: {reason_detail}",
                                }
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
                            except LLMOutputTruncatedError as exc:
                                if retries_used < max_retries_per_step:
                                    retries_used += 1
                                    self.container.metadata["llm_retries"] = (
                                        self.container.metadata.get("llm_retries", 0) + 1
                                    )
                                    correction_prompt = (
                                        "Previous response was truncated. "
                                        "Respond concisely and fit within the token limits. "
                                        "OUTPUT JSON ONLY. No markdown. No extra keys."
                                    )
                                    logger.warning(
                                        "LLM output truncated; retrying step (%s/%s).",
                                        retries_used,
                                        max_retries_per_step,
                                    )
                                    continue
                                reason = str(exc) or "llm_output_truncated"
                                if not reason.startswith("llm_output_"):
                                    reason = "llm_output_truncated"
                                await self._run_hook(
                                    callbacks.get("stage_failed") if callbacks else None,
                                    {
                                        "stage": "implementation",
                                        "reason": reason,
                                        "error": str(exc),
                                    },
                                )
                                self.container.update_state(
                                    ProjectState.ERROR,
                                    reason,
                                )
                                return {
                                    "status": "failed",
                                    "container_id": self.container.project_id,
                                    "state": self.container.state.value,
                                    "progress": self.container.progress,
                                    "files_count": len(self.container.files),
                                    "artifacts_count": sum(
                                        len(a) for a in self.container.artifacts.values()
                                    ),
                                    "iterations": iteration,
                                    "max_iterations": max_iterations,
                                    "history": self.task_history[-5:],
                                    "failure_reason": reason,
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
                        if coder_result is None:
                            raise RuntimeError("Coder result missing after LLM retry attempts.")

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
                        if plan_step_id is not None:
                            next_index = int(plan_step_index or 0) + 1
                            self.container.metadata["plan_step_index"] = next_index
                            self.container.add_artifact(
                                "plan_step_index",
                                {
                                    "index": next_index,
                                    "plan_step_id": plan_step_id,
                                    "plan_version": next_task.get("plan_version"),
                                },
                                "orchestrator",
                            )
                            await self._run_hook(
                                callbacks.get("plan_step_finished") if callbacks else None,
                                {
                                    "plan_step_id": plan_step_id,
                                    "plan_step_index": plan_step_index,
                                    "plan_version": next_task.get("plan_version"),
                                    "description": next_task.get("description"),
                                },
                            )

                        if plan.mode == TaskMode.micro_file:
                            self.container.update_state(ProjectState.COMPLETE, "Micro task completed")
                            self.container.update_progress(1.0)
                            break

                        if plan.use_review:
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
                                logger.warning(
                                    f"Iteration {iteration} rejected: {review_result.get('issues', [])}"
                                )
                                next_task_override = self._build_fix_task(next_task, review_result)
                            next_task_preview = self._preview_task(
                                next_task_override or self._get_next_task()
                            )
                            next_actions = self._build_next_actions(
                                stage="implementation",
                                iteration=iteration,
                                review_result=review_result,
                                next_task_preview=next_task_preview,
                            )
                            self.container.add_artifact("next_actions", next_actions, "orchestrator")
                            await self._run_hook(
                                callbacks.get("next_actions") if callbacks else None,
                                {"payload": next_actions},
                            )
                            manual_stage = "post_iteration_review"
                            if (
                                self._manual_step_enabled(manual_step_enabled)
                                and manual_stage != skip_manual_stage
                            ):
                                last_review_status = (
                                    review_result.get("status")
                                    if isinstance(review_result, dict)
                                    else None
                                )
                                self.container.metadata.update(
                                    {
                                        "awaiting_manual_step": True,
                                        "manual_step_stage": manual_stage,
                                        "manual_step_options": ["continue", "stop", "retry"],
                                        "last_review_status": last_review_status,
                                        "next_task_preview": next_task_preview,
                                        "resume_phase": "implementation",
                                        "resume_iteration": iteration,
                                        "resume_payload": {
                                            "next_task_override": next_task_override,
                                            "next_task_preview": next_task_preview,
                                        },
                                    }
                                )
                                return {
                                    "status": "needs_input",
                                    "container_id": self.container.project_id,
                                    "state": self.container.state.value,
                                    "progress": self.container.progress,
                                    "awaiting_manual_step": True,
                                    "manual_step_stage": manual_stage,
                                    "manual_step_options": ["continue", "stop", "retry"],
                                    "last_review_status": last_review_status,
                                    "last_review_report_artifact_id": self.container.metadata.get(
                                        "last_review_report_artifact_id"
                                    ),
                                    "next_task_preview": next_task_preview,
                                    "resume_phase": "implementation",
                                    "resume_iteration": iteration,
                                    "resume_payload": {
                                        "next_task_override": next_task_override,
                                        "next_task_preview": next_task_preview,
                                    },
                                }
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
                review_required = plan.use_review
                if review_required and "review" in stage_indexes and start_index <= stage_indexes["review"]:
                    manual_stage = "pre_final_review"
                    if self._manual_step_enabled(manual_step_enabled) and manual_stage != skip_manual_stage:
                        self.container.metadata.update(
                            {
                                "awaiting_manual_step": True,
                                "manual_step_stage": manual_stage,
                                "manual_step_options": ["continue", "stop", "retry"],
                                "resume_phase": "review",
                                "resume_iteration": iteration,
                                "resume_payload": {},
                            }
                        )
                        return {
                            "status": "needs_input",
                            "container_id": self.container.project_id,
                            "state": self.container.state.value,
                            "progress": self.container.progress,
                            "awaiting_manual_step": True,
                            "manual_step_stage": manual_stage,
                            "manual_step_options": ["continue", "stop", "retry"],
                            "next_task_preview": None,
                            "resume_phase": "review",
                            "resume_iteration": iteration,
                            "resume_payload": {},
                        }
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
                        break

                    review_cycles += 1
                    self.container.metadata["review_cycles"] = review_cycles
                    if review_cycles >= max_review_cycles:
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
                        break

                    logger.info(
                        "Final review failed; rerouting to planning (cycle %s/%s).",
                        review_cycles,
                        max_review_cycles,
                    )
                    self.container.metadata["plan_step_index"] = 0
                    await self._execute_planning_stage(callbacks)
                    continue
                else:
                    logger.info("Codex allows skipping final review stage")
                    self.container.update_state(ProjectState.COMPLETE, "Project completed (review skipped)")
                    self.container.update_progress(1.0)
                    break

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

    def _get_next_plan_task(self) -> Optional[Dict[str, Any]]:
        if not self.container:
            return None
        plan = self._latest_artifact_content("implementation_plan")
        if not isinstance(plan, dict):
            return None
        steps = plan.get("steps")
        if not isinstance(steps, list) or not steps:
            return None
        order = plan.get("order")
        if isinstance(order, list) and order:
            id_to_step = {step.get("id"): step for step in steps if isinstance(step, dict)}
            ordered_steps = [id_to_step.get(step_id) for step_id in order]
            steps = [step for step in ordered_steps if isinstance(step, dict)]

        step_index = int(self.container.metadata.get("plan_step_index", 0) or 0)
        if step_index >= len(steps):
            return None
        step = steps[step_index]
        goal = step.get("goal") or step.get("description") or "Execute plan step"
        return {
            "type": "plan_step",
            "description": goal,
            "plan_step_id": step.get("id"),
            "plan_step_index": step_index,
            "plan_version": plan.get("plan_version"),
            "files": step.get("files"),
            "acceptance_criteria": step.get("acceptance_criteria"),
            "verification_commands": step.get("commands"),
        }

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
