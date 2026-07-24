"""FastAPI 앱 진입점."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import get_settings
from app.core.security import mask_sensitive

logger = logging.getLogger("app")

#: 이 경로들은 접근 로그에서 **쿼리스트링까지 지운다** (security.md §3.3).
#: 요청·응답 **본문은 어떤 경로에서도 로그에 남기지 않는다** — 남길 수 있게 만들면
#: 언젠가 누군가 디버깅하려고 켜고, 그날 자산 금액이 로그로 샌다.
SENSITIVE_PATHS = ("/api/v1/me/profile", "/api/v1/affordability", "/api/v1/auth")


def create_app(*, repo=None) -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="부동산 AI 자문 시스템",
        version="0.1.0",
        docs_url="/api/docs" if settings.debug else None,   # 운영에서는 스키마 비공개
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.debug else None,
    )

    if repo is None:  # pragma: no cover - 운영 경로
        from app.repositories.memory import InMemoryRepository
        repo = InMemoryRepository()
        logger.warning(
            "인메모리 리포지토리로 기동합니다. PostGIS 구현 연결 전까지 데이터가 보존되지 않습니다."
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
