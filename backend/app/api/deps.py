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
from app.repositories.base import STATUS_REJECTED, UserRecord


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


#: CSRF 2차 방어용 커스텀 헤더 (security.md §2.1 / SR15-1).
#: 쿠키를 쓰는 순간 CSRF 가 성립할 여지가 생긴다. `SameSite=Strict` 가 1차 방어이고,
#: 이 헤더가 2차다 — **HTML `<form>` 은 커스텀 헤더를 붙일 수 없고**, 붙이려면
#: 스크립트가 필요한데 그건 CORS 사전요청(preflight)에 걸린다. 즉 공격자가 만든
#: 남의 페이지에서는 이 헤더를 실은 요청을 우리 서버로 보낼 수 없다.
AJAX_HEADER = "X-Requested-With"
AJAX_HEADER_VALUE = "XMLHttpRequest"


def require_ajax_header(
    x_requested_with: Annotated[str | None, Header()] = None,
) -> None:
    """쿠키 인증 엔드포인트(refresh·logout) 전용 관문.

    ⚠️ 실패해도 **쿠키를 지우지 않는다.** 여기서 로그아웃시키면 공격자가 헤더 없는
    요청을 반복 유도해 남의 세션을 끊는 수단이 된다(로그아웃 CSRF).
    """
    if (x_requested_with or "").strip().lower() != AJAX_HEADER_VALUE.lower():
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "code": "CSRF_HEADER_REQUIRED",
                "message": f"{AJAX_HEADER}: {AJAX_HEADER_VALUE} 헤더가 필요합니다",
            },
        )


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
    # 승인 상태는 **매 요청 DB 에서 다시 본다** (토큰에 담지 않는다).
    # 담아 두면 승인 취소·거부가 access 30분 · refresh 7일 동안 효력이 없다 —
    # 서버측 토큰 폐기가 아직 없으므로(SR15-3) 이 재확인이 유일한 회수 수단이다.
    if not user.is_approved:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=unapproved_detail(user.status))
    return user


CurrentUser = Annotated[UserRecord, Depends(current_user)]


# ---------------------------------------------------------------------------
# 가입 승인 (migrations/009)
# ---------------------------------------------------------------------------

def unapproved_detail(user_status: str) -> dict[str, str]:
    """승인되지 않은 계정에 돌려줄 403 본문.

    ⚠️ **비밀번호 검증을 통과한 뒤에만** 쓴다. 인증 전에 이 문구를 내보내면
    "이 이메일은 가입돼 있다"를 알려주는 계정 열거 오라클이 된다(SR10-1).
    """
    if user_status == STATUS_REJECTED:
        return {"code": "ACCOUNT_REJECTED",
                "message": "가입이 승인되지 않았습니다. 관리자에게 문의하세요."}
    return {"code": "PENDING_APPROVAL",
            "message": "관리자 승인 대기 중입니다. 승인되면 로그인할 수 있습니다."}


def admin_not_found() -> HTTPException:
    """관리자 엔드포인트의 **존재 자체를 숨기는** 404.

    왜 403 이 아니라 404 인가
    -------------------------
    403 은 "여기 뭔가 있는데 너는 못 본다"는 뜻이라, 일반 사용자에게 관리 기능의
    경로·존재를 알려 준다. 공격자는 그 경로에 인증 우회·파라미터 조작을 집중한다.
    404 로 답하면 관리자가 아닌 쪽에서는 **없는 주소와 구분되지 않는다.**

    본문은 FastAPI 가 모르는 경로에 주는 것과 **글자까지 동일**하게 맞춘다
    (`{"detail": "Not Found"}`). 우리 규약인 `{"detail": {"code": ...}}` 를 쓰면
    형태가 달라서 그 자체로 "여기 라우트가 있다"는 신호가 된다.
    """
    return HTTPException(status.HTTP_404_NOT_FOUND)


def admin_user(
    settings: SettingsDep,
    repo=Depends(get_repo),
    authorization: Annotated[str | None, Header()] = None,
) -> UserRecord:
    """관리자 전용 관문. **서버가 DB 에서 `is_admin` 을 확인한다.**

    토큰에 admin 클레임을 싣지 않는 이유: 클라이언트가 들고 다니는 값은 결국
    클라이언트의 주장이고, 서명이 유효해도 **강등된 뒤에도 유효**하다.
    권한은 요청 시점의 DB 가 답한다.

    실패는 사유를 구분하지 않고 전부 같은 404 다 — 토큰 없음/만료/일반 사용자/
    승인 대기 관리자 모두 동일. 구분하면 그 차이가 곧 정보다.
    """
    try:
        user = current_user(settings=settings, repo=repo, authorization=authorization)
    except HTTPException as exc:
        raise admin_not_found() from exc
    if not user.can_administer:
        raise admin_not_found()
    return user


AdminUser = Annotated[UserRecord, Depends(admin_user)]
