"""API 라우터.

원칙: **라우터는 얇게.** 검증 → 도메인 호출 → 직렬화만 한다.
계산식이 라우터에 있으면 코드리뷰에서 반려한다(implementation-plan.md §1).
"""
from __future__ import annotations

import datetime as dt
import secrets
from typing import Annotated, Any

import jwt
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)

from app.agents.recommend import run_recommendation_job
from app.api import schemas
from app.api.cookies import (
    delete_refresh_cookie,
    expired_refresh_cookie_header,
    set_refresh_cookie,
)
from app.api.deps import (
    AdminUser,
    CurrentUser,
    SettingsDep,
    unapproved_detail,
    admin_not_found,
    get_encryption_key,
    get_repo,
    get_rules,
    require_ajax_header,
)
from app.core.config import Settings
from app.core.security import (
    ACCESS_TTL_SECONDS,
    DecryptionError,
    create_token,
    decode_token,
    decrypt_amount,
    dummy_password_hash,
    encrypt_amount,
    hash_password,
    verify_password,
)
from app.domain.affordability.engine import compute_affordability
from app.domain.affordability.models import Borrower, LoanTerms, PropertyFacts
from app.domain.rules.loader import RuleSet
from app.repositories.base import STATUS_APPROVED, STATUS_REJECTED, LastAdminError

router = APIRouter(prefix="/api/v1")

#: 자산 금액 필드 ↔ 암호문 컬럼 매핑
_AMOUNT_FIELDS = {
    "cash_krw": "cash_krw_enc",
    "income_krw": "income_krw_enc",
    "existing_loan_krw": "existing_loan_krw_enc",
}


# ---------------------------------------------------------------------------
# 운영
# ---------------------------------------------------------------------------

@router.get("/health", tags=["ops"])
def health(settings: SettingsDep) -> dict[str, Any]:
    """유일한 비인증 엔드포인트. 비밀값을 노출하지 않는다."""
    return {"status": "ok", "role": settings.app_role}


# ---------------------------------------------------------------------------
# 인증
# ---------------------------------------------------------------------------

@router.post("/auth/register", status_code=status.HTTP_201_CREATED, tags=["auth"])
def register(body: schemas.RegisterIn, repo=Depends(get_repo)) -> schemas.RegisterOut:
    """가입을 **접수**한다. 계정은 `pending` 으로 만들어지고 로그인은 아직 안 된다.

    가입 자체를 막지 않는 이유: 관리자가 검토할 대상이 있어야 승인제가 성립한다.
    (예전에는 nginx 에서 이 경로를 403 으로 막아 두는 임시 조치였다.)
    """
    try:
        user = repo.create_user(str(body.email), hash_password(body.password))
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "EMAIL_TAKEN", "message": str(exc)},
        ) from exc
    return schemas.RegisterOut(
        user_id=user.id,
        status=user.status,
        message="가입 신청이 접수되었습니다. 관리자 승인 후 로그인할 수 있습니다.",
    )


