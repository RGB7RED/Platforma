from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class EventItem(BaseModel):
    id: str
    type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: str


class EventsResponse(BaseModel):
    task_id: str
    total: int
    events: List[EventItem] = Field(default_factory=list)


class ArtifactItem(BaseModel):
    id: str
    type: str
    produced_by: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: str


class ArtifactsResponse(BaseModel):
    task_id: str
    total: int
    artifacts: List[ArtifactItem] = Field(default_factory=list)


class ContainerStateSnapshot(BaseModel):
    status: Optional[str] = None
    progress: Optional[Union[float, int]] = None
    current_stage: Optional[str] = None
    active_role: Optional[str] = None
    current_task: Optional[str] = None
    codex_version: Optional[str] = None
    timestamps: Optional[Dict[str, Any]] = None
    container_state: Optional[str] = None
    container_progress: Optional[Union[float, int]] = None
    awaiting_manual_step: Optional[bool] = None
    manual_step_stage: Optional[str] = None
    manual_step_options: Optional[List[str]] = None
    last_review_status: Optional[str] = None
    last_review_report_artifact_id: Optional[str] = None
    next_task_preview: Optional[Dict[str, Any]] = None
    resume_phase: Optional[str] = None
    resume_iteration: Optional[int] = None
    resume_payload: Optional[Dict[str, Any]] = None


class ContainerStateResponse(BaseModel):
    task_id: str
    state: ContainerStateSnapshot
    updated_at: Optional[str] = None


class ClarificationQuestion(BaseModel):
    id: str
    text: str
    type: str = "text"
    choices: Optional[List[str]] = None
    required: bool = True
    rationale: Optional[str] = None


class TaskQuestionsResponse(BaseModel):
    task_id: str
    pending_questions: List[ClarificationQuestion] = Field(default_factory=list)
    provided_answers: Dict[str, Any] = Field(default_factory=dict)
    resume_from_stage: Optional[str] = None
    requested_at: Optional[str] = None


class TaskInputRequest(BaseModel):
    answers: Dict[str, Any] = Field(default_factory=dict)
    auto_resume: bool = False


class TaskResumeResponse(BaseModel):
    task_id: str
    status: str
    resume_from_stage: Optional[str] = None


class TaskManualStepRequest(BaseModel):
    decision: str
    note: Optional[str] = None
    override_task: Optional[Dict[str, Any]] = None
