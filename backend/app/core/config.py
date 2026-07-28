"""애플리케이션 설정.

원칙: **비밀값은 환경변수(.env)에서만 온다.** 기본값으로 비밀을 넣지 않는다.
설정이 잘못되면 조용히 약한 상태로 돌아가는 대신 **시작을 막는다**
— 그 일을 하는 것은 `enforce_runtime_settings()` 이고, `app.main.create_app()` 이 부른다.
(예전에는 `validate_runtime()` 이 있기만 하고 **아무도 부르지 않아** `JWT_SECRET=""`
로도 앱이 떴다. 위 문장이 사실이 아니었다 — SR29-1. 문서가 방어인 척하지 않게 할 것.)
"""
from __future__ import annotations

import functools
import logging
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

    def _runtime_checks(self) -> list[tuple[bool, str]]:
        """(기동을 막는가, 문제 문구) 목록. 정상이면 빈 목록.

        **무엇을 '막을 문제'로 볼 것인가** — 기준은 하나다:
        *값이 잘못돼도 앱이 정상처럼 계속 도는가.* 그런 항목만 막는다(SR29-1).
        빠졌을 때 첫 사용에서 큰 소리로 죽는 항목은 막지 않는다 — 기동 실패는
        서비스 전체를 죽이는 조치라서, 조용한 약화를 막는 데만 쓴다.
        """
        problems: list[tuple[bool, str]] = []

        # ★ 막는다. 빈 문자열로도 HS256 서명·검증이 **성공한다**(실측). 즉 키가 없으면
        #   누구나 아는 값으로 서명된 토큰이 통과하고, 임의 user_id 위조 = 승인제 우회다.
        #   32자는 RFC 7518 §3.2(HMAC 키는 해시 출력 길이 이상, HS256 → 256bit) 하한.
        if len(self.jwt_secret) < 32:
            problems.append((True, "JWT_SECRET 이 없거나 32자 미만입니다"))

        # ★ 막는다. AES-256-GCM 은 정확히 32바이트 키를 요구한다. 사용 지점
        #   (`security.load_key`)이 fail-closed 로 막지만, 그건 **사용자가 자산 정보를
        #   저장하려는 순간** 500 이 되는 것이라 기동 시점에 아는 편이 낫다.
        if len(self.field_encryption_key) != 32:
            problems.append((True, "FIELD_ENCRYPTION_KEY 는 정확히 32바이트여야 합니다"))

        # ★ 막는다. 파라미터가 낮아도 해시는 **성공한다** — 조용히 약해지는 전형이다.
        #   Argon2 하한은 security.py 가 소유한다(그쪽이 실제로 강제하는 값이라
        #   여기서 숫자를 다시 적으면 언젠가 둘이 어긋난다).
        from app.core.security import argon2_parameter_problems
        problems.extend((True, p) for p in argon2_parameter_problems(self))

        # 막지 않는다 — 값이 비면 **첫 DB 접속에서 즉시 실패**하므로 조용하지 않다.
        # 그리고 리포지토리를 주입해 DB 없이 뜨는 구성(테스트·인메모리)이 실재한다.
        if not self.postgres_password:
            problems.append((False, "POSTGRES_PASSWORD 가 비어 있습니다"))

        # 막지 않는다 — 이 항목은 `debug=True` 일 때만 붙는데, 기동 차단은 운영
        # (`debug=False`)에서만 하므로 애초에 만날 일이 없다. 기록용이다.
        if self.debug:
            problems.append((False, "DEBUG 가 켜져 있습니다 — 운영에서는 꺼야 합니다"))

        # 막지 않는다 — `refresh_cookie_secure` 가 운영에서 **구조적으로** True 로
        # 되돌리므로 이 설정은 운영에서 효력이 없다. 효력 없는 설정 때문에 서비스를
        # 죽이는 것은 비례하지 않는다. 다만 그렇게 적혀 있다는 사실은 드러낸다.
        if not self.cookie_secure:
            problems.append((
                False,
                "COOKIE_SECURE 가 false 입니다 — 로컬 개발 전용 값입니다"
                "(운영에서는 무시되고 Secure 가 강제됩니다)",
            ))
        return problems

    def validate_runtime(self) -> list[str]:
        """운영 기동 전 점검. 문제가 있으면 목록을 돌려준다(빈 목록이면 정상).

        ⚠️ **이 함수를 부르는 것은 `enforce_runtime_settings` 다.** 목록을 돌려주기만
        하는 함수는 아무도 안 부르면 아무 일도 하지 않는다 — 실제로 이 저장소에서
        그 상태로 오래 있었고(SR29-1), 그동안 원장은 이 함수를 방어 근거로 인용했다.
        """
        return [message for _fatal, message in self._runtime_checks()]

    def fatal_runtime_problems(self) -> list[str]:
        """그중 **기동을 막아야 하는** 것들. 판단 근거는 `_runtime_checks` 주석."""
        return [message for fatal, message in self._runtime_checks() if fatal]


class RuntimeConfigError(RuntimeError):
    """운영 기동을 막는 설정 문제. **값은 담지 않는다** — 항목 이름만."""


def enforce_runtime_settings(settings: Settings, *,
                             logger: logging.Logger | None = None) -> list[str]:
    """기동 점검을 **실제로 실행**한다. 운영에서 치명적 문제가 있으면 기동을 멈춘다.

    - `debug=False`(운영) + 치명적 문제 → `RuntimeConfigError` 로 **기동 중단**.
      경고 로그로 끝내면 아무도 안 보고, 약한 상태가 그대로 서비스된다.
    - 나머지(위생 문제, 개발 환경) → 경고 로그. 개발자가 로컬에서 앱을 못 띄우게
      만들지는 않는다.

    로그·예외에는 **항목 이름만** 나간다(비밀값은 어디에도 싣지 않는다).
    """
    log = logger or logging.getLogger("app")
    problems = settings.validate_runtime()
    if not problems:
        return []
    fatal = settings.fatal_runtime_problems()
    if fatal and not settings.debug:
        for message in problems:
            log.error("기동 점검 실패: %s", message)
        raise RuntimeConfigError(
            "운영 설정 점검 실패 — " + " / ".join(fatal)
            + " (환경변수를 채운 뒤 다시 기동하세요)")
    for message in problems:
        log.warning("기동 점검 경고: %s", message)
    return problems


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()