@router.post("/auth/login", tags=["auth"])
def login(body: schemas.LoginIn, response: Response, settings: SettingsDep,
          repo=Depends(get_repo)) -> schemas.TokenOut:
    """access 는 본문으로, **refresh 는 쿠키로만** 준다 (security.md §2.1 / SR15-1).

    ⚠️ 검사 순서를 바꾸지 마라 (계정 열거 방지 · SR10-1)
    ---------------------------------------------------
    1. **비밀번호 먼저.** 틀리면 없는 계정과 **완전히 같은** 401 — 본문·상태·비용 모두.
    2. 승인 상태는 **비밀번호가 맞은 뒤에만** 본다. 이 순서라면 상태(승인 대기/거부)를
       알 수 있는 사람은 이미 그 계정의 비밀번호를 아는 사람뿐이라 열거 오라클이 아니다.

    순서를 뒤집어 "pending 이면 403" 을 먼저 내보내면, 공격자는 아무 비밀번호나 넣고
    403/401 만 보고 **가입된 이메일 목록**을 만들 수 있다. 승인제는 그때 오히려
    "누가 승인 대기 중인지"까지 알려주는 장치가 된다.
    """
    user = repo.get_user_by_email(str(body.email))
    # 없는 계정에도 **같은 비용의 해시 검증**을 태운다 — 응답 시간이 가입 여부를
    # 알려주지 않게 한다(dummy_password_hash 주석 참고).
    ok = verify_password(
        body.password,
        user.password_hash if user is not None else dummy_password_hash(),
    )
    if not ok or user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "이메일 또는 비밀번호가 올바르지 않습니다"},
        )

    # 여기부터는 비밀번호를 아는 사람이다 — 상태를 알려줘도 열거로 이어지지 않는다.
    if not user.is_approved:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=unapproved_detail(user.status))

    set_refresh_cookie(
        response,
        create_token(user.id, secret=settings.jwt_secret, kind="refresh"),
        settings,
    )
    return schemas.TokenOut(
        access_token=create_token(user.id, secret=settings.jwt_secret, kind="access"),
        expires_in=ACCESS_TTL_SECONDS,
    )


def _refresh_rejected(settings: Settings) -> HTTPException:
    """갱신 거절 401. **응답과 함께 쿠키를 지운다.**

    못 쓰는 쿠키를 브라우저에 남겨두면 매 요청마다 실패를 반복하고, 사용자는
    "로그인했는데 안 된다"에 갇힌다. 실패했으면 그 자리에서 정리한다.
    거절 사유(없음/만료/서명오류/종류불일치)는 구분해서 알려주지 않는다.
    """
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail={"code": "UNAUTHORIZED", "message": "유효하지 않은 토큰입니다"},
        headers=expired_refresh_cookie_header(settings),
    )


@router.post("/auth/refresh", tags=["auth"],
             dependencies=[Depends(require_ajax_header)])
def refresh(
    response: Response,
    settings: SettingsDep,
    refresh_token: Annotated[str | None, Cookie()] = None,
    repo=Depends(get_repo),
) -> schemas.TokenOut:
    """쿠키로만 갱신한다. **요청 본문을 받지 않는다.**

    본문으로 refresh 를 받는 경로를 남겨두면 쿠키를 도입한 의미가 없다 —
    공격자는 언제나 더 편한 쪽(JS 로 읽어 본문에 실을 수 있는 쪽)을 고른다.

    갱신할 때마다 **쿠키를 회전**시킨다. 쓴 토큰은 새 토큰으로 덮이므로,
    유출본이 있더라도 정상 사용자가 한 번만 갱신하면 그 값은 브라우저에서 사라진다.
    (아직 서버측 폐기는 없다 — 유출본 자체는 만료까지 유효하다. 후속 SR15-3)
    """
    if not refresh_token:
        raise _refresh_rejected(settings)
    try:
        user_id = decode_token(refresh_token, secret=settings.jwt_secret,
                               expect="refresh")
    except jwt.PyJWTError as exc:
        raise _refresh_rejected(settings) from exc
    # 승인이 취소·거부된 계정은 **더 이상 갱신되지 않는다.** 여기서 막지 않으면
    # 거부 처리가 refresh 수명(7일) 동안 아무 효과가 없다(서버측 폐기 없음 — SR15-3).
    # 사유는 401 로 통일한다: 이 요청은 쿠키만 들고 오므로 상태를 알려줄 이유가 없고,
    # 프론트는 쿠키가 지워진 채 로그인 화면으로 가서 거기서 403 안내를 받는다.
    user = repo.get_user(user_id)
    if user is None or not user.is_approved:
        raise _refresh_rejected(settings)

    set_refresh_cookie(
        response,
        create_token(user_id, secret=settings.jwt_secret, kind="refresh"),
        settings,
    )
    return schemas.TokenOut(
        access_token=create_token(user_id, secret=settings.jwt_secret, kind="access"),
        expires_in=ACCESS_TTL_SECONDS,
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, tags=["auth"],
             dependencies=[Depends(require_ajax_header)])
