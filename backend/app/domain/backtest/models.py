"""백테스트 데이터 형태. 순수 데이터클래스 + 달력 계산.

설계 정본: `docs/02-design/backtest.md` §1 · §3-A
"""
from __future__ import annotations

import bisect
import calendar
import datetime as dt
from dataclasses import dataclass
from typing import NamedTuple

from app.domain.valuation.models import MIN_SAMPLE

# ---------------------------------------------------------------------------
# 면적대 — `hexagon-report-data.md §2-A` 와 **같은 경계**. 새 숫자를 만들지 않는다.
# ---------------------------------------------------------------------------
#: 경계값(㎡, 전용). 주택법·세법·청약 제도가 쓰는 60 / 85 / 102 / 135 그대로다.
AREA_BAND_EDGES: tuple[float, ...] = (60.0, 85.0, 102.0, 135.0)

#: 라벨. `hexagon` 문서의 표기와 글자까지 같게 둔다(같은 데이터에 두 이름을 만들지 않는다).
AREA_BAND_LABELS: tuple[str, ...] = ("<60", "60~85", "85~102", "102~135", ">135")

#: 시군구 코드 길이. `complex.region_code` 는 법정동 10자리이고 앞 5자리가 시군구다
#: (`postgis.py` 의 `left(region_code, length(rc))` 관례와 같다).
SIGUNGU_CODE_LEN = 5

#: 한 시점 가격을 산출할 최소 거래 수. **`valuation.MIN_SAMPLE` 과 같은 값**이다 —
#: 이 저장소가 "숫자를 화면에 올려도 된다"고 정한 하한을 백테스트에서 낮추지 않는다.
MIN_TRADES_PER_ENDPOINT = MIN_SAMPLE

#: 가격 창(개월). 12를 기본으로 두는 이유와 그 대가(6개월 평활·지연)는 backtest.md §2-C.
DEFAULT_WINDOW_MONTHS = 12

#: 채점 지평(개월). 성공기준 ④의 "사후"를 12개월로 읽는다.
DEFAULT_HORIZON_MONTHS = 12


def area_band(area_m2: float | None) -> str | None:
    """전용면적 → 면적대 라벨. 값이 없거나 0 이하면 None(지어내지 않는다).

    경계는 **상한 포함**이다(`bisect_left`). 법이 "60㎡ 이하"·"85㎡ 이하"로 쓰기 때문이다.
    라벨은 `<60`·`60~85` 로 적지만 실제 판정은 `<=60`·`(60,85]` 다 —
    전용면적이 정확히 경계값인 표본은 실무상 거의 없어(59.98·84.97 꼴) 차이가 없다.
    """
    if area_m2 is None:
        return None
    value = float(area_m2)
    if value <= 0:
        return None
    return AREA_BAND_LABELS[bisect.bisect_left(AREA_BAND_EDGES, value)]


def sigungu_of(region_code: str | None) -> str | None:
    """법정동 코드 → 시군구 5자리. 짧거나 없으면 None."""
    if not region_code:
        return None
    code = region_code.strip()
    return code[:SIGUNGU_CODE_LEN] if len(code) >= SIGUNGU_CODE_LEN else None


