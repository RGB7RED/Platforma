"""Test configuration for the FastAPI template."""

import pytest
from fastapi.testclient import TestClient

from database import db
from main import app


@pytest.fixture(autouse=True)
def reset_database():
    """Reset the in-memory database for each test."""
    db.reset()
    yield
    db.reset()


@pytest.fixture
def client() -> TestClient:
    """Provide a FastAPI test client."""
    return TestClient(app)
