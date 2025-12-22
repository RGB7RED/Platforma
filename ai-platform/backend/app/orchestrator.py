"""
Оркестратор - управляет полным циклом выполнения задачи через роли ИИ.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

from .models import Container, ProjectState
from .agents import AIResearcher, AIDesigner, AICoder, AIReviewer


# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AIOrchestrator:
    """Главный оркестратор, управляющий циклом ИИ-ролей"""
    
    def __init__(self, codex_path: Optional[str] = None):
        self.codex = self._load_codex(codex_path)
        self.container: Optional[Container] = None
        self.roles = {}
        self.task_history: List[Dict] = []
        
        logger.info(f"Orchestrator initialized with Codex v{self.codex.get('version', 'unknown')}")
    
    def _load_codex(self, codex_path: Optional[str]) -> Dict[str, Any]:
        """Загрузить кодекс из файла или использовать дефолтный"""
        if codex_path and Path(codex_path).exists():
            try:
                with open(codex_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading codex: {e}")
        
        # Дефолтный кодекс
        return {
            "version": "1.0.0-default",
            "rules": {
                "researcher": {"max_questions": 3},
                "coder": {"testing_required": True}
            }
        }
    
    def initialize_project(self, project_name: str) -> Container:
        """Инициализировать новый проект"""
        self.container = Container()
        self.container.metadata["project_name"] = project_name
        self.container.metadata["started_at"] = datetime.now().isoformat()
        
        # Инициализация ролей
        self.roles = {
            "researcher": AIResearcher(self.codex),
            "designer": AIDesigner(self.codex),
            "coder": AICoder(self.codex),
            "reviewer": AIReviewer(self.codex)
        }
        
        logger.info(f"Project '{project_name}' initialized with ID: {self.container.project_id}")
        return self.container
    
    async def process_task(self, user_task: str) -> Dict[str, Any]:
        """Основной метод обработки задачи пользователя"""
        if not self.container:
            self.initialize_project("Auto-generated Project")
        
        logger.info(f"Starting processing of task: {user_task[:50]}...")
        
        try:
            # Фаза 1: Исследование
            logger.info("Phase 1: Research")
            self.container.update_state(ProjectState.RESEARCH, "Analyzing requirements")
            
            researcher_result = await self.roles["researcher"].execute(
                user_task, 
                self.container
            )
            
            self.container.add_artifact(
                "research_summary",
                researcher_result,
                "researcher"
            )
            
            # Фаза 2: Проектирование
            logger.info("Phase 2: Design")
            self.container.update_state(ProjectState.DESIGN, "Creating architecture")
            
            design_result = await self.roles["designer"].execute(
                self.container
            )
            
            self.container.target_architecture = design_result
            self.container.add_artifact(
                "architecture",
                design_result,
                "designer"
            )
            
            # Фаза 3: Итеративная реализация
            logger.info("Phase 3: Implementation")
            self.container.update_state(ProjectState.IMPLEMENTATION, "Implementing solution")
            
            iteration = 0
            max_iterations = 15  # Защита от бесконечного цикла
            
            while not self.container.is_complete() and iteration < max_iterations:
                iteration += 1
                logger.info(f"Implementation iteration {iteration}")
                
                # 3.1 Получаем следующую задачу от планировщика
                next_task = self._get_next_task()
                if not next_task:
                    logger.warning("No tasks to execute")
                    break
                
                self.container.current_task = next_task["description"]
                self.container.metadata["active_role"] = "coder"
                
                # 3.2 Кодер выполняет задачу
                coder_result = await self.roles["coder"].execute(
                    next_task,
                    self.container
                )
                
                # 3.3 Ревьюер проверяет результат
                self.container.metadata["active_role"] = "reviewer"
                review_result = await self.roles["reviewer"].execute(
                    self.container
                )
                
                if review_result["status"] == "approved":
                    logger.info(f"Iteration {iteration} approved")
                    self.container.update_progress(iteration / max_iterations)
                else:
                    logger.warning(f"Iteration {iteration} rejected: {review_result.get('issues', [])}")
                    # В MVP просто продолжаем, в реальной системе - корректируем
            
            # Фаза 4: Финальное ревью
            logger.info("Phase 4: Final Review")
            self.container.update_state(ProjectState.REVIEW, "Final quality check")
            
            final_review = await self.roles["reviewer"].execute(
                self.container
            )
            
            if final_review["status"] == "approved":
                self.container.update_state(ProjectState.COMPLETE, "Project completed")
                self.container.update_progress(1.0)
                logger.info("Project completed successfully")
            else:
                logger.error(f"Project failed final review: {final_review.get('issues')}")
                self.container.update_state(ProjectState.ERROR, "Failed final review")
            
            # Сохраняем историю задачи
            self.task_history.append({
                "task": user_task,
                "status": self.container.state.value,
                "iterations": iteration,
                "timestamp": datetime.now().isoformat()
            })
            
            return {
                "status": "completed" if self.container.state == ProjectState.COMPLETE else "failed",
                "container_id": self.container.project_id,
                "state": self.container.state.value,
                "progress": self.container.progress,
                "files_count": len(self.container.files),
                "artifacts_count": sum(len(a) for a in self.container.artifacts.values()),
                "iterations": iteration,
                "history": self.task_history[-5:]  # Последние 5 задач
            }
            
        except Exception as e:
            logger.error(f"Error processing task: {e}", exc_info=True)
            if self.container:
                self.container.update_state(ProjectState.ERROR, f"Processing error: {str(e)}")
                self.container.errors.append(str(e))
            
            return {
                "status": "error",
                "error": str(e),
                "container_id": self.container.project_id if self.container else None
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
