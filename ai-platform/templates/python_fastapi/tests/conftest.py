"""Test configuration for the FastAPI template."""

import sys
from pathlib import Path

TEMPLATE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TEMPLATE_ROOT))
