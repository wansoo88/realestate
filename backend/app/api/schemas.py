"""API 요청·응답 스키마."""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, ClassVar

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.repositories.base import LISTING_MAX_AGE_DAYS, BBox, BBoxError


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


# ---------------------------------------------------------------------------
# 관심 단지 호가 수동 입력 (migrations/016 · `/me/listings`)
#
# 이 값들은 **사람이 손으로 치는 숫자**다. 수집 데이터와 달리 단위 실수·오타가
# 일상적으로 들어온다. 그래서 두 층으로 막는다:
#   ① 절대 불가능한 값 → **422 로 거절**한다(조용히 저장하지 않는다).
#   ② 가능은 하지만 이상한 값 → 저장하되 `problems` 로 **고지**한다.
# 무엇을 어디에 넣을지는 "이 값이 계산에 들어가도 사용자가 손해를 안 보는가"로 가른다.
# ---------------------------------------------------------------------------

#: 호가 하한(원). '15'(억)·'150000'(만원) 같은 단위 실수를 잡는다.
#: 수도권 아파트 실거래 최저가 실측(2025-08 이후 249,235건)이 ₩/㎡ 41.7만 × 면적이라
#: 1천만원 미만은 어떤 조합으로도 나올 수 없다.
MIN_ASK_PRICE_KRW = 10_000_000
#: 호가 상한(원). `AffordabilityIn.target_price_krw` 와 **같은 값** —
#: 같은 성격의 금액을 두 기준으로 검사하면 한쪽만 통과하는 값이 생긴다.
MAX_ASK_PRICE_KRW = 100_000_000_000

#: ★ CR35-11. 그 **단지의 실거래**와 대조하는 경고 구간. 역시 **거절이 아니라 고지**다.
#:
#: 왜 ₩/㎡ 검사만으로는 부족한가 (리뷰어 실측)
#: -------------------------------------------
#: 9.2억을 **3.0억으로 오타**해도 84.97㎡ 기준 353만원/㎡ 라 위 구간(200만~6,000만)
#: 한가운데다. 그래서 아무 경고 없이 저장되고, 카드에는 *"적정가 하단 — 급매 가능"* 이
#: 뜬다. 자릿수 하나를 빠뜨린 값이 **좋은 소식으로 보이는** 형태다.
#: 절대 구간은 "수도권 아파트 어디에도 없는 값"만 잡는다 — 이 단지가 9억대인지
#: 3억대인지는 **그 단지의 실거래**에 물어야 알 수 있다.
#:
#: 구간을 이렇게 잡은 근거 (그 단지 적정가 밴드 중위 대비)
#:   · 아래로 −40%: 층·동·향 편차(F4 실측 dong_effect)와 급매(통상 −10~20%)를 합쳐도
#:     −40% 아래는 설명되지 않는다. 10배·3배 자릿수 실수는 여기 걸린다.
#:   · 위로 +60%: 밴드는 최근 6~36개월 창의 중위라 상승장에서 **낮게** 나온다
#:     (서울 기준 연 10%대 · `base.py` 시장지수 주석). 호가는 원래 체결가보다 높고,
#:     최고층·리모델링 프리미엄까지 얹히면 +50%대가 정상 범위 안에 들어온다.
#: 즉 이 구간은 "이상하다"가 아니라 **"설명되지 않는다"** 를 잡는 폭이다.
#: ⚠️ 막지 않는다. 진짜 급매·진짜 초고가가 있고, 그걸 못 넣게 하면 이 기능의 존재
#:    이유(내가 본 호가를 그대로 적는다)가 사라진다. **말해주되 저장한다.**
BAND_WARN_LOW_RATIO = 0.6
BAND_WARN_HIGH_RATIO = 1.6

#: ₩/㎡ 경고 구간. **거절이 아니라 고지**다.
#: 근거(운영 DB 실측 2026-07-29, 2025-08 이후 수도권 아파트 실거래 249,235건):
#:   200만원/㎡ 미만  2,836건(1.14%)  ·  6,000만원/㎡ 초과  189건(0.08%)
#: 즉 이 구간 밖은 실거래의 1.2% 뿐이다. 10배 단위 실수(1.48억↔14.8억)는 대부분
#: 여기에 걸린다. 다만 강남 초고가는 정상적으로 이 위에 있을 수 있어 **막지 않는다.**
PPM_WARN_LOW_KRW = 2_000_000
PPM_WARN_HIGH_KRW = 60_000_000


