"""
Тесты для оркестратора
"""

import pytest
from unittest.mock import AsyncMock, patch
from app.orchestrator import AIOrchestrator
from app.agents import ParseError
from app.models import ProjectState


class TestAIOrchestrator:
    """Тесты для класса AIOrchestrator"""
    
    @pytest.fixture
    def orchestrator(self):
        """Фикстура оркестратора"""
        return AIOrchestrator()
    
    @pytest.fixture
    def mock_agents(self):
        """Фикстура моков агентов"""
        with patch('app.orchestrator.AIResearcher') as MockResearcher, \
             patch('app.orchestrator.AIDesigner') as MockDesigner, \
             patch('app.orchestrator.AICoder') as MockCoder, \
             patch('app.orchestrator.AIReviewer') as MockReviewer:
            
            # Создаем мок-агентов
            mock_researcher = AsyncMock()
            mock_designer = AsyncMock()
            mock_coder = AsyncMock()
            mock_reviewer = AsyncMock()
            
            # Настраиваем возвращаемые значения
            mock_researcher.execute.return_value = {"requirements": []}
            mock_designer.execute.return_value = {
                "components": [{"name": "Test", "files": ["test.py"]}]
            }
            mock_coder.execute.return_value = {"file": "test.py", "size": 100}
            mock_reviewer.execute.return_value = {"status": "approved", "passed": True}
            
            # Настраиваем классы моков
            MockResearcher.return_value = mock_researcher
            MockDesigner.return_value = mock_designer
            MockCoder.return_value = mock_coder
            MockReviewer.return_value = mock_reviewer
            
            yield {
                "researcher": mock_researcher,
                "designer": mock_designer,
                "coder": mock_coder,
                "reviewer": mock_reviewer,
                "mocks": [MockResearcher, MockDesigner, MockCoder, MockReviewer]
            }
    
    @pytest.mark.asyncio
    async def test_initialize_project(self, orchestrator):
        """Тест инициализации проекта"""
        container = orchestrator.initialize_project("Test Project")
        
        assert container is not None
        assert container.metadata["project_name"] == "Test Project"
        assert "started_at" in container.metadata
        assert len(orchestrator.roles) == 4
    
    @pytest.mark.asyncio
    async def test_process_task_success(self, orchestrator, mock_agents):
        """Тест успешной обработки задачи"""
        # Инициализируем проект
        orchestrator.initialize_project("Test")
        
        # Обрабатываем задачу
        result = await orchestrator.process_task("Create a test API")
        
        # Проверяем результат
        assert "status" in result
        assert "container_id" in result
        
        # Проверяем, что агенты были вызваны
        mock_agents["researcher"].execute.assert_called_once()
        mock_agents["designer"].execute.assert_called_once()
        mock_agents["coder"].execute.assert_called()
        mock_agents["reviewer"].execute.assert_called()
    
    @pytest.mark.asyncio
    async def test_process_task_error(self, orchestrator, mock_agents):
        """Тест обработки задачи с ошибкой"""
        # Настраиваем агента на ошибку
        mock_agents["researcher"].execute.side_effect = Exception("Test error")
        
        # Инициализируем проект
        orchestrator.initialize_project("Test")
        
        # Обрабатываем задачу (должна вернуть ошибку)
        result = await orchestrator.process_task("Create a test API")
        
        # Проверяем результат ошибки
        assert result["status"] == "error"
        assert "error" in result
        assert "Test error" in result["error"]

    @pytest.mark.asyncio
    async def test_process_task_final_review_warning_success(self, orchestrator, mock_agents):
        """Финальное ревью с предупреждениями не должно помечать задачу как failed"""
        orchestrator.initialize_project("Test")

        mock_agents["designer"].execute.return_value = {"components": []}
        mock_agents["reviewer"].execute.return_value = {
            "status": "approved_with_warnings",
            "passed": True,
            "warnings": ["warning"],
        }

        result = await orchestrator.process_task("Create a test API")

        assert result["status"] == "completed"
        assert result["status"] != "failed"
        assert orchestrator.container.state == ProjectState.COMPLETE

    @pytest.mark.asyncio
    async def test_process_task_final_review_failure(self, orchestrator, mock_agents):
        """Финальное ревью с ошибками должно помечать задачу как failed"""
        orchestrator.initialize_project("Test")

        mock_agents["designer"].execute.return_value = {"components": []}
        mock_agents["reviewer"].execute.return_value = {
            "status": "rejected",
            "passed": False,
            "errors": ["ruff failed"],
        }

        result = await orchestrator.process_task("Create a test API")

        assert result["status"] == "failed"
        assert orchestrator.container.state == ProjectState.ERROR

    @pytest.mark.asyncio
    async def test_llm_invalid_json_retry_once(self, orchestrator, mock_agents, monkeypatch):
        """Неверный JSON от LLM приводит к контролируемому отказу после одной попытки"""
        orchestrator.initialize_project("Test")
        monkeypatch.setenv("LLM_MAX_CALLS_PER_TASK", "10")
        monkeypatch.setenv("LLM_MAX_RETRIES_PER_STEP", "1")

        mock_agents["coder"].execute.side_effect = [
            ParseError("llm_invalid_json", raw_text="bad", error="boom"),
            ParseError("llm_invalid_json", raw_text="still bad", error="boom"),
        ]

        result = await orchestrator.process_task("Create a test API")

        assert result["status"] == "failed"
        assert result["failure_reason"].startswith("llm_invalid_json:")
        assert mock_agents["coder"].execute.call_count == 2

    @pytest.mark.asyncio
    async def test_llm_call_budget_exhausted(self, orchestrator, mock_agents, monkeypatch):
        """Проверка остановки по лимиту LLM вызовов"""
        orchestrator.initialize_project("Test")
        monkeypatch.setenv("LLM_MAX_CALLS_PER_TASK", "1")
        monkeypatch.setenv("LLM_MAX_RETRIES_PER_STEP", "1")

        mock_agents["coder"].execute.side_effect = [
            ParseError("llm_invalid_json", raw_text="bad", error="boom"),
        ]

        result = await orchestrator.process_task("Create a test API")

        assert result["status"] == "failed"
        assert result["failure_reason"] == "llm_budget_exhausted"
        assert mock_agents["coder"].execute.call_count == 1

    @pytest.mark.asyncio
    async def test_max_iterations_enforced(self, orchestrator, mock_agents, monkeypatch):
        """Проверка соблюдения лимита итераций"""
        orchestrator.codex["workflow"]["max_iterations"] = 2
        orchestrator.initialize_project("Test")
        monkeypatch.setenv("LLM_MAX_CALLS_PER_TASK", "10")
        monkeypatch.setenv("LLM_MAX_RETRIES_PER_STEP", "1")

        mock_agents["designer"].execute.return_value = {
            "components": [{"name": "Test", "files": ["test.py"]}]
        }
        mock_agents["reviewer"].execute.return_value = {"status": "rejected", "passed": False}

        result = await orchestrator.process_task("Create a test API")

        assert result["failure_reason"] == "max_iterations_exhausted"
        assert result["iterations"] == 2
        assert orchestrator.container.metadata["iterations"] == 2
        assert mock_agents["coder"].execute.call_count == 2
    
    @pytest.mark.asyncio
    async def test_get_next_task(self, orchestrator):
        """Тест получения следующей задачи"""
        # Инициализируем проект
        orchestrator.initialize_project("Test")
        
        # Без архитектуры задача не должна быть создана
        task = orchestrator._get_next_task()
        assert task is None
        
        # Устанавливаем архитектуру
        orchestrator.container.target_architecture = {
            "components": [
                {"name": "Test", "files": ["test.py", "test2.py"]}
            ]
        }
        
        # Теперь должна быть создана задача
        task = orchestrator._get_next_task()
        assert task is not None
        assert task["type"] == "implement_component"
        assert "test.py" in task["file"]
    
    @pytest.mark.asyncio
    async def test_save_and_load_container(self, orchestrator, tmp_path):
        """Тест сохранения и загрузки контейнера"""
        # Инициализируем проект
        container = orchestrator.initialize_project("Test")
        container.add_file("test.txt", "Hello")
        
        # Сохраняем контейнер
        filepath = tmp_path / "container.json"
        orchestrator.save_container(str(filepath))
        
        # Проверяем, что файл создан
        assert filepath.exists()
        
        # Загружаем контейнер
        loaded_container = orchestrator.load_container(str(filepath))
        
        # Проверяем восстановление
        assert loaded_container.project_id == container.project_id
        assert loaded_container.files == container.files
    
    def test_get_metrics(self, orchestrator):
        """Тест получения метрик"""
        # Инициализируем проект
        orchestrator.initialize_project("Test")
        
        # Добавляем историю задач
        orchestrator.task_history = [
            {"status": "completed"},
            {"status": "failed"},
            {"status": "completed"}
        ]
        
        # Получаем метрики
        metrics = orchestrator.get_metrics()
        
        # Проверяем метрики
        assert metrics["tasks_processed"] == 3
        assert metrics["successful_tasks"] == 2
        assert metrics["failed_tasks"] == 1
        assert metrics["current_container"] is not None
        assert "researcher" in metrics["active_roles"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
