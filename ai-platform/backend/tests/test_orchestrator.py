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
             patch('app.orchestrator.AIPlanner') as MockPlanner, \
             patch('app.orchestrator.AICoder') as MockCoder, \
             patch('app.orchestrator.AIReviewer') as MockReviewer:
            
            # Создаем мок-агентов
            mock_researcher = AsyncMock()
            mock_designer = AsyncMock()
            mock_planner = AsyncMock()
            mock_coder = AsyncMock()
            mock_reviewer = AsyncMock()

            # Настраиваем возвращаемые значения
            async def _researcher_execute(task, container):
                container.add_artifact("requirements", {"requirements": []}, "researcher")
                return {"requirements": []}

            mock_researcher.execute.side_effect = _researcher_execute
            mock_designer.execute.return_value = {
                "components": [{"name": "Test", "files": ["test.py"]}]
            }
            async def _planner_execute(container):
                plan_version = int(container.metadata.get("plan_version", 0) or 0) + 1
                container.metadata["plan_version"] = plan_version
                container.metadata["plan_step_index"] = 0
                return {
                    "plan_version": plan_version,
                    "steps": [
                        {
                            "id": "create_structure",
                            "goal": "Create structure",
                            "files": ["test.py"],
                            "acceptance_criteria": ["Structure exists"],
                            "commands": ["pytest"],
                        }
                    ],
                    "order": ["create_structure"],
                }

            mock_planner.execute.side_effect = _planner_execute
            mock_coder.execute.return_value = {"file": "test.py", "size": 100}
            mock_reviewer.execute.return_value = {"status": "approved", "passed": True}
            
            # Настраиваем классы моков
            MockResearcher.return_value = mock_researcher
            MockDesigner.return_value = mock_designer
            MockPlanner.return_value = mock_planner
            MockCoder.return_value = mock_coder
            MockReviewer.return_value = mock_reviewer
            
            yield {
                "researcher": mock_researcher,
                "designer": mock_designer,
                "planner": mock_planner,
                "coder": mock_coder,
                "reviewer": mock_reviewer,
                "mocks": [MockResearcher, MockDesigner, MockPlanner, MockCoder, MockReviewer]
            }
    
    @pytest.mark.asyncio
    async def test_initialize_project(self, orchestrator):
        """Тест инициализации проекта"""
        container = orchestrator.initialize_project("Test Project")
        
        assert container is not None
        assert container.metadata["project_name"] == "Test Project"
        assert "started_at" in container.metadata
        assert {
            "researcher",
            "interviewer",
            "designer",
            "planner",
            "coder",
            "reviewer",
        }.issubset(set(orchestrator.roles))
    
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
        mock_agents["planner"].execute.assert_called()
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

        mock_agents["planner"].execute.return_value = {
            "plan_version": 1,
            "steps": [
                {
                    "id": "create_structure",
                    "goal": "Create structure",
                    "files": ["test.py"],
                    "acceptance_criteria": ["Structure exists"],
                    "commands": ["pytest"],
                }
            ],
            "order": ["create_structure"],
        }
        mock_agents["designer"].execute.return_value = {"components": []}
        mock_agents["reviewer"].execute.return_value = {
            "status": "rejected",
            "passed": False,
            "errors": ["ruff failed"],
        }

        result = await orchestrator.process_task(
            "Create a test API",
            manual_step_enabled=False,
        )

        assert result["status"] == "failed"
        assert orchestrator.container.state == ProjectState.ERROR

    @pytest.mark.asyncio
    async def test_review_failure_reroutes_to_planning(self, orchestrator, mock_agents, monkeypatch):
        """Провал финального ревью возвращает на planning и повторяет implementation."""
        orchestrator.initialize_project("Test")
        monkeypatch.setenv("ORCH_MAX_REVIEW_CYCLES", "2")

        stages = []

        async def handle_stage_started(payload):
            stages.append(payload.get("stage"))

        mock_agents["designer"].execute.return_value = {"components": []}
        mock_agents["coder"].execute.return_value = {"file": "test.py", "size": 100}
        mock_agents["reviewer"].execute.side_effect = [
            {"status": "approved", "passed": True},
            {"status": "rejected", "passed": False, "errors": ["fail"]},
            {"status": "approved", "passed": True},
            {"status": "approved", "passed": True},
        ]

        result = await orchestrator.process_task(
            "Create a test API",
            callbacks={"stage_started": handle_stage_started},
        )

        assert result["status"] == "completed"
        assert mock_agents["planner"].execute.call_count == 2
        assert orchestrator.container.metadata.get("plan_version") == 2
        assert mock_agents["coder"].execute.call_count >= 2
        assert stages.count("planning") == 2
        second_planning_index = stages.index("planning", stages.index("planning") + 1)
        assert "review" in stages[:second_planning_index]

    @pytest.mark.asyncio
    async def test_process_task_manual_gate_after_review(self, orchestrator, mock_agents, monkeypatch):
        """Manual step should pause after iteration review when enabled."""
        monkeypatch.setenv("MANUAL_STEP_ENABLED", "true")
        orchestrator.initialize_project("Test")

        result = await orchestrator.process_task("Create a test API")

        assert result["status"] == "needs_input"
        assert result["awaiting_manual_step"] is True
        assert result["manual_step_stage"] == "post_iteration_review"

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
    async def test_llm_token_budget_exceeded(self, orchestrator, mock_agents, monkeypatch):
        """Проверка остановки по лимиту токенов на задачу"""
        orchestrator.initialize_project("Test")
        monkeypatch.setenv("LLM_MAX_TOTAL_TOKENS_PER_TASK", "1")
        monkeypatch.setenv("LLM_MAX_RETRIES_PER_STEP", "0")

        mock_agents["designer"].execute.return_value = {
            "components": [{"name": "Test", "files": ["test.py"]}]
        }
        task_description = "Create structure"
        orchestrator.container.metadata["llm_usage"] = [
            {
                "stage": "implementation",
                "provider": "openai",
                "model": "gpt-4o-mini",
                "tokens_in": 1,
                "tokens_out": 0,
                "total_tokens": 1,
                "created_at": "now",
                "metadata": {"task_description": task_description},
            }
        ]

        result = await orchestrator.process_task("Create a test API")

        assert result["status"] == "failed"
        assert result["failure_reason"] == "llm_budget_exceeded"
        assert mock_agents["coder"].execute.call_count == 0

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
    async def test_micro_task_skips_project_stages(self, monkeypatch):
        """Micro задачи должны обходить research/design/review стадии."""
        monkeypatch.setenv("LLM_PROVIDER", "mock")
        monkeypatch.setenv("ORCH_MICRO_MAX_ITERATIONS", "2")
        task_text = (
            "Return EXACTLY this JSON: "
            "{\"files\":[{\"path\":\"micro.txt\",\"content\":\"hello\"}]}"
        )

        with patch("app.orchestrator.AIResearcher") as MockResearcher, \
             patch("app.orchestrator.AIDesigner") as MockDesigner, \
             patch("app.orchestrator.AIReviewer") as MockReviewer:
            mock_researcher = AsyncMock()
            mock_designer = AsyncMock()
            mock_reviewer = AsyncMock()
            MockResearcher.return_value = mock_researcher
            MockDesigner.return_value = mock_designer
            MockReviewer.return_value = mock_reviewer

            orchestrator = AIOrchestrator()
            orchestrator.initialize_project("Micro Test")

            result = await orchestrator.process_task(task_text)

            assert result["status"] == "completed"
            assert result["files_count"] == 1
            assert orchestrator.container.metadata["iterations"] <= 2
            mock_researcher.execute.assert_not_called()
            mock_designer.execute.assert_not_called()
            mock_reviewer.execute.assert_not_called()
    
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
