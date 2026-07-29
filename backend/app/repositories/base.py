"""데이터 접근 인터페이스.

왜 Protocol 로 감싸나
---------------------
로컬에 Docker 가 없어 PostGIS 를 띄울 수 없다(implementation-plan.md §0).
DB 접근을 인터페이스 뒤에 두면 **가짜 구현으로 API 전체를 테스트**할 수 있다.
배포 시 PostGIS 구현으로 갈아끼우기만 하면 된다.

⚠️ IDOR 방지 규약 (security.md §2.2)
------------------------------------
사용자 자원을 다루는 모든 메서드는 **`user_id` 를 필수 인자로 받는다.**
`get_job(job_id)` 같은 시그니처는 만들지 않는다 — 만들 수 있으면 언젠가 쓰이고,
그 순간 남의 추천 결과가 새어나간다.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, NamedTuple, Protocol, runtime_checkable

from app.domain.location.models import BuildingLocationFact, LocationFacts
from app.domain.valuation.models import LISTING_SOURCE_USER as _LISTING_SOURCE_USER

# ---------------------------------------------------------------------------
# 조회 범위 (지도 · 추천 공용)
#
# `/map/complexes` 와 `POST /recommendations` 가 **같은 형식**의 bbox 를 받는다.
# 형식이 갈라지면 프론트가 "지도에서 보고 있는 범위"를 두 번 다르게 만들어야 하고,
# 그 순간 지도에 보이는 것과 추천 대상이 조용히 어긋난다.
# 그래서 파싱·검증을 **한 곳**에 둔다.
# ---------------------------------------------------------------------------

#: bbox 한 변의 최대 각도. 2도면 수도권 전체(약 1.5° × 1.2°)를 덮는다.
#: 이보다 넓은 요청은 "이 주변"이 아니라 전국 스캔이고, 서버를 태운다.
MAX_BBOX_DEGREES = 2.0


class BBoxError(ValueError):
    """bbox 문자열이 계약을 벗어났다. 호출부가 400/422 로 옮긴다."""


class BBox(NamedTuple):
    """지도 범위. `minLon,minLat,maxLon,maxLat` (WGS84 / EPSG:4326).

    순서를 헷갈리기 쉬워(경도가 먼저다) 튜플이 아니라 이름 있는 필드로 든다 —
    `lat/lon` 이 뒤집히면 조회는 **에러 없이 0건**을 돌려주고, 그건 "그 범위에
    단지가 없다"와 구분되지 않는다(이 프로젝트가 가장 경계하는 조용한 실패).
    """

    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    @classmethod
    def parse(cls, raw: str) -> BBox:
        """`"126.9,37.5,127.1,37.6"` → BBox. 어긋나면 `BBoxError`."""
        if not isinstance(raw, str):
            raise BBoxError("bbox 는 minLon,minLat,maxLon,maxLat 형식의 문자열이어야 합니다")
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) != 4:
            raise BBoxError("bbox 는 minLon,minLat,maxLon,maxLat 형식이어야 합니다")
        try:
            values = [float(p) for p in parts]
        except (TypeError, ValueError) as exc:
            raise BBoxError("bbox 의 좌표는 숫자여야 합니다") from exc
        # NaN/Inf 는 float() 를 통과한다. 비교 연산이 전부 False 라 아래 검증을
        # 조용히 빠져나가고, SQL 에서는 빈 결과가 된다.
        if any(v != v or v in (float("inf"), float("-inf")) for v in values):
            raise BBoxError("bbox 의 좌표가 유효한 숫자가 아닙니다")

        box = cls(*values)
        if not (-180.0 <= box.min_lon <= 180.0 and -180.0 <= box.max_lon <= 180.0):
            raise BBoxError("경도는 -180~180 범위여야 합니다")
        if not (-90.0 <= box.min_lat <= 90.0 and -90.0 <= box.max_lat <= 90.0):
            raise BBoxError("위도는 -90~90 범위여야 합니다")
        if box.min_lon >= box.max_lon or box.min_lat >= box.max_lat:
            raise BBoxError("bbox 범위가 올바르지 않습니다(min 은 max 보다 작아야 합니다)")
        if box.width > MAX_BBOX_DEGREES or box.height > MAX_BBOX_DEGREES:
            raise BBoxError("조회 범위가 너무 넓습니다")
        return box

    @property
    def width(self) -> float:
        return self.max_lon - self.min_lon

    @property
    def height(self) -> float:
        return self.max_lat - self.min_lat

    def as_text(self) -> str:
        """받은 그대로 되돌려 주기 위한 정규 표기(로그·재현성 스냅샷용)."""
        return f"{self.min_lon},{self.min_lat},{self.max_lon},{self.max_lat}"

# --- 가입 승인 상태 (migrations/009) ---------------------------------------
#: 기본값. 가입은 되지만 **로그인은 안 된다** — 관리자가 검토할 때까지.
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
USER_STATUSES = (STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED)


# ---------------------------------------------------------------------------
# 사용자 수동 입력 호가 (migrations/016)
#
# 공공 오픈API 에는 호가가 없고 포털 자동수집은 약관·판례상 하지 않는다. 그래서
# `listing` 테이블은 운영에서 **0행**이었고(2026-07-29 실측), 가격·리스크 축이
# 통째로 죽어 있었다. 남은 합법적인 경로가 **사용자가 손으로 옮겨 적는 것**이다.
#
# 이 데이터는 수집 데이터와 성질이 완전히 다르다:
#   · 출처가 사람이라 **누구 것인지**가 있다(공공 데이터에는 소유자가 없다)
#   · 확인 시점이 사람의 기억에 달려 있어 **언제 본 값인지**를 반드시 받아야 한다
#   · 자동 갱신되지 않는다 — 아무도 안 고치면 그 값은 **영원히 그날의 값**이다
# 그래서 아래 세 상수가 이 기능의 성격을 결정한다.
# ---------------------------------------------------------------------------

#: `listing.source` 값. DB CHECK(`listing_user_source_pair`)가 `created_by_user_id`
#: 와 짝을 강제한다 — 이 문자열을 바꾸면 마이그레이션 016 도 함께 바꿔야 한다.
#:
#: ⚠️ **정본은 `app/domain/valuation/models.py` 에 있다**(여기서는 재수출한다).
#:    분석 계층이 이 값으로 신뢰도 산정 여부를 가르기 때문이다 — 두 곳에 같은 리터럴을
#:    두면 한쪽만 바뀌는 날 사용자 입력이 조용히 수집 데이터로 분류되고, 그 순간
#:    가짜 신뢰도 100점이 되살아난다. 이름은 그대로 두어 기존 import 를 깨지 않는다.
LISTING_SOURCE_USER = _LISTING_SOURCE_USER
#: 화면·근거 문자열에 그대로 나가는 출처 표기. **서버가 붙인다.**
#: 프론트가 각자 만들면 어느 화면에선가 빠지고, 빠진 화면에서는 사용자 입력이
#: 공공 데이터처럼 보인다 — 그 순간 "무엇이 근거였나"에 답할 수 없게 된다(G2).
LISTING_SOURCE_USER_LABEL = "사용자 입력"

# --- 낡음 판정 -------------------------------------------------------------
#
# 근거 (운영 DB 실측, 2026-07-29 · `market_price_index` scope='sido')
# -------------------------------------------------------------------
# 완결월(is_complete)만으로 최근 구간을 재면 월평균 상승률은
#     서울(11) 2025-10 1.038446 → 2026-05 1.112226 : 7개월 +7.10% → **+0.99%/월**
#     경기(41) 2025-10 1.003529 → 2026-05 1.034474 : 7개월 +3.08% → +0.43%/월
#     인천(28) 2025-10 1.006645 → 2026-05 1.011518 : 7개월 +0.48% → +0.07%/월
# 서울의 실측 최대 3개월 구간 이동은 +3.3%(2026-02→2026-05), 6개월은 +7.1%다.
#
# 이 숫자가 왜 중요한가: 가격 축 점수는 `100 - |호가갭%| * 5` 이고 판정이 ±10% 에서
# 뒤집힌다(`orchestrator.valuation_finding`). 즉 호가가 X% 낡으면 점수가 5X 점
# 어긋난다. 90일(서울 최대 +3.3%)이면 약 17점, 180일(+7.1%)이면 약 35점이고
# 판정 경계 ±10% 에 육박한다 — 그때는 "적정가 범위"가 "급매"로 뒤집힌다.
#
# 그래서 세 구간으로 나눈다. 자르기만 하지 않고 **말한다**:
#   fresh (≤30일)  그대로 쓴다. 서울 기준 예상 이동 ≈1.0%(점수 ≈5점).
#   aging (≤90일)  쓰되 며칠 된 값인지 고지한다. 최대 ≈3.3%(점수 ≈17점).
#   stale (>90일)  **추천 계산에서 뺀다.** 목록에는 남기고 갱신을 유도한다.
#
# 왜 30일을 하한으로 두지 않는가: 비교 대상인 실거래도 신고까지 최대 30일 걸린다
# (`orchestrator.DELAY_RISK`). 호가에만 30일 미만을 요구하면 밴드보다 엄격한 잣대다.
# 참고: `domain/listings/dedup.STALE_DAYS` 도 90일이지만 **다른 뜻**이다(등록 후
# 90일간 안 팔림 = 의심 신호). 우연히 같은 값이며 서로 묶지 않는다.
LISTING_FRESH_DAYS = 30
LISTING_STALE_DAYS = 90
#: 이보다 오래된 날짜는 입력 자체를 거절한다(422). 서울 기준 1년이면 +12% 이동이라
#: 어떤 해석으로도 "지금 호가"가 아니고, 실제로는 날짜 오타일 확률이 더 높다.
LISTING_MAX_AGE_DAYS = 365

#: ★ 사용자 1명이 만들 수 있는 호가 행 수 상한 (SR31-3 · CR35-8).
#:
#: 왜 두는가 — `POST /me/listings` 는 **행을 무제한 만드는 첫 엔드포인트**다
#: (프로필·선호는 1행 upsert). nginx `re_api` 10r/s 면 승인 계정 하나가 하루 ~86만 행,
#: 행+인덱스 ~600B 기준 하루 ~500MB 다. 운영 `/` 는 **92% 사용 · 여유 2.2GB** 이고
#: db 컨테이너는 `mem_limit 192m` · 스왑 없음이다. 악의가 아니라 **클라이언트 재시도
#: 루프 하나**로도 도달한다. 상한이 없으면 그때 디스크가 먼저 죽고, 같은 호스트의
#: 다른 서비스까지 함께 죽는다.
#:
#: 왜 하필 목록 상한과 **같은 값**인가 — `list_user_listings` 가 200건에서 자르는데
#: 그보다 많이 만들 수 있으면 `summary.total` 과 중복 경고(`siblings`)가 **조용히**
#: 틀린다(201건째부터 "이미 N건 등록돼 있습니다"가 거짓이 된다 — CR35-8).
#: 두 숫자를 하나로 묶으면 그 상태가 아예 만들어지지 않는다. 나눠 두면 언젠가
#: 한쪽만 바뀐다.
#:
#: 200 이면 충분한가 — 이 도구의 사용 맥락은 "관심 단지 5~10곳"이고, 가격이 바뀐
#: 경우는 새로 넣는 게 아니라 **PATCH** 하도록 서버가 안내한다(`problems`).
#: 모자라면 사용자가 지우거나 상태를 바꿀 수 있고, 상한에 닿으면 서버가 **그렇게
#: 말한다**(조용히 거절하지 않는다).
MAX_USER_LISTINGS = 200

STALENESS_FRESH = "fresh"
STALENESS_AGING = "aging"
STALENESS_STALE = "stale"


def listing_staleness(as_of: dt.date | None,
                      today: dt.date | None = None) -> tuple[str, int | None]:
    """호가의 낡음 등급과 경과일수. `as_of` 가 없으면 **stale** 로 본다.

    시점을 모르는 호가를 신선하다고 가정하지 않는다 — 모름은 통과가 아니다.
    미래 날짜(입력 검증을 우회해 들어온 값)는 경과일수 0 의 fresh 로 접는다.
    """
    if as_of is None:
        return STALENESS_STALE, None
    days = max(0, ((today or dt.date.today()) - as_of).days)
    if days <= LISTING_FRESH_DAYS:
        return STALENESS_FRESH, days
    if days <= LISTING_STALE_DAYS:
        return STALENESS_AGING, days
    return STALENESS_STALE, days


def listing_usable(as_of: dt.date | None, status: str,
                   today: dt.date | None = None) -> bool:
    """이 호가를 **추천 계산에 넣어도 되는가**(= 이 호가 자체의 자격).

    리포지토리 읽기 경로(`listings_for_complex`)와 API 표시
    (`eligible_for_recommendation`)가 **같은 함수**를 본다. 두 곳이 따로 판정하면
    화면은 "반영됨"이라 적어 놓고 계산에는 안 들어간 상태가 생기고, 그건 사용자가
    알아챌 방법이 없다.

    ⚠️ **이 함수는 "실제로 반영됐는가"를 답하지 않는다.** 반영되려면 그 단지가
       추천 요청의 지역·예산·평수 조건과 후보 조회 상한까지 통과해야 하고, 그건
       이 함수가 볼 수 있는 범위 밖이다. API 필드 이름이 `used_…` 가 아니라
       `eligible_…` 인 이유다(CR35-7 · SR31-2).
    """
    if status != "active":
        return False
    grade, _ = listing_staleness(as_of, today)
    return grade != STALENESS_STALE


class LastAdminError(Exception):
    """마지막 관리자를 거부·강등하려 했다.

    관리자가 0명이 되면 **어떤 신규 가입도 승인할 수 없는 상태**가 되고,
    복구하려면 서버에 SSH 로 들어가 CLI 를 돌리는 수밖에 없다.
    실수 한 번으로 그 상태에 빠지지 않게 리포지토리가 거절한다.
    """


@dataclass
class UserRecord:
    """사용자.

    ⚠️ `status`·`is_admin` 은 **서버 DB 가 진실 소스**다. JWT 에 담지 않는다 —
    토큰에 실으면 클라이언트가 주장하는 값이 되고, 그 순간 위조 표면이 생긴다
    (security.md §2.2 와 같은 강도).
    """

    id: int
    email: str
    password_hash: str
    #: 'pending' | 'approved' | 'rejected'. 기본은 승인 대기다.
    status: str = STATUS_PENDING
    is_admin: bool = False
    created_at: dt.datetime | None = None
    # -- 감사 흔적 (누가 언제 왜 상태를 바꿨나) --
    status_changed_at: dt.datetime | None = None
    status_changed_by: int | None = None
    status_reason: str | None = None

    @property
    def is_approved(self) -> bool:
        return self.status == STATUS_APPROVED

    @property
    def can_administer(self) -> bool:
        """관리자 권한의 **유일한 판정식.**

        승인되지 않은 관리자는 관리자가 아니다 — 거부된 계정에 남아 있던
        `is_admin` 이 되살아나는 경로를 만들지 않는다.
        """
        return self.is_admin and self.is_approved


@dataclass
class ProfileRecord:
    """자산 3종은 **암호문(bytes)** 으로만 오간다. 평문 int 를 담지 않는다."""

    user_id: int
    cash_krw_enc: bytes | None = None
    income_krw_enc: bytes | None = None
    existing_loan_krw_enc: bytes | None = None
    owned_houses: int = 0
    household_size: int = 1


@dataclass(frozen=True)
class NearestStationFact:
    """최근접 역 — **값이지 판정이 아니다.**

    임계값(역세권 500m)은 표시 관례라 바뀐다. 서버가 boolean 으로 굳혀 보내면
    과거에 저장된 결과에 옛 임계값이 박히고 되돌릴 수 없다. 그래서 거리(m)를 준다.
    블록 자체가 `None` 이면 **"역이 없다"가 아니라 "탐색 반경 안에서 못 찾았다"** 이다.
    거리는 직선거리(geography)이며 도보 거리가 아니다 — `basis` 가 그것을 못박는다.
    """

    distance_m: float
    name: str | None = None
    lines: tuple[str, ...] = ()
    basis: str = "straight_line"

    @property
    def line_count(self) -> int:
        return len(self.lines)


@dataclass(frozen=True)
class RedevelopmentFact:
    """정비사업 구역 매칭 **사실**(단계 해석은 도메인이 한다).

    ⚠️ `available=False` 는 **'정비사업이 없다'가 아니라 '확인되지 않았다'** 이다
       (수집 범위: 서울·인천. 경기도 미수집 · 대표지번 파싱 실패분 존재).
       이 구분이 무너지면 화면이 "이 단지는 재건축 아님"이라고 **거짓 단언**을 한다.
    """

    available: bool = False
    stage: str = "unknown"
    raw_stage: str = ""
    zone_name: str | None = None


@dataclass
class ComplexSummary:
    id: int
    name: str
    #: ⚠️ **None 일 수 있다.** 주소 지오코딩이 안 된 단지는 `complex.geom` 이 NULL 이고,
    #: `recommendation_candidates`(지역 조회)는 그런 단지도 그대로 돌려준다 —
    #: 좌표가 없다고 추천 대상에서 빼면 사용자는 그 단지를 영영 못 본다.
    #: 반대로 `complexes_in_bbox`·bbox 추천은 공간 연산이라 **구조적으로 빠진다**.
    lon: float | None
    lat: float | None
    region_code: str
    built_year: int | None = None
    total_households: int | None = None
    #: **최근 체결가**(원). 시점 보정된 추정치가 아니라 실제로 체결된 1건이다 —
    #: 추천 카드의 `est_price_krw`(창 중위를 기준월로 환산한 추정가)와 **다른 양**이고,
    #: 운영 실측 226단지에서 중위 −2.4%·p10 −13.3% 어긋난다(CR34-3). 덮어쓰지 말 것.
    recent_price_krw: int | None = None
    price_as_of: str | None = None
    #: 그 체결가가 **어느 면적**의 거래인가(㎡). 지도 조회에서만 채워진다.
    #: 면적을 안 말하면 34㎡ 체결가가 84㎡ 를 찾는 사용자의 화면에서 그 단지 가격이 된다.
    price_area_m2: float | None = None
    active_listings: int = 0
    #: 지도 화면의 특성 태그(🚇역세권·🔨재건축)용 사실. **지도 조회에만** 채워진다
    #: (`complexes_in_bbox`). 추천 경로는 같은 값을 입지·정비사업 분석에서 얻으므로
    #: 여기서 다시 재지 않는다 — 같은 숫자를 두 곳에서 만들면 언젠가 어긋난다.
    #: `None` 은 **모름**이다. 0·False 로 접지 않는다.
    nearest_station: NearestStationFact | None = None
    redevelopment: RedevelopmentFact | None = None


@dataclass(frozen=True)
class UserListingRecord:
    """사용자가 손으로 옮겨 적은 호가 1건 (migrations/016).

    ⚠️ **소유자(`user_id`)가 없는 이 레코드는 존재할 수 없다.** DB CHECK
       (`listing_user_source_pair`)가 그것을 강제하고, 이 dataclass 도 필수 필드로 둔다.
       소유자 없는 사용자 데이터가 만들어질 수 있으면 언젠가 그게 남에게 보인다.

    ⚠️ `source` 는 항상 `LISTING_SOURCE_USER` 다. 필드로 들고 다니는 이유는 응답·근거
       문자열에 **그대로 실어 보내기 위해서**다 — "이 숫자는 사용자 입력"이라는 사실은
       화면에서 지워지면 안 된다.
    """

    id: int
    user_id: int
    complex_id: int
    ask_price_krw: int
    area_m2: float
    as_of: dt.date
    floor: int | None = None
    apt_dong: str | None = None
    note: str | None = None
    status: str = "active"
    source: str = LISTING_SOURCE_USER
    #: 표시용 단지명(조인). 없으면 화면이 "단지 #1234" 밖에 못 쓴다.
    complex_name: str | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None

    def staleness(self, today: dt.date | None = None) -> tuple[str, int | None]:
        return listing_staleness(self.as_of, today)

    def usable(self, today: dt.date | None = None) -> bool:
        """추천 계산에 실제로 들어가는가. 표시와 계산이 **같은 판정**을 보게 한다."""
        return listing_usable(self.as_of, self.status, today)


@dataclass
class JobRecord:
    id: str
    user_id: int
    criteria_snapshot: dict[str, Any] = field(default_factory=dict)
    status: str = "queued"
    items: list[dict[str, Any]] = field(default_factory=list)
    #: 제외된 후보와 사유. **추천 목록의 반쪽**이다 — "왜 이건 안 나왔지"에 답하는 자리.
    #: 비어 있는 것과 저장 경로가 없어 사라진 것은 다르다(후자는 사용자가 결과를 못 믿는다).
    excluded: list[dict[str, Any]] = field(default_factory=list)
    #: 결과 전체에 붙는 단서(추정 표기·미구현 기능 고지 등).
    notes: list[str] = field(default_factory=list)


@runtime_checkable
class UserRepository(Protocol):
    def create_user(self, email: str, password_hash: str) -> UserRecord: ...
    def get_user_by_email(self, email: str) -> UserRecord | None: ...
    def get_user(self, user_id: int) -> UserRecord | None: ...


@runtime_checkable
class UserAdminRepository(Protocol):
    """관리자 승인 (migrations/009).

    ⚠️ **마지막 관리자 보호는 여기서 한다.** 라우터에서만 검사하면 CLI 가 그 검사를
    비켜가고, CLI 에서만 검사하면 API 가 비켜간다. 상태를 바꾸는 **단 하나의 길목**인
    리포지토리가 거절해야 두 경로 모두 막힌다(`LastAdminError`).
    """

    def list_users(self, *, status: str | None = None,
                   limit: int = 100) -> list[UserRecord]: ...

    #: 상태 변경 + 감사 기록을 **한 트랜잭션**으로. 대상이 없으면 None.
    def set_user_status(self, user_id: int, status: str, *,
                        actor: str, actor_user_id: int | None = None,
                        reason: str | None = None) -> UserRecord | None: ...

    def set_user_admin(self, user_id: int, is_admin: bool, *,
                       actor: str, actor_user_id: int | None = None) -> UserRecord | None: ...

    #: 승인된 관리자 수. 0명이 되는 변경을 막는 데 쓴다.
    def count_active_admins(self) -> int: ...


@runtime_checkable
class ProfileRepository(Protocol):
    def get_profile(self, user_id: int) -> ProfileRecord | None: ...
    def upsert_profile(self, profile: ProfileRecord) -> ProfileRecord: ...
    def get_preferences(self, user_id: int) -> dict[str, Any]: ...
    def set_preferences(self, user_id: int, prefs: dict[str, Any]) -> dict[str, Any]: ...


@runtime_checkable
class MapRepository(Protocol):
    def complexes_in_bbox(
        self,
        *,
        min_lon: float, min_lat: float, max_lon: float, max_lat: float,
        max_price_krw: int | None = None,
        area_min_m2: float | None = None,
        area_max_m2: float | None = None,
        built_after: int | None = None,
        limit: int = 500,
    ) -> list[ComplexSummary]: ...


@runtime_checkable
class JobRepository(Protocol):
    def create_job(self, job_id: str, user_id: int,
                   criteria: dict[str, Any]) -> JobRecord: ...
    #: user_id 필수 — 소유권 검증 없이 조회할 방법을 만들지 않는다
    def get_job(self, job_id: str, user_id: int) -> JobRecord | None: ...


@runtime_checkable
class RecommendationRepository(Protocol):
    """추천 러너가 쓰는 조회·저장 (docs/domain/recommendation-execution.md §repo인터페이스).

    러너는 이 메서드들을 **duck-typing 으로** 부른다 — 없으면 경고 후 빈 결과로
    degrade 한다. 즉 시그니처가 어긋나도 크래시하지 않고 **추천이 조용히 비어** 버린다.
    그 침묵이 위험해서 Protocol 로 박아 둔다: 두 구현 모두 `isinstance` 로 검증한다.
    """

    #: 후보 단지 조회.
    #:
    #: ⚠️ `region_codes` 와 `bbox` 가 **둘 다 오면 교집합**이다(AND). 사용자가 지역을
    #:    고르고 "이 주변"까지 눌렀다면 둘 다 만족하는 단지를 원한 것이다.
    #:    ⚠️ `bbox` 는 **좌표가 있는 단지만** 찾는다 — geom 이 NULL 이면 공간 연산이
    #:       NULL 을 내고 자연히 빠진다. 호출부는 이 사실을 사용자에게 고지해야 한다
    #:       (좌표 확보율이 100% 가 아니다 · `geocode_coverage`).
    #:
    #: ⚠️ **내 조건(평수·연식·세대수)은 여기서 걸러야 한다.** 예산과 달리 이건
    #:    "제외 사유"가 아니라 **후보가 아님**이다 — 59㎡를 원하는 사람에게 84㎡ 는
    #:    사유를 달아 봐야 답이 아니고, 조회 상한(50개 단지)만 잡아먹는다.
    #:    미상(면적·연식·세대수 NULL)은 **통과시키지 않는다**(모르는 것을 조건에 맞다고
    #:    우기면 "조건에 안 맞는 게 나온다"가 그대로 재현된다). 대신 몇 개가 그렇게
    #:    빠졌는지는 `candidate_scope_stats` 가 세고 러너가 notes 로 말한다.
    def recommendation_candidates(
        self, *, region_codes: list[str], max_price_krw: int | None = None,
        limit: int = 50, bbox: BBox | None = None,
        area_min_m2: float | None = None, area_max_m2: float | None = None,
        built_after: int | None = None, min_households: int | None = None,
    ) -> list[ComplexSummary]: ...

    #: 조건 때문에 조회에서 빠진 단지 수 `{scope_total, area_dropped, built_dropped,
    #: built_unknown, households_dropped, households_unknown}`.
    #: **거르는 것과 말하지 않는 것은 다르다** — 세지 않으면 "왜 3건뿐이냐"에 답할 수 없다.
    def candidate_scope_stats(
        self, *, region_codes: list[str] | None = None, bbox: BBox | None = None,
        area_min_m2: float | None = None, area_max_m2: float | None = None,
        built_after: int | None = None, min_households: int | None = None,
    ) -> dict[str, int]: ...

    #: 좌표 확보 현황 `(좌표 있는 단지 수, 전체 단지 수)`.
    #: bbox 검색에서 **몇 개가 구조적으로 빠지는지**를 숫자로 말하기 위한 것이다.
    #: 고정 문구("약 5%")로 적으면 수집이 진행돼도 영영 낡은 값이 남는다.
    def geocode_coverage(
        self, *, region_codes: list[str] | None = None) -> tuple[int, int]: ...

    #: 활성 호가. **중복 포함** — 대표건 선정은 러너의 group_duplicates 몫이다.
    #:
    #: ⚠️ **`user_id` 를 주지 않으면 사용자 입력 호가는 한 건도 나오지 않는다**
    #:    (migrations/016). 기본값을 "전부 보여줌"이 아니라 "하나도 안 보여줌"으로 둔
    #:    이유는 fail-closed 다 — 배선을 잊은 호출부에서 **남의 호가가 새는 쪽**이 아니라
    #:    **아무것도 안 보이는 쪽**으로 실패하게 만든다(security.md §2.2 IDOR 규약).
    #:    조용한 누출보다 조용한 결측이 낫다. 결측은 사용자가 "내 매물이 왜 안 보이지"로
    #:    알아채지만, 누출은 아무도 알아채지 못한다.
    #: ⚠️ 낡은 사용자 호가(as_of 가 `LISTING_STALE_DAYS` 초과)는 **여기서 빠진다.**
    #:    호출부가 거르기를 기대하지 않는다 — 한 곳이라도 잊으면 3개월 전 호가가
    #:    현재 호가로 계산에 들어간다.
    def listings_for_complex(self, complex_id: int,
                             user_id: int | None = None) -> list[Any]: ...

    #: 실거래. **해제건 포함** — 제외 여부는 통계 계층이 정한다.
    def trades_for_complex(self, complex_id: int) -> list[Any]: ...

    #: user_id 필수 — 결과를 되쓸 때도 소유권을 다시 확인한다(IDOR).
    #:
    #: ⚠️ `excluded`·`notes` 는 **선택 인자가 아니라 계약의 일부**다. 구현이 이 인자를
    #:    받지 않으면 러너의 호출이 TypeError 로 죽어 결과가 통째로 사라진다. 기본값을
    #:    둔 것은 옛 호출부(테스트)를 위해서지 "안 실어도 된다"는 뜻이 아니다 —
    #:    저장하지 않으면 사용자는 "왜 이건 안 나왔지"에 답을 받지 못한다.
    def save_job_result(self, job_id: str, user_id: int, *, status: str,
                        items: list[dict[str, Any]],
                        excluded: list[dict[str, Any]] | None = None,
                        notes: list[str] | None = None) -> None: ...


@runtime_checkable
class UserListingRepository(Protocol):
    """사용자 수동 입력 호가 CRUD (migrations/016 · `POST /me/listings`).

    IDOR 규약 (security.md §2.2)
    ---------------------------
    **읽기·수정·삭제 모두 `user_id` 를 필수 인자로 받는다.** `get_user_listing(id)`
    같은 시그니처는 만들지 않는다 — 만들 수 있으면 언젠가 쓰이고, 그 순간 남의
    관심 단지·호가(= 그 사람이 어디를 사려는지)가 새어나간다. 자산 금액만큼은
    아니어도 이것 역시 **개인의 매수 의사**를 그대로 드러내는 정보다.

    없는 id 와 남의 id 는 **같은 결과**(None/False)를 낸다. 구분하면 그 차이가
    "그 id 는 존재한다"는 정보가 된다(라우터가 둘 다 404 로 옮긴다).
    """

    #: 단지 존재 확인 + 표시용 이름. 없으면 None → 라우터가 404.
    #: 존재하지 않는 complex_id 로 저장하면 FK 위반이 500 으로 튀거나(PostGIS),
    #: 조용히 들어가 영영 조회되지 않는다(인메모리) — 둘 다 나쁘다.
    def complex_name(self, complex_id: int) -> str | None: ...

    def add_user_listing(self, user_id: int, *, complex_id: int,
                         ask_price_krw: int, area_m2: float, as_of: dt.date,
                         floor: int | None = None, apt_dong: str | None = None,
                         note: str | None = None) -> UserListingRecord: ...

    #: 내 호가 목록. **낡은 것도 함께** 돌려준다 — 목록은 고치라고 보여주는 화면이라
    #: 낡은 건을 숨기면 사용자가 갱신할 대상을 볼 수 없다(계산 경로와 다르다).
    #:
    #: ⚠️ 기본 상한은 `MAX_USER_LISTINGS` 와 **같은 상수**여야 한다(CR36-4). 여기만
    #:    리터럴 `200` 이면 상한을 300 으로 올리는 날 목록이 200에서 잘리고, 그 순간
    #:    `summary.total` 과 중복 경고(`siblings`)가 조용히 틀린다(CR35-8 이 막은 상태).
    def list_user_listings(self, user_id: int, *, complex_id: int | None = None,
                           limit: int = MAX_USER_LISTINGS) -> list[UserListingRecord]: ...

    def get_user_listing(self, listing_id: int,
                         user_id: int) -> UserListingRecord | None: ...

    #: 부분 수정. `fields` 에 준 키만 바꾼다(None 을 "지우기"로 오해하지 않는다).
    #: 대상이 없거나 남의 것이면 None.
    def update_user_listing(self, listing_id: int, user_id: int,
                            **fields: Any) -> UserListingRecord | None: ...

    #: 지웠으면 True, 없거나 남의 것이면 False.
    def delete_user_listing(self, listing_id: int, user_id: int) -> bool: ...


@runtime_checkable
class LocationRepository(Protocol):
    """입지 사실 조립 — `location-analyst`(re-domain) 의 입력을 만든다.

    경계 (domain/location/models.py 의 규약과 짝을 이룬다)
    -----------------------------------------------------
    **공간 판정은 전부 여기서 한다.** 학구도 포함 여부(`ST_Contains`),
    역·POI·유해요소 최단거리(`ST_Distance`)를 DB 에서 계산해 사실만 넘기고,
    그걸 점수·근거로 바꾸는 일은 도메인 계층이 한다. 반대 방향으로 새면 안 된다 —
    리포지토리가 점수를 매기기 시작하면 근거 감사(G2)가 두 곳을 봐야 한다.

    ⚠️ 데이터가 없으면 **추정하지 않고 비운다.**
    학구도가 없으면 `SchoolFact.district_data_available=False` 로 넘기고,
    최근접 학교 거리로 배정을 대체하지 않는다(배정과 거리는 다른 개념).
    거리를 모르면 `None` 이다 — 0 이나 임의값으로 채우지 않는다.
    """

    def location_facts(self, complex_id: int) -> LocationFacts | None: ...

    #: 동(棟)별 좌표 사실. 실거래에 동 정보가 없어 **추정 입력**으로만 쓰인다(F4 §D).
    def building_location_facts(self, complex_id: int) -> list[BuildingLocationFact]: ...
