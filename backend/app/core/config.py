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

    # --- refresh 쿠키 (SR15-1 / security.md §2.1) ---
    # refresh 토큰은 **응답 본문에 넣지 않는다.** `httpOnly` 쿠키로만 오간다.
    # 문제는 `Secure` 다: 브라우저는 `Secure` 쿠키를 http 응답에서 아예 저장하지 않으므로
    # `http://localhost` 로 개발할 때 로그인 흐름 자체가 막힌다.
    # 그래서 설정으로 분기하되 **끄는 것은 DEBUG 에서만** 허용한다
    # (`refresh_cookie_secure` 가 운영에서 강제 True 로 되돌린다).
    cookie_secure: bool = True

    # --- DB / 캐시 ---
    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_db: str = "realestate"
    postgres_user: str = ""
    postgres_password: str = ""
    redis_url: str = "redis://redis:6379/0"
    #: 서버측 쿼리 상한(ms). API·워커가 쓰는 엔진에만 걸린다(SR24-4).
    #: 0 으로 끌 수 있게 두지만 **끄지 말 것** — 한 번의 평범한 조회가 192m 짜리 db
    #: 컨테이너를 눕힐 수 있고, 클라이언트 타임아웃은 서버 쿼리를 멈추지 못한다.
    #: 대량 적재 배치는 이 엔진을 쓰지 않는다(`scripts/_common.make_engine`).
    db_statement_timeout_ms: int = 10_000

    # --- 외부 API ---
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-5"
    kakao_rest_api_key: str = ""
    molit_api_key: str = ""

    # --- 도메인 설정 ---
    tax_rules_path: Path = REPO_ROOT / "config" / "tax_rules.yaml"

    @property
    def refresh_cookie_secure(self) -> bool:
        """쿠키에 실제로 붙일 `Secure` 값.

        **운영(DEBUG=false)에서는 설정과 무관하게 항상 True.** 설정 실수 하나로
        refresh 토큰이 평문 HTTP 로 흐르는 사고를 구조적으로 막는다.
        `COOKIE_SECURE=false` 는 오직 DEBUG 개발 환경에서만 효력이 있다.
        """
        if not self.debug:
            return True
        return self.cookie_secure

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
        if not self.cookie_secure:
            # 운영에서는 `refresh_cookie_secure` 가 어차피 True 로 되돌리지만,
            # 설정이 그렇게 적혀 있다는 사실 자체를 기동 점검에서 드러낸다.
            problems.append(
                "COOKIE_SECURE 가 false 입니다 — 로컬 개발 전용 값입니다"
                "(운영에서는 무시되고 Secure 가 강제됩니다)"
            )
        # Argon2 하한은 security.py 가 소유한다(그쪽이 실제로 강제하는 값이라
        # 여기서 숫자를 다시 적으면 언젠가 둘이 어긋난다).
        from app.core.security import argon2_parameter_problems
        problems.extend(argon2_parameter_problems(self))
        return problems


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()
