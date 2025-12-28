from pathlib import Path
import sys

TEMPLATE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TEMPLATE_ROOT))
sys.modules.pop("cli", None)
