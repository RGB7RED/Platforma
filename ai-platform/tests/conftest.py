"""Test configuration for repo-root tests."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from todo_main import app  # noqa: E402


def test_client() -> TestClient:
    """Provide a TestClient for integration tests."""
    return TestClient(app)
