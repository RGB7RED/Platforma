"""Task planning and output contract validation."""

from __future__ import annotations

import json
import os
import re
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .llm import generate_with_retry, get_llm_provider, load_llm_settings


class TaskMode(str, Enum):
    micro_file = "micro_file"
    small_code = "small_code"
    project = "project"


class OutputContract(BaseModel):
    exact_json_only: bool = False
    allowed_files_count: Optional[int] = None
    allowed_paths: Optional[List[str]] = None
    no_extra_files: bool = False
    no_extra_text_outside_json: bool = False
    required_json_top_level_keys: List[str] = Field(default_factory=lambda: ["files"])


class TaskPlan(BaseModel):
    mode: TaskMode
    stages: List[str]
    max_iterations: int
    contract: OutputContract
    use_review: bool
    notes: Dict[str, Any] = Field(default_factory=dict)


class OutputContractViolation(ValueError):
    def __init__(self, violations: List[str]):
        super().__init__("contract_violation")
        self.violations = violations


async def build_task_plan(
    task_text: str,
    codex_cfg: Dict[str, Any],
    *,
    allow_llm: bool = True,
) -> TaskPlan:
    workflow = codex_cfg.get("workflow", {}) if isinstance(codex_cfg, dict) else {}
    default_stages = workflow.get("stages") or ["research", "design", "planning", "implementation", "review"]
    default_max_iterations = workflow.get("max_iterations", 15)
    review_required = workflow.get("review_required", workflow.get("require_review", True))

    heuristics = _heuristic_plan(task_text)
    if heuristics:
        return _finalize_plan(heuristics, default_stages, default_max_iterations, review_required)

    if allow_llm:
        llm_plan = await _classify_with_llm(task_text)
        if llm_plan:
            return _finalize_plan(llm_plan, default_stages, default_max_iterations, review_required)

    fallback = {
        "mode": TaskMode.project,
        "contract": OutputContract(),
        "notes": {"source": "fallback"},
    }
    return _finalize_plan(fallback, default_stages, default_max_iterations, review_required)


def build_default_plan(codex_cfg: Dict[str, Any]) -> TaskPlan:
    workflow = codex_cfg.get("workflow", {}) if isinstance(codex_cfg, dict) else {}
    default_stages = workflow.get("stages") or ["research", "design", "planning", "implementation", "review"]
    default_max_iterations = workflow.get("max_iterations", 15)
    review_required = workflow.get("review_required", workflow.get("require_review", True))
    fallback = {
        "mode": TaskMode.project,
        "contract": OutputContract(),
        "notes": {"source": "default"},
    }
    return _finalize_plan(fallback, default_stages, default_max_iterations, review_required)


def validate_output_contract(
    contract: OutputContract,
    raw_text: str,
    parsed_json: Any,
) -> None:
    violations: List[str] = []
    stripped = raw_text.strip()

    if contract.exact_json_only or contract.no_extra_text_outside_json:
        decoder = json.JSONDecoder()
        try:
            obj, end = decoder.raw_decode(stripped)
        except json.JSONDecodeError:
            violations.append("response is not valid JSON")
        else:
            if stripped[end:].strip():
                violations.append("response includes extra text outside JSON")
            if contract.exact_json_only and not isinstance(obj, dict):
                violations.append("top-level JSON must be an object")

    if not isinstance(parsed_json, dict):
        violations.append("parsed response is not a JSON object")
    else:
        required_keys = contract.required_json_top_level_keys or []
        if required_keys and not all(key in parsed_json for key in required_keys):
            violations.append("missing required top-level keys")
        if required_keys and (contract.exact_json_only or contract.no_extra_text_outside_json):
            extra_keys = set(parsed_json.keys()) - set(required_keys)
            if extra_keys:
                violations.append("extra top-level keys are not allowed")

        files_value = parsed_json.get("files")
        if not isinstance(files_value, list):
            violations.append("files must be a list")
        else:
            if contract.allowed_files_count is not None and len(files_value) != contract.allowed_files_count:
                violations.append("files count does not match contract")
            allowed_paths = contract.allowed_paths or []
            if allowed_paths:
                for file_entry in files_value:
                    path = str(file_entry.get("path") or file_entry.get("file") or "").strip()
                    if path and path not in allowed_paths:
                        violations.append("file path is not allowed")
                        break

    if violations:
        raise OutputContractViolation(violations)


def build_contract_repair_prompt(contract: OutputContract, violations: List[str]) -> str:
    allowed_paths = ", ".join(contract.allowed_paths or [])
    files_hint = "one file" if contract.allowed_files_count == 1 else "files"
    return (
        "You violated the output contract: "
        f"{'; '.join(violations)}.\n"
        "Return ONLY a valid JSON object with the correct schema. "
        "No markdown, no extra text. "
        f"Include {files_hint} under the 'files' key. "
        f"Allowed paths: {allowed_paths or 'not specified'}."
    )


