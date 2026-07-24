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
        return problems


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()