def add_months(date: dt.date, months: int) -> dt.date:
    """달력 기준 월 가감. 말일은 그 달의 말일로 잘린다(1/31 − 1개월 = 12/31).

    왜 `timedelta(days=30*n)` 을 쓰지 않는가 — 30일 곱셈은 12개월이 360일이 되어
    "12개월 수익률"이 실제로는 11.8개월이 된다. 지평이 12개월인데 5일씩 밀리면
    폴드를 여러 개 겹칠 때 창이 어긋난다.
    """
    total = (date.year * 12 + date.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(date.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


class CellRef(NamedTuple):
    """채점 단위 = **(단지, 면적대)**.

    단지 단위로 재면 믹스 효과가 수익률로 둔갑한다(면적대별 중위 ₩/㎡ 가 23.1% 차이 —
    `hexagon §2-A`). 근거는 backtest.md §1.
    """

    complex_id: int
    band: str


@dataclass(frozen=True)
class BacktestTrade:
    """백테스트가 보는 실거래 한 건. `trade` 행을 그대로 옮긴 형태.

    ⚠️ **리포지토리는 여기에 as-of 필터를 걸지 않는다.** 자르는 곳은 `asof.py` 한 곳이다
    (backtest.md §5-2). 두 곳에서 자르면 한쪽만 고쳐지는 날이 온다.
    """

    complex_id: int
    contract_date: dt.date
    price_krw: int
    area_m2: float
    #: 법정동 10자리. 시군구 벤치마크(B2)에 쓴다. 없으면 그 셀은 B2 에서 빠진다.
    region_code: str | None = None
    is_cancelled: bool = False
    #: 해제일. ⚠️ **현재 `trade` 테이블에 이 컬럼이 없다** — 수집기는 파싱하는데
    #: (`ingest/molit.py::cancelled_on`) 적재 SQL 의 컬럼 목록에서 빠져 값이 버려진다.
    #: 그래서 실데이터에서는 항상 None 이고, `CancellationPolicy.EXCLUDE_KNOWN_AT` 을
    #: 쓸 수 없다. 마이그레이션 017 로 컬럼을 만들면 이 자리는 그대로 살아난다(§2-D).
    cancelled_on: dt.date | None = None
    #: 등기일. **가시성 필터로 쓰지 않는다**(선택편향 — backtest.md §2-A).
    #: 쓰는 곳은 딱 하나, `apt_dong` 을 T 시점에 알았는지 판정하는 데다(§2-B).
    registered_at: dt.date | None = None
    apt_dong: str | None = None
    floor: int | None = None

    @property
    def band(self) -> str | None:
        return area_band(self.area_m2)

    @property
    def sigungu(self) -> str | None:
        return sigungu_of(self.region_code)

    @property
    def ppm_krw(self) -> float:
        """₩/㎡. 면적이 0 이하인 행은 리포지토리가 보내지 않는다(DB CHECK)."""
        return self.price_krw / self.area_m2

    @property
    def cell(self) -> CellRef | None:
        band = self.band
        return CellRef(self.complex_id, band) if band else None

    def sort_key(self) -> tuple:
        """결정적 정렬용. as-of 뷰가 **집합의 함수**가 되게 한다(입력 순서 무관)."""
        return (self.contract_date, self.complex_id, self.price_krw,
                self.area_m2, self.floor if self.floor is not None else -1,
                self.apt_dong or "")


#: `PricePoint.reason` 문구 (테스트·리포트가 같은 문자열을 본다).
REASON_NO_TRADE = "창 안에 거래가 없습니다"
REASON_TOO_FEW = "창 안 거래가 최소 표본에 미달합니다"


@dataclass(frozen=True)
class PricePoint:
    """한 셀의 **한 시점** 가격(₩/㎡ 중위). 표본이 모자라면 숫자를 만들지 않는다."""

    available: bool
    median_ppm_krw: int | None = None
    sample_size: int = 0
    window_months: int | None = None
    #: 이 창이 끝나는 날 = `as_of − 신고지연`. "언제까지의 거래로 만든 값인가"를 남긴다.
    window_end: dt.date | None = None
    reason: str | None = None


@dataclass(frozen=True)
class AsOfCell:
    """T 시점에 알 수 있었던 것만으로 만든 후보 하나.

    ⚠️ **점수 함수는 이 객체만 본다.** 원본 거래를 넘기지 않는 이유는 성능이 아니라
    누출 차단이다 — 누출을 하고 싶어도 손이 닿지 않게 타입으로 막는다(§5-4).
    """

    ref: CellRef
    as_of: dt.date
    sigungu: str | None
    #: T 시점 가격(후행 `window_months` 창).
    price: PricePoint
    #: 그 직전 창의 가격. 두 창은 인접하고 겹치지 않는다 → 가격추세 축의 입력.
    prior_price: PricePoint
    #: T 시점 창 안의 거래 수(환금성 축의 분자).
    window_trade_count: int = 0
    #: 세대수. **상수 가정이 정당한 유일한 축**(준공 시 확정 — §2-E).
    total_households: int | None = None
    #: 같은 (시군구, 면적대) 셀들의 T 시점 ₩/㎡ 중위. 가격매력 축의 분모.
    #: 피어가 모자라면 None(지어내지 않는다).
    peer_median_ppm_krw: int | None = None

    @property
    def complex_id(self) -> int:
        return self.ref.complex_id

    @property
    def band(self) -> str:
        return self.ref.band

    @property
    def peer_key(self) -> tuple[str, str] | None:
        return (self.sigungu, self.band) if self.sigungu else None


@dataclass(frozen=True)
class CellOutcome:
    """한 셀의 T → T+H 실현 결과. `measured=False` 면 **수익률이 없다**(지어내지 않는다)."""

    ref: CellRef
    sigungu: str | None
    measured: bool
    ret_pct: float | None
    start: PricePoint
    end: PricePoint
    reason: str | None = None

    @property
    def peer_key(self) -> tuple[str, str] | None:
        return (self.sigungu, self.ref.band) if self.sigungu else None


@dataclass(frozen=True)
class FoldSpec:
    """폴드 하나 = (기준시점 T, 지평 H, 창 W).

    필요한 데이터 범위는 `T` 하나에 약 `W + H + W` 개월이다(§4-A). 그래서 지금 데이터
    (2024-01~)로는 겹치지 않는 폴드가 **사실상 1개**이고, 그 구간은 전부 상승기다.
    상승기만으로 채점한 결과는 무의미하다 — `engine.summarize` 가 `rising_only` 로 막는다.
    """

    as_of: dt.date
    horizon_months: int = DEFAULT_HORIZON_MONTHS
    window_months: int = DEFAULT_WINDOW_MONTHS
    label: str | None = None

    def __post_init__(self) -> None:
        if self.horizon_months <= 0:
            raise ValueError(f"지평은 양수여야 합니다: {self.horizon_months}")
        if self.window_months <= 0:
            raise ValueError(f"가격 창은 양수여야 합니다: {self.window_months}")

    @property
    def name(self) -> str:
        return self.label or self.as_of.isoformat()

    @property
    def outcome_as_of(self) -> dt.date:
        """결과를 재는 시점 T+H. **T 와 같은 함수로** 가격을 만든다(§3-A)."""
        return add_months(self.as_of, self.horizon_months)

    @property
    def prior_as_of(self) -> dt.date:
        """가격추세용 직전 시점 T−W. 두 창은 인접하고 겹치지 않는다."""
        return add_months(self.as_of, -self.window_months)

    def required_contract_range(self, *, report_lag_days: int,
                                include_prior: bool = True) -> tuple[dt.date, dt.date]:
        """이 폴드를 돌리는 데 필요한 **계약일 범위**. 스크립트가 데이터 유무를 먼저 본다.

        ⚠️ 요구 범위가 **두 가지**다. 이걸 구분하지 않으면 백필 계획을 잘못 세운다:

          · `include_prior=False` — 가격매력·환금성만. 폭 = `W + H` (기본 24개월 + 30일)
          · `include_prior=True`  — **가격추세까지**. 직전 창이 하나 더 필요해
            폭 = `2W + H` (기본 36개월 + 30일)

        실제로 이 차이가 물린다: 2021-01 백필로 T=2022-01 하락기 폴드를 돌리면
        직전 창(2020-01~2021-01)이 없어 **가격추세 축이 통째로 빠진다**(backtest.md §4-D).
        """
        end = self.outcome_as_of - dt.timedelta(days=report_lag_days)
        anchor = self.prior_as_of if include_prior else self.as_of
        start_cutoff = anchor - dt.timedelta(days=report_lag_days)
        return add_months(start_cutoff, -self.window_months), end
