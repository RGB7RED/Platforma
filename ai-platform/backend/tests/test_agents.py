"""
Тесты для ИИ-агентов
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from app.agents import AIResearcher, AIDesigner, AICoder, AIReviewer
from app.models import Container


class TestAIAgents:
    """Тесты для ИИ-агентов"""
    
    @pytest.fixture
    def codex(self):
        """Фикстура кодекса"""
        return {
            "version": "1.0.0-test",
            "rules": {
                "researcher": {"max_questions": 3},
                "designer": {},
                "coder": {"testing_required": True},
                "reviewer": {"checklist": ["test"]}
            }
        }
    
    @pytest.fixture
    def container(self):
        """Фикстура контейнера"""
        return Container("test-project")
    
    @pytest.mark.asyncio
    async def test_researcher_execute(self, codex, container):
        """Тест выполнения исследователя"""
        researcher = AIResearcher(codex)
        result = await researcher.execute("Test task", container)
        
        # Проверяем результат
        assert "user_task" in result
        assert "requirements" in result
        assert "user_stories" in result
        
        # Проверяем, что артефакты добавлены в контейнер
        assert len(container.artifacts["requirements"]) == 1
        assert "requirements.md" in container.files
        assert "user_stories.md" in container.files
    
    @pytest.mark.asyncio
    async def test_designer_execute(self, codex, container):
        """Тест выполнения проектировщика"""
        # Сначала нужно добавить требования
        container.add_artifact("requirements", {
            "requirements": [],
            "user_stories": []
        }, "test")
        
        designer = AIDesigner(codex)
        result = await designer.execute(container)
        
        # Проверяем результат
        assert "name" in result
        assert "components" in result
        assert "api_endpoints" in result
        
        # Проверяем, что контейнер обновлен
        assert container.target_architecture == result
        assert "architecture.md" in container.files
        assert "implementation_plan.md" in container.files
    
    @pytest.mark.asyncio
    async def test_coder_execute(self, codex, container):
        """Тест выполнения кодера"""
        coder = AICoder(codex)
        
        # Тестовая задача
        task = {
            "type": "implement_component",
            "component": "API",
            "file": "main.py",
            "description": "Implement main.py"
        }
        
        result = await coder.execute(task, container)
        
        # Проверяем результат
        assert "file" in result
        assert result["file"] == "main.py"
        assert "size" in result
        
        # Проверяем, что файл добавлен в контейнер
        assert "main.py" in container.files
        assert len(container.artifacts["code"]) == 1
    
    @pytest.mark.asyncio
    async def test_coder_generate_code(self, codex):
        """Тест генерации кода"""
        coder = AICoder(codex)
        
        # Тестируем генерацию main.py
        code = coder._generate_main_py()
        assert "FastAPI" in code
        assert "Todo API" in code
        
        # Тестируем генерацию модели
        model_code = coder._generate_todo_model()
        assert "Todo" in model_code
        assert "BaseModel" in model_code
        
        # Тестируем генерацию тестов
        test_code = coder._generate_api_tests()
        assert "TestTodoAPI" in test_code
        assert "test_" in test_code
    
    @pytest.mark.asyncio
    async def test_reviewer_execute(self, codex, container):
        """Тест выполнения ревьюера"""
        # Добавляем тестовые файлы
        container.add_file("test.py", "def test():\n    pass\n")
        container.add_file("test_no_docs.py", "x = 1\n" * 150)  # Длинные строки
        
        reviewer = AIReviewer(codex)
        result = await reviewer.execute(container)
        
        # Проверяем результат
        assert "status" in result
        assert "issues" in result
        assert "warnings" in result
        assert "files_reviewed" in result
        
        # Проверяем, что ревью добавлен в артефакты
        assert len(container.artifacts["reviews"]) == 1
    
    def test_reviewer_file_review(self, codex):
        """Тест проверки файла"""
        reviewer = AIReviewer(codex)
        
        # Тестовый файл с длинными строками
        content = "x" * 200 + "\n" + "y" * 150 + "\n" + "z" * 100
        issues, warnings, passed = reviewer._review_file("test.py", content)
        
        # Должны быть предупреждения о длинных строках
        assert len(warnings) > 0
        assert any("too long" in w.lower() for w in warnings)
    
    def test_researcher_generate_markdown(self, codex):
        """Тест генерации Markdown исследователем"""
        researcher = AIResearcher(codex)
        
        requirements = {
            "user_task": "Test task",
            "requirements": [
                {"id": "REQ-1", "description": "Test", "priority": "high", "category": "func"}
            ],
            "user_stories": ["Story 1"],
            "technical_constraints": ["Python"],
            "assumptions": ["Test assumption"],
            "questions_to_user": ["Question 1"],
            "analyzed_at": "2024-01-01"
        }
        
        md = researcher._generate_markdown(requirements)
        
        # Проверяем структуру Markdown
        assert "# Requirements Analysis" in md
        assert "## Original Task" in md
        assert "## Requirements" in md
        assert "## User Stories" in md
        assert "REQ-1" in md


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