#: ★ SR31-1. **두 리포지토리가 다른 입력을 받아들이던 자리.**
#:
#: JSON 의 `"\u0000"` 은 문법상 정상이라 pydantic `str`·`max_length`·`.strip()` 을
#: 전부 통과했다. 인메모리 리포지토리는 그대로 저장해 **201**, PostgreSQL `text` 는
#: NUL 을 담지 못해 `psycopg.DataError` → **500** 이었다(SR-031 실측).
#: 증상보다 나쁜 것은 그 다음이다 — **테스트 1,368건이 운영을 대표하지 못한다.**
#: 인메모리에서 초록인 입력이 운영에서 죽는 구간이 생기면, 그 구간에서는 테스트가
#: 무엇도 보증하지 않는다.
#:
#: 계약을 **더 좁은 쪽(PostgreSQL)에 맞춘다.** 넓은 쪽(인메모리)에 맞추려면 저장
#: 직전에 값을 바꿔야 하는데(제거·치환), 이 두 필드는 *"서버가 이스케이프하지 않고
#: 원문 그대로 보관·반환한다"* 가 명시된 자리다(SR-031 §9-16). 조용히 고치는 것은
#: 이 저장소가 반복해서 막아 온 형태이므로, **받지 않겠다고 말한다**(422).
#:
#: 범위: NUL 을 포함한 C0/C1 제어문자. 탭·줄바꿈(`\t\n\r`)은 **남긴다** — 매물
#: 페이지에서 붙여넣은 메모에 정상적으로 들어오고, PostgreSQL 도 받는다.
#: 이모지·한글·전각은 제어문자가 아니라 그대로 통과한다(SR-031 실측과 일치).
#: ⚠️ DB CHECK 로 옮기지 않는 이유: PostgreSQL 은 NUL 을 **타입 수준**에서 이미
#:    거절하고(CHECK 보다 앞선다), 나머지 제어문자는 저장 가능한 값이라 거절 근거가
#:    표현 계층(사람이 읽는 문자열)에 있다. 016 은 이미 운영 검증을 마친 파일이므로
#:    되돌아가 손대지 않는다.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

#: 오류 문장에 **입력값을 넣지 않는다**(SR25-2 — pydantic 은 ValueError 문자열을
#: 그대로 응답 `msg` 에 반사한다). 어느 문자였는지 알려주면 반사 표면이 된다.
_CONTROL_CHARS_MSG = (
    "보이지 않는 제어문자가 들어 있습니다 — 다른 화면에서 붙여넣을 때 섞인 것 같습니다. "
    "직접 입력하거나 메모장을 거쳐 다시 붙여넣어 주세요"
)


def _clean_optional_text(value: str | None) -> str | None:
    """앞뒤 공백을 털고, 빈 값은 `None`, **제어문자는 거절**(422).

    `apt_dong`·`note` 두 필드가 POST·PATCH 양쪽에서 **같은 함수**를 쓴다.
    복사본을 두면 한쪽만 고쳐지고, 그 순간 "POST 로는 막히는데 PATCH 로는 들어가는"
    값이 생긴다.
    """
    if value is None:
        return None
    if _CONTROL_CHARS_RE.search(value):
        raise ValueError(_CONTROL_CHARS_MSG)
    return value.strip() or None


