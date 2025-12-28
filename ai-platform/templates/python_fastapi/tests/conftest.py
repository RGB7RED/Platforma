"""Test configuration for the FastAPI template."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import db  # noqa: E402
from main import app  # noqa: E402


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
