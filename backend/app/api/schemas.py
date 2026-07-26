"""API 요청·응답 스키마."""
from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)


class RegisterOut(BaseModel):
    """가입 접수 응답. 계정은 만들어졌지만 **아직 못 쓴다**는 것을 분명히 말한다.

    "가입 완료"라고 하면 사용자는 곧바로 로그인을 시도하고 실패한다.
    """

    user_id: int
    status: str
    message: str


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    """로그인·갱신 응답.

    ⚠️ **refresh_token 필드를 다시 추가하지 마라.** refresh 는 `httpOnly` 쿠키로만
    오간다(security.md §2.1, SR15-1). 본문에 실으면 클라이언트가 그것을 저장할 곳을
    찾게 되고, 웹에서 그 자리는 결국 JS 가 읽는 저장소가 된다.
    access 는 **메모리 전용**으로 쓰라는 전제다.
    """

    access_token: str
    token_type: str = "bearer"
    #: access 수명(초). 프론트가 만료 전에 미리 갱신할 수 있게 준다.
    expires_in: int


class ProfileIn(BaseModel):
    """자산 정보. 이 모델의 값은 **로그에 남기지 않는다** (security.md §3.3)."""

    cash_krw: int = Field(ge=0, le=10**15)
    income_krw: int = Field(ge=0, le=10**15)
    existing_loan_krw: int = Field(default=0, ge=0, le=10**15)
    existing_annual_repayment_krw: int = Field(default=0, ge=0, le=10**15)
    existing_annual_interest_krw: int = Field(default=0, ge=0, le=10**15)
    owned_houses: int = Field(default=0, ge=0, le=100)
    household_size: int = Field(default=1, ge=1, le=20)


class ProfileOut(ProfileIn):
    pass


class PreferencesIn(BaseModel):
    prefer: dict[str, Any] = Field(default_factory=dict)
    avoid: dict[str, Any] = Field(default_factory=dict)
    weights: dict[str, float] = Field(default_factory=dict)


class AffordabilityIn(BaseModel):
    # ⚠️ 권역(region_group/target_region_code)은 **클라이언트 입력이 아니다.**
    # 사용자가 비수도권 코드를 보내 6억 캡을 끄고 예산을 부풀릴 수 있어(약 13.6억) G2 위반이다.
    # 권역은 서버가 판정하며(대상지역이 수도권 전체 → 안전기본 수도권), 여기에 필드를 두지 않는다.
    # (근거: docs/domain/affordability-region-policy.md, CR10-1)
    purpose: str = Field(default="live", pattern="^(live|invest)$")
    area_m2: float = Field(default=84.0, gt=0, le=1000)
    is_regulated_area: bool = False
    annual_rate: float = Field(default=0.04, ge=0, le=0.3)
    years: int = Field(default=30, ge=1, le=50)
    apply_dti: bool = False


# ---------------------------------------------------------------------------
# 관리자 (가입 승인 · migrations/009)
# ---------------------------------------------------------------------------

class AdminUserOut(BaseModel):
    """관리자에게 보여줄 사용자 요약.

    ⚠️ **`password_hash` 를 여기 넣지 마라.** 리포지토리는 해시를 담아 오지만
    이 스키마가 마지막 문이다. 오프라인 크래킹 재료를 API 로 흘리는 순간
    Argon2 파라미터를 아무리 올려도 소용없다.
    ⚠️ 자산·소득도 넣지 않는다 — 관리자는 **가입 승인만** 한다(security.md §3.1).
    """

    id: int
    email: EmailStr
    status: str
    is_admin: bool
    created_at: dt.datetime | None = None
    status_changed_at: dt.datetime | None = None
    status_changed_by: int | None = None
    status_reason: str | None = None


class AdminUserListOut(BaseModel):
    items: list[AdminUserOut]
    #: 승인된 관리자 수. 화면이 "마지막 관리자"를 미리 경고할 수 있게 준다.
    active_admins: int


class RejectIn(BaseModel):
    #: 거부 사유. 감사 흔적으로 남는다(사용자에게 그대로 노출하지 않는다).
    reason: str | None = Field(default=None, max_length=500)


class RecommendationIn(BaseModel):
    region_codes: list[str] = Field(default_factory=list, max_length=50)
    purpose: str = Field(default="live", pattern="^(live|invest)$")
    budget_override_krw: int | None = Field(default=None, ge=0)
    agents: list[str] | None = None
    top_n: int = Field(default=10, ge=1, le=50)