def logout(settings: SettingsDep) -> Response:
    """쿠키를 만료시킨다. 인증을 요구하지 않는다 — 이미 만료된 access 로도 나갈 수 있어야 한다.

    ⚠️ 지금은 **브라우저에서 지우는 것**까지가 전부다. 이미 발급된 refresh 는
    서버가 회수하지 못한다(폐기 목록 없음). 후속 과제 SR15-3.
    """
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    delete_refresh_cookie(response, settings)
    return response


# ---------------------------------------------------------------------------
# 내 조건 (민감 — 로그 제외 대상)
# ---------------------------------------------------------------------------

def _profile_to_out(profile, user_id: int, key: bytes) -> schemas.ProfileOut:
    values: dict[str, int] = {}
    for plain, enc_col in _AMOUNT_FIELDS.items():
        try:
            values[plain] = decrypt_amount(
                getattr(profile, enc_col), user_id=user_id, field=plain, key=key) or 0
        except DecryptionError as exc:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "DECRYPTION_FAILED",
                        "message": "저장된 자산 정보를 읽을 수 없습니다. 다시 입력해 주세요."},
            ) from exc
    return schemas.ProfileOut(
        **values,
        existing_annual_repayment_krw=0,
        existing_annual_interest_krw=0,
        owned_houses=profile.owned_houses,
        household_size=profile.household_size,
    )


@router.get("/me/profile", tags=["me"])
def get_profile(user: CurrentUser, repo=Depends(get_repo),
                key: bytes = Depends(get_encryption_key)) -> schemas.ProfileOut:
    profile = repo.get_profile(user.id)
    if profile is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "자산 정보가 아직 없습니다"},
        )
    return _profile_to_out(profile, user.id, key)


@router.put("/me/profile", tags=["me"])
def put_profile(body: schemas.ProfileIn, user: CurrentUser,
                repo=Depends(get_repo),
                key: bytes = Depends(get_encryption_key)) -> schemas.ProfileOut:
    from app.repositories.base import ProfileRecord

    record = ProfileRecord(
        user_id=user.id,
        owned_houses=body.owned_houses,
        household_size=body.household_size,
    )
    for plain, enc_col in _AMOUNT_FIELDS.items():
        setattr(record, enc_col,
                encrypt_amount(getattr(body, plain), user_id=user.id, field=plain, key=key))
    repo.upsert_profile(record)
    return _profile_to_out(record, user.id, key)


@router.get("/me/preferences", tags=["me"])
def get_preferences(user: CurrentUser, repo=Depends(get_repo)) -> dict[str, Any]:
    return repo.get_preferences(user.id)


@router.put("/me/preferences", tags=["me"])
def put_preferences(body: schemas.PreferencesIn, user: CurrentUser,
                    repo=Depends(get_repo)) -> dict[str, Any]:
    return repo.set_preferences(user.id, body.model_dump())


# ---------------------------------------------------------------------------
# 실구매 가능 금액 (F2) — 동기 · 규칙 계산 · LLM 미사용
# ---------------------------------------------------------------------------

@router.post("/affordability", tags=["analysis"])
def affordability(body: schemas.AffordabilityIn, user: CurrentUser,
                  repo=Depends(get_repo),
                  key: bytes = Depends(get_encryption_key),
                  rules: RuleSet = Depends(get_rules)) -> dict[str, Any]:
    profile = repo.get_profile(user.id)
    if profile is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INSUFFICIENT_DATA",
                    "message": "자산 정보를 먼저 입력해 주세요"},
        )

    def _amount(plain: str) -> int:
        return decrypt_amount(getattr(profile, _AMOUNT_FIELDS[plain]),
                              user_id=user.id, field=plain, key=key) or 0

    try:
        borrower = Borrower(
            cash_krw=_amount("cash_krw"),
            annual_income_krw=_amount("income_krw"),
            # 기존 대출 연 상환액은 프로필에 별도 저장되기 전까지 보수적으로 0 처리하지 않고
            # 원금의 일부를 추정하지 않는다 — 값이 없으면 그대로 0 이고, 가정에 명시한다.
            existing_annual_repayment_krw=0,
            existing_annual_interest_krw=0,
            owned_houses=profile.owned_houses,
            household_size=profile.household_size,
        )
    except DecryptionError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "DECRYPTION_FAILED",
                    "message": "저장된 자산 정보를 읽을 수 없습니다"},
        ) from exc

    result = compute_affordability(
        borrower, rules,
        terms=LoanTerms(annual_rate=body.annual_rate, years=body.years,
                        apply_dti=body.apply_dti),
        prop=PropertyFacts(area_m2=body.area_m2,
                           is_regulated_area=body.is_regulated_area,
                           purpose=body.purpose),
    )
    payload = result.to_api()
    payload["assumptions"].append("기존 대출 상환액 미입력 — 0으로 계산했습니다")
    return payload