class UserListingIn(BaseModel):
    """내가 직접 보고 옮겨 적은 호가 (POST).

    ⚠️ **`as_of` 는 필수다.** "지금 얼마인지"를 말하는 데이터인데 언제 본 값인지
       모르면 그건 그냥 숫자다. 기본값(오늘)을 넣지 않는 이유: 사용자는 며칠 전에
       캡처해 둔 값을 옮겨 적는 경우가 많고, 기본값이 있으면 그게 **오늘 값으로
       둔갑**한다. 한 번 더 묻는 편이 낫다.
    """

    complex_id: int = Field(gt=0)
    ask_price_krw: int = Field(ge=MIN_ASK_PRICE_KRW, le=MAX_ASK_PRICE_KRW)
    #: 전용면적. `AffordabilityIn.area_m2` 와 같은 규칙(gt=0, le=1000).
    #: `allow_inf_nan=False` — `Infinity` 는 `gt=0` 을 통과하고(inf > 0) 하류에서
    #: 조용히 조건을 무너뜨린다(SR24-6 과 같은 함정).
    area_m2: float = Field(gt=0, le=1000, allow_inf_nan=False)
    #: 층. 모르면 비운다 — 0 으로 채우면 `dedup.filter_by_avoid` 의 '1층 기피'가
    #: 오작동한다(모름과 1층 이하가 같아진다).
    floor: int | None = Field(default=None, ge=-5, le=200)
    #: 동(棟) 원본 표기('101동'·'101'·'청담(103)'). 적힌 그대로 보존한다.
    apt_dong: str | None = Field(default=None, max_length=20)
    #: **이 호가를 직접 확인한 날짜.** 저장 시각(`created_at`)과 다르다.
    as_of: dt.date
    #: 메모(중개사·특이조건). 근거 문자열에 나갈 수 있으므로 짧게.
    note: str | None = Field(default=None, max_length=200)

    @field_validator("apt_dong", "note")
    @classmethod
    def _strip_or_none(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)

    @field_validator("as_of")
    @classmethod
    def _check_as_of(cls, value: dt.date | None) -> dt.date | None:
        """미래·1년 초과는 **거절**한다.

        ⚠️ 오류 문장에 입력값을 넣지 않는다(SR25-2 — pydantic 은 `ValueError` 문자열을
           그대로 `msg` 로 응답에 반사한다). 날짜는 그 자체로 민감하진 않지만, 같은
           패턴을 금액 필드에 쓰는 순간 사고가 된다. 규칙을 하나로 유지한다.

        ⚠️ `None` 을 그냥 통과시킨다. 이 검증기는 PATCH(`as_of: date | None`)에서도
           **같은 함수로** 재사용되는데, 거기서 `null` 은 "안 건드림"이라는 정상 입력이다.
           None 을 date 처럼 비교하면 TypeError 가 되고, 그건 422 가 아니라 **500** 으로
           나간다 — 사용자 입력 오류가 서버 오류로 보이는 건 다른 종류의 거짓말이다.
           (POST 는 `as_of: dt.date` 라 None 이 타입 단계에서 이미 걸린다.)
        """
        if value is None:
            return None
        today = dt.date.today()
        if value > today:
            raise ValueError("호가를 확인한 날짜가 미래입니다 — 오늘 이전 날짜여야 합니다")
        if (today - value).days > LISTING_MAX_AGE_DAYS:
            raise ValueError(
                f"{LISTING_MAX_AGE_DAYS}일이 넘은 호가는 등록할 수 없습니다 — "
                "서울 기준 1년이면 시세가 10%대로 움직여 '지금 호가'라고 부를 수 "
                "없습니다. 다시 확인한 뒤 오늘 날짜로 등록하세요")
        return value


class UserListingPatch(BaseModel):
    """부분 수정 (PATCH). 준 필드만 바뀐다.

    ⚠️ **가격을 바꾸면 `as_of` 도 함께 받는다**(라우터가 422 로 강제).
       호가는 "얼마"와 "언제 본 값"이 분리될 수 없다 — 가격만 갱신하면 3개월 전
       날짜에 오늘 가격이 붙어, 낡음 판정이 통째로 거짓이 된다.
    """

    ask_price_krw: int | None = Field(default=None, ge=MIN_ASK_PRICE_KRW,
                                      le=MAX_ASK_PRICE_KRW)
    area_m2: float | None = Field(default=None, gt=0, le=1000, allow_inf_nan=False)
    floor: int | None = Field(default=None, ge=-5, le=200)
    apt_dong: str | None = Field(default=None, max_length=20)
    as_of: dt.date | None = None
    note: str | None = Field(default=None, max_length=200)
    #: 'active' 그대로 두거나, 팔렸으면 'traded', 내렸으면 'withdrawn'.
    #: active 가 아니면 추천 계산에서 빠진다(삭제하지 않고 기록을 남기는 길).
    status: str | None = Field(default=None, pattern="^(active|traded|withdrawn)$")

    #: **비울 수 있는 필드.** PATCH 의 규칙은 하나다:
    #:   · 키를 **생략** → 안 건드림
    #:   · 키에 **`null`(또는 빈 문자열)** → 그 값을 비운다
    #: 아래 목록에 없는 필드(`as_of`·`ask_price_krw`·`area_m2`·`status`)에 `null` 을
    #: 보내면 **422** 다 — 비울 수 없는 값이고, 조용히 무시하면 사용자는 지웠다고 믿는다.
    #: (pydantic 은 "생략"과 "명시적 null" 을 `exclude_unset` 으로 구분해 준다 —
    #:  그 구분이 없으면 이 규칙을 만들 수 없다.)
    CLEARABLE: ClassVar[frozenset[str]] = frozenset({"floor", "apt_dong", "note"})

    # ⚠️ POST 와 **같은 함수**를 쓴다. 복사해 두면 한쪽만 고쳐진다(SR31-1).
    @field_validator("apt_dong", "note")
    @classmethod
    def _strip_or_none(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)

    _check_as_of = field_validator("as_of")(UserListingIn._check_as_of.__func__)


