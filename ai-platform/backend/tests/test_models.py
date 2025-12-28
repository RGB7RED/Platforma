"""
Тесты для моделей данных
"""

import pytest
from datetime import datetime
from app.models import Container, Artifact, ProjectState


class TestArtifact:
    """Тесты для класса Artifact"""
    
    def test_artifact_creation(self):
        """Тест создания артефакта"""
        artifact = Artifact(
            type="requirement",
            content="Test requirement",
            created_by="tester"
        )
        
        assert artifact.type == "requirement"
        assert artifact.content == "Test requirement"
        assert artifact.created_by == "tester"
        assert artifact.id is not None
        assert isinstance(artifact.created_at, datetime)
    
    def test_artifact_defaults(self):
        """Тест значений по умолчанию"""
        artifact = Artifact()
        
        assert artifact.type == ""
        assert artifact.content is None
        assert artifact.created_by == ""
        assert artifact.metadata == {}


class TestContainer:
    """Тесты для класса Container"""
    
    @pytest.fixture
    def container(self):
        """Фикстура контейнера"""
        return Container("test-project")
    
    def test_container_creation(self):
        """Тест создания контейнера"""
        container = Container()
        
        assert container.project_id is not None
        assert container.state == ProjectState.RESEARCH
        assert container.progress == 0.0
        assert container.files == {}
        assert len(container.history) > 0
    
    def test_add_file(self, container):
        """Тест добавления файла"""
        container.add_file("test.txt", "Hello, World!")
        
        assert "test.txt" in container.files
        assert container.files["test.txt"] == "Hello, World!"
        assert len(container.history) == 2  # 1 создание + 1 добавление файла
    
    def test_add_artifact(self, container):
        """Тест добавления артефакта"""
        artifact_id = container.add_artifact(
            "requirements",
            {"req": "Test requirement"},
            "tester"
        )
        
        assert artifact_id is not None
        assert len(container.artifacts["requirements"]) == 1
        assert container.artifacts["requirements"][0].content["req"] == "Test requirement"
    
    def test_get_relevant_context(self, container):
        """Тест получения контекста для ролей"""
        # Добавляем тестовые данные
        container.add_artifact("requirements", "Test requirement", "tester")
        container.state = ProjectState.DESIGN
        
        context = container.get_relevant_context("designer")
        
        assert context["project_id"] == container.project_id
        assert context["state"] == "design"
        assert "requirements" in context
    
    def test_is_complete(self, container):
        """Тест проверки завершенности"""
        # Пустой контейнер не завершен
        assert not container.is_complete()
        
        # Контейнер в состоянии COMPLETE завершен
        container.state = ProjectState.COMPLETE
        assert container.is_complete()
    
    def test_to_dict_from_dict(self, container):
        """Тест сериализации и десериализации"""
        # Добавляем тестовые данные
        container.add_file("test.txt", "Hello")
        container.add_artifact("test", {"key": "value"}, "tester")
        container.state = ProjectState.COMPLETE
        container.progress = 1.0
        
        # Конвертируем в словарь
        data = container.to_dict()
        
        # Проверяем структуру
        assert "project_id" in data
        assert "files" in data
        assert "artifacts" in data
        assert data["state"] == "complete"
        assert data["progress"] == 1.0
        
        # Восстанавливаем из словаря
        new_container = Container.from_dict(data)
        
        # Проверяем восстановление
        assert new_container.project_id == container.project_id
        assert new_container.files == container.files
        assert new_container.state == container.state
        assert new_container.progress == container.progress
    
    def test_update_state(self, container):
        """Тест обновления состояния"""
        container.update_state(ProjectState.DESIGN, "Design phase")
        
        assert container.state == ProjectState.DESIGN
        assert container.current_task == "Design phase"
        
        # Проверяем запись в истории
        last_entry = container.history[-1]
        assert last_entry["action"] == "state_changed"
        assert last_entry["details"]["to"] == "design"
    
    def test_update_progress(self, container):
        """Тест обновления прогресса"""
        container.update_progress(0.5)
        
        assert container.progress == 0.5
        
        # Прогресс не может быть меньше 0
        container.update_progress(-0.1)
        assert container.progress == 0.0
        
        # Прогресс не может быть больше 1
        container.update_progress(1.5)
        assert container.progress == 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