# ---------------------------------------------------------------------------
# 지도 (F1)
# ---------------------------------------------------------------------------

#: 이 줌 미만에서는 단지가 아니라 지역 군집을 반환한다 (ux/README.md §4)
CLUSTER_ZOOM_THRESHOLD = 13
_MAX_BBOX_DEGREES = 2.0


@router.get("/map/complexes", tags=["map"])
def map_complexes(
    user: CurrentUser,
    bbox: str = Query(description="minLon,minLat,maxLon,maxLat"),
    zoom: int = Query(ge=1, le=22),
    max_price_krw: int | None = Query(default=None, ge=0),
    area_min_m2: float | None = Query(default=None, gt=0),
    area_max_m2: float | None = Query(default=None, gt=0),
    built_after: int | None = Query(default=None, ge=1900, le=2100),
    repo=Depends(get_repo),
) -> dict[str, Any]:
    try:
        parts = [float(x) for x in bbox.split(",")]
        min_lon, min_lat, max_lon, max_lat = parts
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PARAM",
                    "message": "bbox 는 minLon,minLat,maxLon,maxLat 형식이어야 합니다"},
        ) from exc

    if min_lon >= max_lon or min_lat >= max_lat:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PARAM", "message": "bbox 범위가 올바르지 않습니다"},
        )
    # 지나치게 넓은 범위는 서버를 태운다. 줌아웃은 군집으로 처리한다.
    if (max_lon - min_lon) > _MAX_BBOX_DEGREES or (max_lat - min_lat) > _MAX_BBOX_DEGREES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PARAM", "message": "조회 범위가 너무 넓습니다"},
        )

    rows = repo.complexes_in_bbox(
        min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat,
        max_price_krw=max_price_krw, area_min_m2=area_min_m2,
        area_max_m2=area_max_m2, built_after=built_after,
    )

    if zoom < CLUSTER_ZOOM_THRESHOLD:
        clusters: dict[str, dict[str, Any]] = {}
        for c in rows:
            g = clusters.setdefault(c.region_code, {
                "region_code": c.region_code, "count": 0,
                "lon_sum": 0.0, "lat_sum": 0.0, "prices": [],
            })
            g["count"] += 1
            g["lon_sum"] += c.lon
            g["lat_sum"] += c.lat
            if c.recent_price_krw:
                g["prices"].append(c.recent_price_krw)
        items = []
        for g in clusters.values():
            prices = sorted(g["prices"])
            items.append({
                "region_code": g["region_code"],
                "count": g["count"],
                "center": [round(g["lon_sum"] / g["count"], 6),
                           round(g["lat_sum"] / g["count"], 6)],
                "median_price_krw": prices[len(prices) // 2] if prices else None,
            })
        return {"level": "cluster", "items": items}

    return {
        "level": "complex",
        "items": [
            {
                "id": c.id,
                "name": c.name,
                "point": [c.lon, c.lat],
                "households": c.total_households,
                "built_year": c.built_year,
                "recent_price_krw": c.recent_price_krw,
                # 실거래 신고 지연이 있으므로 '현재가'라고 말하지 않는다.
                "price_as_of": c.price_as_of,
                "price_confidence": "estimated" if c.recent_price_krw else "unknown",
                "active_listings": c.active_listings,
                "over_budget": bool(max_price_krw and c.recent_price_krw
                                    and c.recent_price_krw > max_price_krw),
            }
            for c in rows
        ],
        "note": "실거래는 신고까지 최대 30일이 걸립니다. 최근 거래가 반영되지 않았을 수 있습니다.",
    }


# ---------------------------------------------------------------------------
# 추천 (F1·F3·F6) — 비동기
# ---------------------------------------------------------------------------

@router.post("/recommendations", status_code=status.HTTP_202_ACCEPTED, tags=["analysis"])
def create_recommendation(body: schemas.RecommendationIn, user: CurrentUser,
                          response: Response, background_tasks: BackgroundTasks,
                          settings: SettingsDep,
                          repo=Depends(get_repo)) -> dict[str, Any]:
    """작업을 큐에 넣고 즉시 202. 분석은 **인프로세스 BackgroundTask** 로 돈다.

    배포 최소구성이 redis 없는 api+db 라 별도 워커/큐를 두지 않는다(개인용, 동시성 낮음).
    러너가 프로필 복호화·후보 조회·파이프라인·저장을 맡고, GET 으로 결과를 폴링한다.
    """
    job_id = "rec_" + secrets.token_urlsafe(16)
    criteria = body.model_dump()
    criteria["requested_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    repo.create_job(job_id, user.id, criteria)

    # 세율/키 로드·복호화는 러너 안에서(BackgroundTask 는 Depends 를 못 받는다).
    # 실패해도 요청은 202 로 접수되고, 러너가 job 을 'error' 로 남긴다.
    background_tasks.add_task(
        run_recommendation_job, repo=repo, settings=settings,
        job_id=job_id, user_id=user.id, criteria=criteria,
    )

    response.headers["Location"] = f"/api/v1/recommendations/{job_id}"
    return {
        "job_id": job_id,
        "status": "queued",
        "poll_url": f"/api/v1/recommendations/{job_id}",
        "note": "분석을 시작했습니다. 잠시 후 결과를 조회하세요.",
    }


@router.get("/recommendations/{job_id}", tags=["analysis"])
def get_recommendation(job_id: str, user: CurrentUser,
                       repo=Depends(get_repo)) -> dict[str, Any]:
    # 소유권 검증은 리포지토리가 강제한다 (IDOR — security.md §2.2).
    job = repo.get_job(job_id, user.id)
    if job is None:
        # 남의 작업이 존재한다는 사실조차 알려주지 않는다 → 404 로 통일
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "작업을 찾을 수 없습니다"},
        )
    return {
        "job_id": job.id,
        "status": job.status,
        "criteria_snapshot": job.criteria_snapshot,
        "items": job.items,
        # 추천 목록은 답의 절반이다. 나머지 절반이 **"왜 저건 없는가"** 다 —
        # 제외된 후보와 사유를 함께 준다(빈 목록과 "안 내려줌"은 다른 뜻이다).
        "excluded": job.excluded,
        "notes": job.notes,
        "disclaimer": "투자 권유가 아니며 개인 판단을 돕는 참고 자료입니다.",
    }


