"""FastAPI 앱 진입점."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import get_settings
from app.core.masking import install_log_masking
from app.core.security import HashCapacityError, mask_sensitive

logger = logging.getLogger("app")

#: 이 경로들은 접근 로그에서 **쿼리스트링까지 지운다** (security.md §3.3).
#: 요청·응답 **본문은 어떤 경로에서도 로그에 남기지 않는다** — 남길 수 있게 만들면
#: 언젠가 누군가 디버깅하려고 켜고, 그날 자산 금액이 로그로 샌다.
SENSITIVE_PATHS = ("/api/v1/me/profile", "/api/v1/affordability", "/api/v1/auth")


def create_app(*, repo=None) -> FastAPI:
    settings = get_settings()

    # 로그로 나가는 문자열에서 비밀을 지운다(SR17-3). 이 프로세스에서 가장 위험한 경로는
    # 아래 `logger.exception` 이다 — SQLAlchemy 예외는 접속 DSN(비밀번호 포함)을,
    # 외부 API 예외는 요청 URL(인증키 포함)을 메시지에 그대로 담는다.
    install_log_masking()

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

        path = request.url.path
        if any(path.startswith(p) for p in SENSITIVE_PATHS):
            logged_target = path                       # 쿼리스트링 제거
        else:
            logged_target = path + (f"?{request.url.query}" if request.url.query else "")
        logger.info("%s %s %s", request.method, logged_target, response.status_code)


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

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):  # pragma: no cover
        # 스택트레이스·로컬 변수를 응답에 절대 싣지 않는다.
        logger.exception("처리되지 않은 오류: %s %s", request.method,
                         mask_sensitive(str(request.url)))
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL", "message": "처리 중 오류가 발생했습니다"}},
        )

    return app


app = create_app()
