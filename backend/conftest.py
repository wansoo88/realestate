"""pytest 부트스트랩 — backend/ 를 import 경로에 넣어 `app.*` 를 찾게 한다."""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