# ---------------------------------------------------------------------------
# 관리자 — 가입 승인 (migrations/009)
#
# 인가 규약
# ---------
# * 권한은 **요청 시점에 DB 의 `app_user.is_admin` 으로** 판정한다(`deps.admin_user`).
#   JWT 에 admin 클레임을 넣지 않는다 — 토큰에 실린 권한은 클라이언트의 주장이고,
#   서명이 유효해도 **강등된 뒤에도 유효**하다.
# * 관리자가 아닌 모든 접근(토큰 없음·만료·일반 사용자·승인 대기)은 **동일한 404** 다.
#   403 으로 답하면 "여기 관리 기능이 있다"를 알려주는 셈이라, 모르는 경로와
#   구분되지 않게 맞춘다(deps.admin_not_found).
# * 사용자 자원 접근이지만 IDOR 규약(security.md §2.2)의 예외가 아니다 —
#   여기서는 "관리자"라는 역할이 소유권을 대신하고, 그 역할을 서버가 검증한다.
# ---------------------------------------------------------------------------

def _admin_user_out(user) -> schemas.AdminUserOut:
    return schemas.AdminUserOut(
        id=user.id, email=user.email, status=user.status, is_admin=user.is_admin,
        created_at=user.created_at, status_changed_at=user.status_changed_at,
        status_changed_by=user.status_changed_by, status_reason=user.status_reason,
    )


