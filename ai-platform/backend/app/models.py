"""
Модуль контейнера - единый источник истины для проекта.
Содержит 4 уровня данных: файлы, артефакты, история и метаданные.
"""

import json
import uuid
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field, asdict


class ProjectState(Enum):
    """Состояния проекта в жизненном цикле"""
    RESEARCH = "research"
    DESIGN = "design"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class Artifact:
    """Базовый класс артефакта"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: str = ""
    content: Any = None
    created_at: datetime = field(default_factory=datetime.now)
    created_by: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class Container:
    """Основной контейнер проекта с 4 уровнями"""
    
    def __init__(self, project_id: Optional[str] = None):
        self.project_id = project_id or str(uuid.uuid4())
        self.created_at = datetime.now()
        self.updated_at = self.created_at
        
        # Уровень 1: Фактические файлы (код, конфиги, документация)
        self.files: Dict[str, str] = {}
        
        # Уровень 2: Структурированные артефакты
        self.artifacts: Dict[str, List[Artifact]] = {
            "requirements": [],
            "architecture": [],
            "code": [],
            "tests": [],
            "documentation": [],
            "decisions": [],
            "review_report": [],
            "patch_diff": [],
            "git_export": [],
            "repro_manifest": [],
            "usage_report": [],
        }
        
        # Уровень 3: История изменений
        self.history: List[Dict[str, Any]] = []
        
        # Уровень 4: Метаданные и состояние
        self.state: ProjectState = ProjectState.RESEARCH
        self.target_architecture: Optional[Dict[str, Any]] = None
        self.current_task: Optional[str] = None
        self.progress: float = 0.0
        self.errors: List[str] = []
        self.metadata: Dict[str, Any] = {
            "version": "1.0.0-mvp",
            "iterations": 0,
            "active_role": None,
            "ai_models_used": [],
            "total_tokens": 0,
            "llm_usage": [],
            "template_id": None,
            "template_hash": None,
            "llm_usage_summary": {
                "total_tokens_in": 0,
                "total_tokens_out": 0,
                "by_stage": {},
                "models": {},
            },
        }
        self.file_update_hook: Optional[Callable[[str, Optional[Any]], None]] = None
        
        # Логируем создание контейнера
        self._add_history_entry("container_created", 
                               {"project_id": self.project_id})
    
    def add_file(self, filepath: str, content: str) -> None:
        """Добавить или обновить файл"""
        self.files[filepath] = content
        self.updated_at = datetime.now()
        self._add_history_entry("file_added", 
                               {"filepath": filepath, "size": len(content)})
        if self.file_update_hook:
            self.file_update_hook(filepath, content)

    def remove_file(self, filepath: str) -> None:
        """Удалить файл из контейнера"""
        if filepath not in self.files:
            return
        self.files.pop(filepath, None)
        self.updated_at = datetime.now()
        self._add_history_entry("file_removed", {"filepath": filepath})
        if self.file_update_hook:
            self.file_update_hook(filepath, None)
    
    def add_artifact(self, artifact_type: str, content: Any, 
                    created_by: str = "system") -> str:
        """Добавить артефакт в контейнер"""
        if artifact_type not in self.artifacts:
            self.artifacts[artifact_type] = []
        
        artifact = Artifact(
            type=artifact_type,
            content=content,
            created_by=created_by
        )
        
        self.artifacts[artifact_type].append(artifact)
        self.updated_at = datetime.now()
        
        self._add_history_entry("artifact_added", {
            "artifact_id": artifact.id,
            "type": artifact_type,
            "created_by": created_by
        })
        
        return artifact.id
    
    def get_relevant_context(self, role_name: str) -> Dict[str, Any]:
        """Получить релевантный контекст для конкретной роли"""
        context = {
            "project_id": self.project_id,
            "state": self.state.value,
            "progress": self.progress,
            "active_task": self.current_task
        }
        
        # Каждой роли - свой контекст
        if role_name == "researcher":
            context.update({
                "requirements": [a.content for a in self.artifacts.get("requirements", [])],
                "user_stories": [a.content for a in self.artifacts.get("user_stories", [])]
            })
        elif role_name == "designer":
            context.update({
                "requirements": [a.content for a in self.artifacts.get("requirements", [])],
                "existing_architecture": self.target_architecture
            })
        elif role_name == "coder":
            context.update({
                "architecture": self.target_architecture,
                "files": list(self.files.keys()),
                "recent_changes": self.history[-5:] if self.history else []
            })
        elif role_name == "reviewer":
            context.update({
                "files": self.files,
                "architecture": self.target_architecture,
                "requirements": [a.content for a in self.artifacts.get("requirements", [])]
            })
        
        return context
    
    def get_diff(self, target_architecture: Dict[str, Any]) -> List[str]:
        """Сравнить текущее состояние с целевой архитектурой"""
        diffs = []
        
        if not target_architecture:
            return diffs
        
        # Проверяем наличие требуемых компонентов
        if "components" in target_architecture:
            required_components = target_architecture.get("components", [])
            
            for component in required_components:
                component_name = component.get("name", "")
                expected_files = component.get("files", [])
                
                for filepath in expected_files:
                    if filepath not in self.files:
                        diffs.append(f"Missing file: {filepath} for component {component_name}")
        
        # Проверяем прогресс реализации
        if "progress_metrics" in target_architecture:
            metrics = target_architecture["progress_metrics"]
            current_progress = self._calculate_progress(metrics)
            
            if current_progress < 1.0:
                diffs.append(f"Progress incomplete: {current_progress:.0%}")
        
        return diffs
    
    def _calculate_progress(self, metrics: Dict[str, Any]) -> float:
        """Вычислить прогресс реализации"""
        if not self.files:
            return 0.0
        
        expected_files = metrics.get("expected_files", 10)
        actual_files = len(self.files)
        
        return min(actual_files / expected_files, 1.0)
    
    def is_complete(self) -> bool:
        """Проверить, завершен ли проект"""
        if self.state == ProjectState.COMPLETE:
            return True
        
        # Если есть целевая архитектура, проверяем по diff
        if self.target_architecture:
            diffs = self.get_diff(self.target_architecture)
            return len(diffs) == 0
        
        return False
    
    def update_state(self, new_state: ProjectState, 
                    task_description: Optional[str] = None) -> None:
        """Обновить состояние проекта"""
        old_state = self.state
        self.state = new_state
        
        if task_description:
            self.current_task = task_description
        
        self._add_history_entry("state_changed", {
            "from": old_state.value,
            "to": new_state.value,
            "task": task_description
        })
    
    def update_progress(self, progress: float) -> None:
        """Обновить прогресс выполнения"""
        self.progress = max(0.0, min(1.0, progress))
        self._add_history_entry("progress_updated", {"progress": self.progress})

    def record_llm_usage(
        self,
        *,
        stage: str,
        provider: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record LLM usage and update summary counters."""
        usage_entry = {
            "stage": stage,
            "provider": provider,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "total_tokens": tokens_in + tokens_out,
            "created_at": datetime.now().isoformat(),
        }
        if metadata:
            usage_entry["metadata"] = metadata
        self.metadata.setdefault("llm_usage", []).append(usage_entry)

        summary = self.metadata.setdefault(
            "llm_usage_summary",
            {"total_tokens_in": 0, "total_tokens_out": 0, "by_stage": {}, "models": {}},
        )
        summary["total_tokens_in"] += tokens_in
        summary["total_tokens_out"] += tokens_out

        stage_summary = summary["by_stage"].setdefault(
            stage,
            {"tokens_in": 0, "tokens_out": 0, "total_tokens": 0, "models": {}},
        )
        stage_summary["tokens_in"] += tokens_in
        stage_summary["tokens_out"] += tokens_out
        stage_summary["total_tokens"] += tokens_in + tokens_out
        stage_summary["models"][model] = stage_summary["models"].get(model, 0) + 1

        summary["models"][model] = summary["models"].get(model, 0) + 1
        self.metadata["total_tokens"] = summary["total_tokens_in"] + summary["total_tokens_out"]
        if model not in self.metadata.get("ai_models_used", []):
            self.metadata.setdefault("ai_models_used", []).append(model)
    
    def _add_history_entry(self, action: str, details: Dict[str, Any]) -> None:
        """Добавить запись в историю"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "details": details,
            "state": self.state.value,
            "progress": self.progress
        }
        self.history.append(entry)
        self.metadata["iterations"] += 1
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертировать контейнер в словарь для сериализации"""
        return {
            "project_id": self.project_id,
            "state": self.state.value,
            "files": self.files,
            "artifacts": {
                k: [asdict(a) for a in v] 
                for k, v in self.artifacts.items()
            },
            "history": self.history,
            "metadata": self.metadata,
            "progress": self.progress,
            "target_architecture": self.target_architecture,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Container':
        """Создать контейнер из словаря"""
        from datetime import datetime
        
        container = cls(data["project_id"])
        container.files = data["files"]
        container.state = ProjectState(data["state"])
        container.progress = data["progress"]
        container.metadata = data["metadata"]
        container.metadata.setdefault("llm_usage", [])
        container.metadata.setdefault(
            "llm_usage_summary",
            {"total_tokens_in": 0, "total_tokens_out": 0, "by_stage": {}, "models": {}},
        )
        container.metadata.setdefault("ai_models_used", [])
        container.metadata.setdefault("total_tokens", 0)
        container.target_architecture = data.get("target_architecture")
        container.history = data["history"]
        container.created_at = datetime.fromisoformat(data["created_at"])
        container.updated_at = datetime.fromisoformat(data["updated_at"])
        
        # Восстанавливаем артефакты
        for artifact_type, artifacts_list in data["artifacts"].items():
            container.artifacts[artifact_type] = [
                Artifact(
                    id=a["id"],
                    type=a["type"],
                    content=a["content"],
                    created_at=datetime.fromisoformat(a["created_at"]),
                    created_by=a["created_by"],
                    metadata=a["metadata"]
                )
                for a in artifacts_list
            ]
        
        return container


# Дополнительные модели для API
class AITask:
    """Задача для обработки ИИ"""
    def __init__(self, description: str, user_id: str):
        self.id = str(uuid.uuid4())
        self.description = description
        self.user_id = user_id
        self.status = "pending"
        self.created_at = datetime.now()
        self.results = {}
