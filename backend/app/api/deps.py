"""FastAPI 의존성 — 인증, 리포지토리, 세율 설정.

인증 원칙: **공개 엔드포인트를 두지 않는다**(`/health` 제외).
개인 자산 기반 서비스라 익명 접근이 의미가 없고, 실수로 열릴 여지를 없앤다.
"""
from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, Request, status

from app.core.config import Settings, get_settings
from app.core.security import decode_token, load_key
from app.domain.rules.loader import RuleSet, RuleValidationError, load_rules
from app.repositories.base import UserRecord


def get_repo(request: Request):
    """앱 상태에 붙어 있는 리포지토리. 테스트는 여기에 인메모리 구현을 꽂는다."""
    repo = getattr(request.app.state, "repo", None)
    if repo is None:  # pragma: no cover - 기동 시 항상 설정된다
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "리포지토리 미설정")
    return repo


SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_encryption_key(settings: SettingsDep) -> bytes:
    try:
        return load_key(settings.field_encryption_key)
    except ValueError as exc:
        # 키가 없으면 평문으로 돌아가는 대신 기능을 막는다.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "MISCONFIGURED", "message": str(exc)},
        ) from exc


def get_rules(settings: SettingsDep) -> RuleSet:
    """세율 설정. 검증에 실패하면 **추정하지 않고 503** 을 낸다.

    "대충 계산해서 보여주기" 는 이 도메인에서 최악의 선택이다.
    """
    try:
        return load_rules(settings.tax_rules_path)
    except RuleValidationError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "TAX_RULES_UNAVAILABLE",
                "message": "세율 설정이 검증되지 않아 계산할 수 없습니다. "
                           "공식 출처로 config/tax_rules.yaml 을 채운 뒤 status 를 "
                           "verified 로 바꾸세요.",
                "problems": exc.problems,
            },
        ) from exc


def current_user(
    settings: SettingsDep,
    repo=Depends(get_repo),
    authorization: Annotated[str | None, Header()] = None,
) -> UserRecord:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "인증이 필요합니다"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    try:
        user_id = decode_token(token, secret=settings.jwt_secret, expect="access")
    except jwt.PyJWTError as exc:
        # 왜 실패했는지(만료/서명오류) 구체적으로 알려주지 않는다.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "유효하지 않은 토큰입니다"},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = repo.get_user(user_id)
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "유효하지 않은 토큰입니다"},
        )
    return user


CurrentUser = Annotated[UserRecord, Depends(current_user)]
