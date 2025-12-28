from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from fastapi.testclient import TestClient

TEMPLATE_ROOT = Path(__file__).resolve().parents[1]
spec = spec_from_file_location(
    "template_app_main", TEMPLATE_ROOT / "app" / "main.py"
)
module = module_from_spec(spec)
if spec and spec.loader:
    spec.loader.exec_module(module)
app = module.app


def test_root():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
