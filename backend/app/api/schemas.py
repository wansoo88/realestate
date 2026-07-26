"""API 요청·응답 스키마."""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.repositories.base import BBox, BBoxError


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
    #: 대출 금리 가정. **소수**다(0.04 = 연 4%). 응답 `plan.terms.annual_rate_pct` 는
    #: 퍼센트(4.0)로 나간다 — 단위가 다르므로 필드명을 다르게 뒀다.
    #: 사용자가 덮을 수 있게 열어 둔 이유: 금리 1%p 차이가 30년 총이자를 30% 넘게 바꾼다.
    #: 우리가 정한 4%를 유일한 진실처럼 보여주면 그 자체가 근거 없는 단정이 된다(G2).
    annual_rate: float = Field(default=0.04, ge=0, le=0.3)
    years: int = Field(default=30, ge=1, le=50)
    apply_dti: bool = False
    #: 희망 매매가(원). 주면 응답에 `plan`(필요 대출·부족액·월 원리금)이 붙는다.
    #: 안 주면 응답은 예전과 완전히 동일하다 — 기존 클라이언트는 영향받지 않는다.
    #: 상한 1,000억: 슬라이더 오조작이나 단위 실수(만원↔원)를 **조용히 계산하지 않고**
    #: 422 로 되돌린다. 0·음수도 422다(가격 없는 계획은 계획이 아니다).
    target_price_krw: int | None = Field(default=None, gt=0, le=100_000_000_000)


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


#: 법정동코드는 숫자만이다 — 시도(2) · 시군구(5) · 읍면동(8) · 리 포함(10).
#: **왜 정규식으로 막나 (SR21-4)**: 접두 매칭에 `%`·`_` 가 섞이면 SQL `LIKE` 가
#: 에러 없이 전 지역을 매칭해 "강남만 보기"가 조용히 "전국"이 된다. 인젝션은 아니지만
#: 실패가 실패로 보이지 않아서 더 나쁘다 — 그래서 **거절**한다(조용히 지우지 않는다).
_REGION_CODE_RE = re.compile(r"^\d{2,10}$")


class RecommendationIn(BaseModel):
    region_codes: list[str] = Field(default_factory=list, max_length=50)
    #: "이 주변에서 검색" — 지도에서 보고 있는 범위 (REC-5).
    #: 형식은 `/map/complexes` 의 `bbox` 와 **같다**: `minLon,minLat,maxLon,maxLat`.
    #: 형식이 갈라지면 프론트가 같은 값을 두 번 다르게 만들어야 하고, 그러면
    #: 지도에 보이는 범위와 추천 대상이 언젠가 조용히 어긋난다.
    #:
    #: `region_codes` 와 **둘 다 오면 교집합**이다(지역도 고르고 "이 주변"도 눌렀다면
    #: 둘 다 만족하는 게 자연스럽다). 둘 다 없으면 기존대로 전체.
    bbox: str | None = Field(
        default=None, max_length=100,
        description="minLon,minLat,maxLon,maxLat (WGS84). /map/complexes 와 같은 형식")
    purpose: str = Field(default="live", pattern="^(live|invest)$")
    budget_override_krw: int | None = Field(default=None, ge=0)
    agents: list[str] | None = None
    top_n: int = Field(default=10, ge=1, le=50)

    @field_validator("region_codes")
    @classmethod
    def _check_region_codes(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for raw in value:
            code = str(raw).strip()
            if not _REGION_CODE_RE.match(code):
                raise ValueError(
                    f"region_codes 는 숫자 2~10자리 법정동코드여야 합니다: {code!r}")
            out.append(code)
        return out

    @field_validator("bbox")
    @classmethod
    def _check_bbox(cls, value: str | None) -> str | None:
        """형식·좌표범위·면적 상한을 여기서 막는다 → 위반이면 **422**.

        파싱 결과를 버리고 원문을 그대로 둔다: `criteria_snapshot` 은 재현성 근거라
        **사용자가 보낸 값 그대로** 남아야 한다(러너가 같은 파서로 다시 읽는다).
        """
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None                     # 빈 문자열은 "안 보냄"과 같게 취급한다
        try:
            BBox.parse(text)
        except BBoxError as exc:
            raise ValueError(str(exc)) from exc
        return text
