"""FastAPI 앱 진입점."""
from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import enforce_runtime_settings, get_settings
from app.core.masking import install_log_masking
from app.core.security import HashCapacityError

logger = logging.getLogger("app")

#: ★ SR32-1. **쿼리스트링의 값은 어떤 경로에서도 로그에 남기지 않는다.**
#:
#: 예전에는 `SENSITIVE_PATHS` 라는 **허용목록의 반대**(민감목록)를 두고 거기 실린
#: 경로에서만 쿼리를 지웠다. 그 구조가 그대로 사고가 됐다:
#:   · `/me/profile`·`/affordability` 는 목록에 있었다 — 본문이 안 남는다.
#:   · **`/map/complexes` 는 목록에 없었다.** 그런데 그 쿼리에 실려 있던
#:     `max_price_krw=1314310000` 은 방금 그 `/affordability` 가 **암호화된 자산·소득·
#:     대출을 복호화해 계산한 결론**이었다. 세 겹으로 지킨 값이 네 번째 길로 나갔다.
#: 목록으로 관리하는 방어는 **새 엔드포인트가 생길 때마다 사람이 기억해야** 하고,
#: 기억은 언젠가 빠진다. 그래서 규칙을 뒤집는다 — **기본이 '지운다'** 이고, 남기려면
#: 그 자리에서 이유를 대야 한다(지금은 예외가 하나도 없다).
#:
#: 요청·응답 **본문도 어떤 경로에서도 로그에 남기지 않는다** — 남길 수 있게 만들면
#: 언젠가 누군가 디버깅하려고 켜고, 그날 자산 금액이 로그로 샌다.
#:
#: ⚠️ 이 미들웨어는 **세 싱크 중 하나**다. 나머지 둘도 같이 막혀 있어야 뜻이 있다:
#:    ② uvicorn 접근 로그 → `masking.install_access_log_query_stripping()`
#:    ③ nginx `combined` → `deploy/nginx-realestate.conf` 의 `re_noquery` log_format
#:    하나만 막으면 나머지가 계속 쓴다(SR-032 §4-1 실측).

#: 쿼리 **이름**은 남긴다 — "어떤 조건이 걸린 요청이었나"는 운영에 필요한 사실이고,
#: 이름 자체는 값이 아니다. 다만 **이름 자리에 값을 넣는 요청**(`?1314310000=x`)이
#: 오면 그것도 유출이므로, 소문자 식별자 모양만 통과시킨다(숫자로 시작하는 이름,
#: 이메일·금액처럼 생긴 이름은 그 자리에서 버린다).
_QUERY_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def log_target(path: str, query: str) -> str:
    """접근 로그에 남길 문자열. **값은 절대 넣지 않는다.**

    `/api/v1/map/complexes [q: bbox,budget,zoom]` 처럼 경로 + 파라미터 이름만.
    """
    if not query:
        return path
    names = sorted({k for k, _, _ in (p.partition("=") for p in query.split("&")) if k})
    shown = [n for n in names if _QUERY_NAME_RE.match(n)]
    dropped = len(names) - len(shown)
    if dropped:
        shown.append(f"+{dropped}")
    return f"{path} [q: {','.join(shown)}]" if shown else path

#: 422 응답에 실을 검증 메시지 1건의 길이 상한(문자). **되비침의 총량을 묶는다**(SR25-2).
#: 정상 메시지는 실측 100자 이하다. 이 상한이 하는 일은 "누군가 검증기에 입력값을
#: 넣었을 때 응답이 요청만큼 커지는 것"을 막는 것뿐이고, 값을 넣지 않는 것이 본 방어다.
MAX_VALIDATION_MSG_CHARS = 200


