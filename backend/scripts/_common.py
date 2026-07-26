"""운영 스크립트 공통 배선 — 로깅 · .env 로딩 · DB 엔진 · 경로.

왜 별도 모듈인가
----------------
수집·검증·지오코딩 스크립트가 전부 같은 것들을 필요로 한다:
(1) 저장소 루트의 `.env` (비밀은 코드·이미지에 없다 — security.md §2),
(2) DB 엔진,
(3) **비밀이 새지 않는 로깅**.
각자 구현하면 "이 스크립트만 .env 를 못 읽는다" / "이 스크립트만 키를 찍는다" 사고가 난다.

⚠️ 이 모듈은 **비밀값을 절대 출력하지 않는다.** DSN 을 찍어야 할 일이 있으면
   `safe_dsn()` 로 비밀번호를 가린 문자열을 쓴다.

SR17-3 — 로깅 설정은 "부르면 되는 것"이 아니라 **import 하면 걸리는 것**이다
----------------------------------------------------------------------
예전에는 스크립트가 각자 `configure_logging()` 을 불러야 했고, 7개 중 2개만 불렀다.
부르지 않은 `verify_region_codes.py` 는 MOLIT 인증키를 쿼리스트링으로 보내면서도
억제가 없었다(찍히지 않은 건 루트 로거가 미설정이라 운 좋게 버려졌을 뿐이다).
그래서 지금은 **이 모듈을 import 하는 순간** 로깅 억제·마스킹이 설치된다.
모든 스크립트가 `_common` 을 거치므로(`tests/test_script_hygiene.py` 가 강제한다)
빠뜨릴 수 있는 구멍이 없다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.masking import install_log_masking, mask_secrets  # noqa: E402

__all__ = [
    "BACKEND_DIR", "REPO_ROOT", "configure_logging", "database_url", "load_env",
    "make_engine", "mask_secrets", "require", "safe_dsn",
]

#: 요청 URL 을 통째로 INFO 로 찍는 라이브러리들. 공공데이터포털은 **인증키를 쿼리스트링에
#: 실어 보내므로**(`serviceKey=...`), 이걸 켠 채로 수집을 돌리면 로그·터미널·CI 산출물에
#: 키가 그대로 남는다. 운영 스크립트는 항상 이 로거들을 WARNING 으로 낮춘다.
#: ⚠️ 이건 **보조** 방어다. 주 방어는 `app.core.masking` 의 구조적 마스킹이다 —
#:    레벨을 낮추는 것만으로는 예외 메시지·print 경로를 못 막는다(SR17-1).
_URL_LOGGING_LIBS = ("httpx", "httpcore", "urllib3", "anthropic")


def configure_logging(level: int | str = "INFO") -> None:
    """스크립트 로깅 설정. **비밀이 문자열로 새는 경로를 먼저 막는다.**

    멱등하다. 모듈 import 시 기본값으로 한 번 돌고, 스크립트가 레벨을 바꾸고 싶으면
    다시 부르면 된다.
    """
    import logging

    logging.basicConfig(level=level,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # basicConfig 는 핸들러가 이미 있으면 아무것도 하지 않는다(레벨도 안 바꾼다).
    # 두 번째 호출에서도 레벨이 먹도록 루트에 직접 건다.
    logging.getLogger().setLevel(level)
    for name in _URL_LOGGING_LIBS:
        logging.getLogger(name).setLevel(logging.WARNING)
    install_log_masking()


def load_env(path: Path | None = None) -> Path | None:
    """저장소 루트 `.env` 를 프로세스 환경에 싣는다. 이미 있는 값은 덮지 않는다."""
    env_path = Path(path or (REPO_ROOT / ".env"))
    if not env_path.exists():
        return None
    try:
        from dotenv import load_dotenv
    except ImportError:                                  # pragma: no cover - 운영 venv 에는 있다
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        return env_path
    load_dotenv(env_path, override=False)
    return env_path


def database_url() -> str:
    """DB DSN.

    우선순위: `DATABASE_URL` > `POSTGRES_*` 조합.
    ⚠️ `POSTGRES_HOST` 는 컨테이너 안에서 쓰는 서비스명(`db`)이라 호스트에서 실행할 때는
       `DATABASE_URL` 로 컨테이너 IP 를 넘겨야 한다(포트는 의도적으로 미개방 — security.md).
    """
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return url
    from urllib.parse import quote

    user = os.getenv("POSTGRES_USER", "")
    pw = quote(os.getenv("POSTGRES_PASSWORD", ""), safe="")
    host = os.getenv("POSTGRES_HOST", "db")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "realestate")
    return f"postgresql+psycopg://{user}:{pw}@{host}:{port}/{db}"


def safe_dsn(url: str) -> str:
    """로그·보고용 DSN. 비밀번호를 `***` 로 가린다."""
    import re

    return re.sub(r"://([^:/@]*):[^@]*@", r"://\1:***@", url)


def make_engine(url: str | None = None) -> Any:
    from sqlalchemy import create_engine

    return create_engine(url or database_url(), pool_pre_ping=True)


def require(name: str) -> str:
    """필수 환경변수. 없으면 '도는 척' 하지 않고 즉시 멈춘다(가짜 성공 금지)."""
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"[FAIL] {name} 이(가) 필요합니다 — .env 를 확인하세요.")
    return value


# ⚠️ import 만으로 로깅 억제·마스킹이 걸린다(SR17-3). 스크립트가 부르는 것을 잊어도
#    구멍이 생기지 않게 하려는 의도적인 import 부작용이다.
configure_logging()