class UserListingOut(BaseModel):
    """저장된 호가 1건.

    ⚠️ `source`·`source_label` 을 **항상** 싣는다. 프론트가 각자 라벨을 만들면
       어느 화면에선가 빠지고, 빠진 화면에서 이 숫자는 공공 데이터처럼 보인다.
    ⚠️ `age_days`(값) 와 `staleness`·`eligible_for_recommendation`(판정) 을 둘 다 준다.
       표시 임계값은 바뀔 수 있으니 값이 필요하고, 낡음·상태 판정은 계산 경로와
       **같은 함수**(`listing_usable`)로 해야 두 곳이 갈라지지 않는다.

    ⚠️ 이 필드는 `used_in_recommendation` 이었다 — **서버가 모르는 것을 안다고
       말하는 이름**이었다(CR35-7 · SR31-2). 서버가 아는 것은 "이 호가가 계산에
       들어갈 **자격**이 있는가"(활성 + 안 낡음)뿐이고, 실제로 반영되려면 그 단지가
       추천 요청의 지역·예산·평수 조건과 **후보 조회 상한**을 통과해야 한다.
       그 조회는 소유자 인자를 받지 않으므로(교차 사용자 누출 방지) 사용자 호가는
       조회 단계에서 근거로 세어지지 않는다. 실측: 인천 단지에 넣은 호가가
       `true` 인데 서울만 요청한 추천은 그 호가를 0회 본다.
       → 이름을 **자격**으로 바꾸고, 남은 조건은 `notes` 가 상시로 말한다.
    """

    id: int
    complex_id: int
    complex_name: str | None = None
    ask_price_krw: int
    area_m2: float
    floor: int | None = None
    apt_dong: str | None = None
    as_of: dt.date
    note: str | None = None
    status: str
    source: str
    source_label: str
    #: 확인한 날로부터 며칠 지났나.
    age_days: int
    #: fresh(≤30일) | aging(≤90일) | stale(>90일)
    staleness: str
    #: 이 호가가 추천 계산에 들어갈 **자격**이 있는가(활성 + 안 낡음).
    #: `false` 면 확실히 반영되지 않는다. `true` 는 "반영됐다"가 **아니라**
    #: "이 호가 때문에 빠지지는 않는다"는 뜻이다 — 위 클래스 주석 참고.
    eligible_for_recommendation: bool
    #: ₩/㎡. 단위 실수를 사용자가 스스로 알아채는 가장 빠른 숫자라 응답에 싣는다.
    price_per_m2_krw: int
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class UserListingItemOut(BaseModel):
    """단건 응답 — 저장 결과 + **조용히 넘기지 않은 것들**."""

    item: UserListingOut
    #: 저장은 됐지만 사용자가 알아야 하는 사실(이상 단가·낡음·같은 조건 중복 등).
    #: **비어 있으면 빈 배열**이다 — 키 자체를 빼지 않는다(프론트가 분기하기 쉽게).
    problems: list[str] = Field(default_factory=list)
    #: 이 값 자체에 대한 고정 고지(출처 · `eligible_for_recommendation` 의 한계).
    #: `problems` 와 나눈 이유: 저쪽은 **이 건에만 해당하는 사실**이고 이쪽은 항상
    #: 참인 성질이다. 섞으면 "문제 없음"을 색으로 표시하는 화면이 만들 수 없다.
    #: 단건 응답에도 싣는 이유: 사용자가 `eligible_for_recommendation: true` 를
    #: **처음 보는 자리가 POST 201** 이다. 거기서 조건을 말하지 않으면 목록 화면에
    #: 가기 전에 이미 "반영됐다"고 믿는다(CR35-7 · SR31-2).
    notes: list[str] = Field(default_factory=list)


