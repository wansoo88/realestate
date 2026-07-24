"""API 라우터.

원칙: **라우터는 얇게.** 검증 → 도메인 호출 → 직렬화만 한다.
계산식이 라우터에 있으면 코드리뷰에서 반려한다(implementation-plan.md §1).
"""
from __future__ import annotations

import datetime as dt
import secrets
from typing import Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api import schemas
from app.api.deps import (
    CurrentUser,
    SettingsDep,
    get_encryption_key,
    get_repo,
    get_rules,
)
from app.core.security import (
    DecryptionError,
    create_token,
    decrypt_amount,
    encrypt_amount,
    hash_password,
    verify_password,
)
from app.domain.affordability.engine import compute_affordability
from app.domain.affordability.models import Borrower, LoanTerms, PropertyFacts
from app.domain.rules.loader import RuleSet

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
def register(body: schemas.RegisterIn, repo=Depends(get_repo)) -> dict[str, Any]:
    try:
        user = repo.create_user(str(body.email), hash_password(body.password))
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "EMAIL_TAKEN", "message": str(exc)},
        ) from exc
    return {"user_id": user.id}


@router.post("/auth/login", tags=["auth"])
def login(body: schemas.LoginIn, settings: SettingsDep,
          repo=Depends(get_repo)) -> schemas.TokenOut:
    user = repo.get_user_by_email(str(body.email))
    # 사용자 존재 여부를 응답으로 구분할 수 없게 한다(계정 열거 방지).
    ok = user is not None and verify_password(body.password, user.password_hash)
    if not ok:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "이메일 또는 비밀번호가 올바르지 않습니다"},
        )
    return schemas.TokenOut(
        access_token=create_token(user.id, secret=settings.jwt_secret, kind="access"),
        refresh_token=create_token(user.id, secret=settings.jwt_secret, kind="refresh"),
        expires_in=1800,
    )


@router.post("/auth/refresh", tags=["auth"])
def refresh(body: schemas.RefreshIn, settings: SettingsDep,
            repo=Depends(get_repo)) -> schemas.TokenOut:
    from app.core.security import decode_token
    try:
        user_id = decode_token(body.refresh_token, secret=settings.jwt_secret,
                               expect="refresh")
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "유효하지 않은 토큰입니다"},
        ) from exc
    if repo.get_user(user_id) is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "유효하지 않은 토큰입니다"},
        )
    return schemas.TokenOut(
        access_token=create_token(user_id, secret=settings.jwt_secret, kind="access"),
        refresh_token=create_token(user_id, secret=settings.jwt_secret, kind="refresh"),
        expires_in=1800,
    )


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
                          response: Response, repo=Depends(get_repo)) -> dict[str, Any]:
    """작업을 큐에 넣고 즉시 202. 에이전트 분석은 수십 초 걸린다."""
    job_id = "rec_" + secrets.token_urlsafe(16)
    criteria = body.model_dump()
    criteria["requested_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    repo.create_job(job_id, user.id, criteria)

    response.headers["Location"] = f"/api/v1/recommendations/{job_id}"
    return {
        "job_id": job_id,
        "status": "queued",
        "poll_url": f"/api/v1/recommendations/{job_id}",
        # ⚠️ 실제 큐 소비자(worker-agent)는 아직 미구현이다. 완료되지 않는다.
        "note": "에이전트 오케스트레이션은 구현 중입니다(T7).",
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
        "disclaimer": "투자 권유가 아니며 개인 판단을 돕는 참고 자료입니다.",
    }