def _set_status(repo, admin, user_id: int, new_status: str,
                reason: str | None = None) -> schemas.AdminUserOut:
    """승인·거부 공통. 실패는 전부 **존재를 숨기는 404** 로 통일한다."""
    try:
        updated = repo.set_user_status(
            user_id, new_status,
            actor="admin_api", actor_user_id=admin.id, reason=reason,
        )
    except LastAdminError as exc:
        # 마지막 관리자를 스스로 잠그는 것을 막는다. 이건 숨길 정보가 아니라
        # **왜 안 되는지 알려줘야 하는** 상황이라 404 로 덮지 않는다.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "LAST_ADMIN", "message": str(exc)},
        ) from exc
    if updated is None:
        raise admin_not_found()
    return _admin_user_out(updated)


@router.get("/admin/users", tags=["admin"])
def admin_list_users(admin: AdminUser, repo=Depends(get_repo),
                     user_status: str | None = Query(
                         default=None, alias="status",
                         pattern="^(pending|approved|rejected)$"),
                     limit: int = Query(default=100, ge=1, le=500),
                     ) -> schemas.AdminUserListOut:
    """가입 대기 목록. 기본은 전체이며 `?status=pending` 으로 좁힌다.

    응답에는 이메일·상태·감사 흔적만 담는다 — 비밀번호 해시도, 자산 금액도 넘기지 않는다
    (AdminUserOut 이 마지막 문이다).
    """
    users = repo.list_users(status=user_status, limit=limit)
    return schemas.AdminUserListOut(
        items=[_admin_user_out(u) for u in users],
        active_admins=repo.count_active_admins(),
    )


@router.post("/admin/users/{user_id}/approve", tags=["admin"])
def admin_approve_user(user_id: int, admin: AdminUser,
                       repo=Depends(get_repo)) -> schemas.AdminUserOut:
    return _set_status(repo, admin, user_id, STATUS_APPROVED)


@router.post("/admin/users/{user_id}/reject", tags=["admin"])
def admin_reject_user(user_id: int, body: schemas.RejectIn, admin: AdminUser,
                      repo=Depends(get_repo)) -> schemas.AdminUserOut:
    """거부. 이미 승인된 계정을 되돌리는 데도 쓴다(접근 회수).

    ⚠️ 마지막 관리자는 거부되지 않는다 — 관리자가 0명이 되면 어떤 가입도 승인할 수
    없고, 복구하려면 서버에 SSH 로 들어가야 한다(리포지토리가 `LastAdminError`).
    """
    return _set_status(repo, admin, user_id, STATUS_REJECTED, reason=body.reason)


#: ⚠️ **반드시 위 관리자 라우트들보다 뒤에 있어야 한다.**
#: Starlette 은 경로가 맞고 메서드가 다르면 405 를 주는데, 그 405 자체가
#: "여기 라우트가 있다"는 신호다(`PUT /admin/users` → 405 vs 없는 경로 → 404).
#: 이 포괄 라우트가 남은 메서드·하위경로를 전부 받아 **모르는 경로와 같은 404** 로 맞춘다.
#: (Starlette 은 완전 일치를 먼저 찾으므로 위의 정상 라우트를 가리지 않는다.)
@router.api_route("/admin/{rest:path}", include_in_schema=False,
                  methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
def admin_catch_all(rest: str) -> None:
    raise admin_not_found()