class UserListingListOut(BaseModel):
    items: list[UserListingOut]
    #: 몇 건이 추천 계산에 들어갈 **자격**이 있는가(`eligible_for_recommendation`).
    #: "다 넣었는데 왜 안 바뀌지"의 **절반**에 답한다 — 나머지 절반(후보 조회에
    #: 잡혔는가)은 서버가 이 화면에서 알 수 없어 `notes` 로 조건을 말한다.
    summary: dict[str, int]
    notes: list[str] = Field(default_factory=list)


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
    #: 단지 id. **`target_price_krw` 없이** 주면 서버가 그 단지·`area_m2` 의 기준가를
    #: **추천 카드와 같은 함수로** 계산해 계획을 세운다(CR34-3 — 같은 단지가 화면마다
    #: 다른 금액으로 보이던 것을 자금계획 쪽에서 끊는다).
    #: 둘 다 주면 `target_price_krw` 가 이긴다 — 사용자가 직접 넣은 숫자를 서버가
    #: 조용히 갈아치우면 슬라이더가 말을 안 듣는 화면이 된다.
    #: 응답의 `target_price.basis` 가 **어느 쪽이 쓰였는지** 항상 말한다.
    complex_id: int | None = Field(default=None, gt=0)


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

    #: ★ SR32-3. `UserListingIn.note` 와 **같은 함수**를 쓴다.
    #: 이 값은 `app_user.status_reason`·`user_status_event.reason`(PostgreSQL `text`)로
    #: 들어가는데, NUL 이 섞이면 인메모리는 200 이고 운영은 `psycopg.DataError` → 500 이다.
    #: 관리자만 닿는 자리라 실현성은 낮지만, 두 구현이 다른 입력을 받아들이는 순간
    #: 그 구간에서는 테스트가 운영을 대표하기를 멈춘다(SR31-1 을 고친 것과 같은 이유).
    @field_validator("reason")
    @classmethod
    def _strip_or_none(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)


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

    # --- 내 조건(선호) — 후보 선별에 실제로 쓰이는 값들 --------------------
    #
    # ⚠️ **여기 없는 조건은 추천에 도달하지 못한다.** 평수가 정확히 그랬다:
    #    지도(`/map/complexes`)에는 `area_min_m2`/`area_max_m2` 가 있는데 추천 요청에는
    #    없어서, 같은 화면의 같은 조건이 지도는 거르고 추천은 안 걸렀다(사용자 제보).
    #    검증 규칙은 `/map/complexes` 와 **같게** 둔다(`gt=0`) — 같은 값을 두 규칙으로
    #    검사하면 한쪽만 통과하는 값이 생기고, 그 순간 두 화면이 서로 다른 말을 한다.
    #
    # 안 보내면 서버가 **저장된 "내 조건"(`user_preference.prefer`)을 폴백으로 쓴다**
    # (app/domain/conditions.py). 프론트가 한 줄 빠뜨려도 조건이 증발하지 않게 하려는 것이다.
    # 보내면 이번 요청에 한해 그 값이 이긴다.
    # ⚠️ `allow_inf_nan=False` (SR24-6). `Infinity` 는 `gt=0` 을 **통과한다**(inf > 0).
    #    통과하면 `_positive_number` 가 뒤에서 `None` 으로 만들어 조건이 사라지는데,
    #    사용자에게는 조건이 걸린 결과처럼 보인다 — 이 제품이 가장 경계하는 조용한 실패다.
    #    `NaN`·`-Infinity` 는 이미 422 이므로 규칙을 하나로 맞춘다(지도 쿼리도 동일).
    area_min_m2: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    area_max_m2: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    built_after: int | None = Field(default=None, ge=1900, le=2100)
    min_households: int | None = Field(default=None, ge=0, le=1_000_000)
    #: 저장된 "내 조건"을 이번 요청에 쓸 것인가. **끄는 방법이 있어야 한다** —
    #: 폴백만 있으면 화면에서 면적 칩을 껐는데 추천은 계속 걸러지는 상태가 되고,
    #: 그건 이번 사고의 거울상(끈 조건이 계속 켜져 있음)이다. `null` 은 "안 보냄"과
    #: 같으므로 이 스위치가 필요하다(값으로는 '조건 없음'을 표현할 수 없다).
    use_saved_conditions: bool = True

    @field_validator("region_codes")
    @classmethod
    def _check_region_codes(cls, value: list[str]) -> list[str]:
        """⚠️ **오류 문장에 입력값을 넣지 않는다**(SR25-2).

        pydantic 은 `ValueError` 의 문자열을 그대로 `msg` 로 만들고, 422 핸들러는
        `msg` 를 통과시킨다. 그래서 여기서 값을 문장에 넣으면 그 값이 **원문 그대로**
        응답으로 되돌아간다(실측: 3,000자 입력 → 응답 3,127바이트 전량 반사).
        지금 이 필드는 법정동코드라 피해가 없지만, 같은 패턴을 자산·비밀번호 필드에
        쓰는 순간 그날 조용히 사고가 된다. **위치(index)로 지목하고 값은 말하지 않는다.**
        """
        out: list[str] = []
        for idx, raw in enumerate(value):
            code = str(raw).strip()
            if not _REGION_CODE_RE.match(code):
                raise ValueError(
                    f"region_codes[{idx}] 가 형식에 맞지 않습니다 — "
                    "숫자 2~10자리 법정동코드여야 합니다(값은 응답에 싣지 않습니다)")
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