def create_app(*, repo=None) -> FastAPI:
    settings = get_settings()

    # 로그로 나가는 문자열에서 비밀을 지운다(SR17-3). 이 프로세스에서 가장 위험한 경로는
    # 아래 `logger.exception` 이다 — SQLAlchemy 예외는 접속 DSN(비밀번호 포함)을,
    # 외부 API 예외는 요청 URL(인증키 포함)을 메시지에 그대로 담는다.
    # ⚠️ 기동 점검보다 **먼저** 설치한다 — 점검 로그가 나가는 경로도 마스킹을 타야 한다.
    install_log_masking()

    # ⛔ 설정이 잘못됐으면 여기서 멈춘다(SR29-1). 경고만 찍고 뜨면 아무도 안 본다:
    #    `JWT_SECRET=""` 로도 토큰은 발급·검증되고, 서비스는 **정상으로 보인다.**
    #    무엇을 막고 무엇을 경고로 둘지의 근거는 `Settings._runtime_checks` 에 있다.
    enforce_runtime_settings(settings, logger=logger)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 리포지토리는 **기동 시점**에 만든다. import 시점에 DB 에 붙으면
        # 테스트·도구가 모듈을 읽기만 해도 연결을 시도하게 된다.
        # 테스트가 넣어준 구현이 이미 있으면 건드리지 않는다.
        if app.state.repo is None:  # pragma: no cover - 운영 경로
            from app.repositories.factory import build_repository
            app.state.repo = build_repository(settings)
        try:
            yield
        finally:  # pragma: no cover - 운영 경로
            close = getattr(app.state.repo, "close", None)
            if callable(close):
                close()

    app = FastAPI(
        title="부동산 AI 자문 시스템",
        version="0.1.0",
        docs_url="/api/docs" if settings.debug else None,   # 운영에서는 스키마 비공개
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )

    app.state.repo = repo

    app.include_router(router)

    @app.middleware("http")
    async def access_log_and_headers(request: Request, call_next):
        response = await call_next(request)

        logger.info("%s %s %s", request.method,
                    log_target(request.url.path, request.url.query),
                    response.status_code)


        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.exception_handler(HashCapacityError)
    async def hash_overloaded(request: Request, exc: HashCapacityError):
        """인증 폭주는 **인증만** 거절한다 (SR8-1).

        해시 슬롯을 기다리며 스레드풀이 다 막히면 지도·리포트까지 함께 죽는다.
        여기서 잘라내면 나머지 기능은 계속 응답한다.
        비밀번호·계정 존재 여부는 어떤 식으로도 드러내지 않는다.
        """
        logger.warning("인증 해시 동시 실행 한도 초과: %s", request.url.path)
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "BUSY",
                               "message": "요청이 많아 잠시 후 다시 시도해 주세요"}},
            headers={"Retry-After": "1"},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_failed(request: Request, exc: RequestValidationError):
        """입력 검증 실패 → 422. **사용자가 보낸 값은 되돌려 주지 않는다.**

        FastAPI 기본 핸들러는 오류마다 `input`(사용자가 보낸 원본 값)을 응답에 싣는다.
        그게 두 가지 문제를 만든다:

        ① **비밀이 되돌아온다.** `POST /auth/register` 에서 비밀번호가 12자 미만이면
           기본 핸들러는 `{"input": "hunter2s"}` 로 **평문 비밀번호를 응답 본문에**
           담아 보낸다(실측). 보낸 사람에게 돌려주는 것이라 유출은 아니지만, 그 값은
           브라우저 콘솔·프론트 오류 리포팅·프록시 캐시로 흘러갈 자리가 너무 많다.
           같은 이유로 자산 금액(`/me/profile`)도 검증 실패 시 되돌아왔다.
        ② **직렬화가 깨져 422 가 500 이 된다.** `input` 이 `Infinity`·`NaN` 이면
           `JSONResponse` 의 `json.dumps(allow_nan=False)` 가 예외를 던지고, 그러면
           검증 실패가 **처리되지 않은 오류(500)** 로 나간다(SR24-6 수정 중 실측).

        그래서 `type`·`loc`·`msg` 만 남긴다 — 클라이언트가 "어느 필드가 왜 틀렸는지"를
        아는 데 필요한 정보는 그대로이고, 원본 값은 이미 클라이언트가 갖고 있다.

        ⚠️ **이 보증은 절대적이지 않다**(SR25-2). `msg` 는 pydantic 내장 규칙이나
           **우리가 쓴 커스텀 검증기**가 만든 문장이다. 검증기에서 `ValueError(f"...{값}")`
           처럼 입력값을 문장에 넣으면 그 값은 `msg` 를 타고 그대로 되돌아간다
           (실측: `region_codes` 3,000자 → 응답 3,127바이트). 그래서 두 가지를 건다:
             ① 검증기는 값을 문장에 넣지 않고 **`loc`·위치로 지목**한다(schemas.py 규약)
             ② 그래도 새는 경우를 대비해 여기서 `msg` 길이를 자른다 —
                되비치는 양을 제한하는 것은 마지막 방어선이지 첫 방어선이 아니다.
        """
        detail = [
            {"type": str(err.get("type", "")),
             "loc": [str(part) for part in err.get("loc", ())],
             "msg": str(err.get("msg", ""))[:MAX_VALIDATION_MSG_CHARS]}
            for err in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        # 스택트레이스·로컬 변수를 응답에 절대 싣지 않는다.
        #
        # ★ SR33-1 — 여기는 **위에서 선언한 규칙의 예외가 아니다.**
        #   예전에는 `mask_sensitive(str(request.url))` 이었는데, 그 함수는
        #   dict/list 의 **키 이름**으로 민감 필드를 찾는 구조 마스커라 문자열이
        #   들어오면 아무 일도 하지 않았다(그대로 반환). 그래서 이 한 줄이
        #   `?bbox=…&area_min_m2=84.5` 처럼 **쿼리를 통째로** 로그에 남겼다.
        #   하필 이 줄이 앱 로거에서 운영에 실제로 나가는 **유일한 줄**이다 —
        #   root 핸들러가 없어 위 미들웨어의 INFO 는 버려지고, ERROR 만
        #   `logging.lastResort` 로 stderr(= `docker logs`)에 나간다.
        #   즉 "값을 지우는 계층"은 침묵하고 "값을 담는 계층"만 말하고 있었다.
        #   → 같은 파일의 `log_target` 을 쓴다(쿼리는 **이름만** 남는다).
        logger.exception("처리되지 않은 오류: %s %s", request.method,
                         log_target(request.url.path, request.url.query))
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL", "message": "처리 중 오류가 발생했습니다"}},
        )

    return app


app = create_app()