def _heuristic_plan(task_text: str) -> Optional[Dict[str, Any]]:
    lowered = task_text.lower()
    json_strict_markers = [
        "return exactly this json",
        "return exact json",
        "exact json",
    ]
    project_markers = [
        "fastapi",
        "website",
        "next.js",
        "docker",
        "crud",
        "db",
        "auth",
        "tests",
        "ci",
        "api",
        "rest",
        "сайт",
        "лендинг",
        "визитк",
        "одностранич",
        "landing",
        "страница",
        "визитка",
    ]

    strict_json = any(marker in lowered for marker in json_strict_markers)
    json_paths = _extract_json_paths(task_text)
    create_file_paths = _extract_create_file_paths(task_text)
    allowed_paths = list(dict.fromkeys(json_paths + create_file_paths)) or None

    if strict_json or json_paths or create_file_paths:
        contract = OutputContract(
            exact_json_only=True,
            allowed_files_count=1,
            allowed_paths=allowed_paths,
            no_extra_files=True,
            no_extra_text_outside_json=True,
        )
        return {
            "mode": TaskMode.micro_file,
            "contract": contract,
            "notes": {
                "source": "heuristic",
                "strict_json": strict_json,
                "allowed_paths": allowed_paths,
            },
        }

    if any(marker in lowered for marker in project_markers):
        return {
            "mode": TaskMode.project,
            "contract": OutputContract(),
            "notes": {"source": "heuristic"},
        }

    return None


def _finalize_plan(
    plan_payload: Dict[str, Any],
    default_stages: List[str],
    default_max_iterations: int,
    review_required: bool,
) -> TaskPlan:
    mode = plan_payload.get("mode", TaskMode.project)
    contract = plan_payload.get("contract") or OutputContract()
    notes = plan_payload.get("notes") or {}

    if mode == TaskMode.micro_file:
        stages = ["implementation"]
        max_iterations = _get_int_env("ORCH_MICRO_MAX_ITERATIONS", 3)
        use_review = False
    elif mode == TaskMode.small_code:
        stages = _filter_stages(default_stages, {"implementation", "review", "design", "planning"})
        if not stages:
            stages = ["implementation", "review"]
        max_iterations = default_max_iterations
        use_review = review_required
    else:
        stages = list(default_stages)
        max_iterations = default_max_iterations
        use_review = review_required

    stages = _ensure_research_before_design(stages)
    stages = _ensure_planning_after_design(stages)

    return TaskPlan(
        mode=mode,
        stages=stages,
        max_iterations=max_iterations,
        contract=contract,
        use_review=use_review,
        notes=notes,
    )


def _extract_json_paths(task_text: str) -> List[str]:
    paths: List[str] = []
    for match in re.finditer(r"\"path\"\s*:\s*\"([^\"]+)\"", task_text):
        candidate = match.group(1).strip()
        if candidate:
            paths.append(candidate)
    return paths


def _extract_create_file_paths(task_text: str) -> List[str]:
    paths: List[str] = []
    for match in re.finditer(r"create a file\s+([^\s\n]+)", task_text, flags=re.IGNORECASE):
        candidate = match.group(1).strip().strip("`\"")
        if candidate:
            paths.append(candidate)
    return paths


def _filter_stages(stages: List[str], allowed: set[str]) -> List[str]:
    return [stage for stage in stages if stage in allowed]


def _ensure_research_before_design(stages: List[str]) -> List[str]:
    if "design" not in stages or "research" in stages:
        return stages
    design_index = stages.index("design")
    return stages[:design_index] + ["research"] + stages[design_index:]


def _ensure_planning_after_design(stages: List[str]) -> List[str]:
    if "planning" not in stages or "design" not in stages:
        return stages
    design_index = stages.index("design")
    planning_index = stages.index("planning")
    if planning_index > design_index:
        return stages
    reordered = [stage for stage in stages if stage != "planning"]
    insert_at = reordered.index("design") + 1
    return reordered[:insert_at] + ["planning"] + reordered[insert_at:]


def _get_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


async def _classify_with_llm(task_text: str) -> Optional[Dict[str, Any]]:
    settings = load_llm_settings()
    provider = get_llm_provider(settings)
    max_tokens = _get_int_env("ORCH_PLAN_MAX_TOKENS", 256)
    system_prompt = (
        "You classify tasks into modes. Return JSON only with keys: "
        "mode, needs_review, contract."
    )
    user_prompt = (
        "Classify the task into one of: micro_file, small_code, project. "
        "If the task demands exact JSON or a single file, choose micro_file. "
        "Respond with JSON like: "
        "{\"mode\":\"micro_file\",\"needs_review\":false,"
        "\"contract\":{\"exact_json_only\":true}}\n"
        f"Task: {task_text}"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    try:
        response = await generate_with_retry(
            provider,
            messages,
            settings,
            require_json=True,
            max_tokens_override=max_tokens,
        )
    except (RuntimeError, Exception):
        return None

    text = (response or {}).get("text", "") if isinstance(response, dict) else ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None

    mode_value = payload.get("mode")
    if mode_value not in {mode.value for mode in TaskMode}:
        return None
    contract_payload = payload.get("contract") or {}
    try:
        contract = OutputContract.model_validate(contract_payload)
    except Exception:
        contract = OutputContract()
    notes = {"source": "llm"}
    return {
        "mode": TaskMode(mode_value),
        "contract": contract,
        "notes": notes,
    }
