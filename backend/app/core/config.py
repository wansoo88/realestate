"""애플리케이션 설정.

원칙: **비밀값은 환경변수(.env)에서만 온다.** 기본값으로 비밀을 넣지 않는다.
설정이 잘못되면 조용히 약한 상태로 돌아가는 대신 **시작을 막는다.**
"""
from __future__ import annotations

import functools
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_role: str = "api"
    debug: bool = False

    # --- 보안 (기본값 없음 — 반드시 주입) ---
    jwt_secret: str = ""
    field_encryption_key: str = ""

    # --- Argon2id 비밀번호 해시 (SR8-1) ---
    # argon2-cffi 기본값은 64MiB·t=3·p=4 다. 해시 하나가 64MiB 를 잡으므로
    # 로그인 동시 5건이면 320MiB — 동거 서비스가 도는 소형 VPS 에서는 그것만으로
    # OOM 위험이다. OWASP 권장 하한(19MiB·t=2·p=1)으로 낮춘다.
    # ⚠️ 아래 OWASP 하한 미만으로 내리면 기동이 막힌다(security.py).
    #    메모리가 부족하면 파라미터를 더 낮추지 말고 **동시성**(argon2_concurrency)을 줄인다.
    argon2_memory_kib: int = 19456      # 19 MiB
    argon2_time_cost: int = 2
    argon2_parallelism: int = 1

    # 동시에 해시 연산에 들어갈 수 있는 요청 수. 이걸 안 걸면 FastAPI 의
    # 동기 엔드포인트 스레드풀(기본 40)이 전부 해시에 들어가 40×19MiB=760MiB 가 된다.
    # 4 × 19MiB ≈ 76MiB — 로그인 폭주가 와도 이만큼만 쓴다.
    argon2_concurrency: int = 4
    # 슬롯을 이만큼 기다려도 못 얻으면 503 으로 흘려보낸다(대기하다 전부 마비되는 대신).
    argon2_wait_timeout_sec: float = 2.0

    # --- DB / 캐시 ---
    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_db: str = "realestate"
    postgres_user: str = ""
    postgres_password: str = ""
    redis_url: str = "redis://redis:6379/0"

    # --- 외부 API ---
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-5"
    kakao_rest_api_key: str = ""
    molit_api_key: str = ""

    # --- 도메인 설정 ---
    tax_rules_path: Path = REPO_ROOT / "config" / "tax_rules.yaml"

    @property
    def database_url(self) -> str:
        return (f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}")

    def validate_runtime(self) -> list[str]:
        """운영 기동 전 점검. 문제가 있으면 목록을 돌려준다(빈 목록이면 정상)."""
        problems: list[str] = []
        if len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET 이 없거나 32자 미만입니다")
        if len(self.field_encryption_key) != 32:
            problems.append("FIELD_ENCRYPTION_KEY 는 정확히 32바이트여야 합니다")
        if not self.postgres_password:
            problems.append("POSTGRES_PASSWORD 가 비어 있습니다")
        if self.debug:
            problems.append("DEBUG 가 켜져 있습니다 — 운영에서는 꺼야 합니다")
        # Argon2 하한은 security.py 가 소유한다(그쪽이 실제로 강제하는 값이라
        # 여기서 숫자를 다시 적으면 언젠가 둘이 어긋난다).
        from app.core.security import argon2_parameter_problems
        problems.extend(argon2_parameter_problems(self))
        return problems


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()
