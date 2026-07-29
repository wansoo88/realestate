"""시세 분석 입출력 모델. 순수 데이터클래스."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

#: 층대 구분. 실거래로 말할 수 있는 축 중 하나.
FLOOR_BANDS: tuple[tuple[str, int, int], ...] = (
    ("1-5", 1, 5),
    ("6-15", 6, 15),
    ("16+", 16, 10_000),
)

#: 표본이 이보다 적으면 밴드를 산출하지 않는다. 적은 표본의 통계는 근거가 아니라 착시다.
MIN_SAMPLE = 5

#: `ListingRow.source` 값 — 사용자가 **손으로 옮겨 적은** 호가(migrations/016).
#:
#: 왜 도메인 최하위 계층에 두는가
#: ------------------------------
#: 이 문자열이 분석 계층의 **분기 기준**이기 때문이다. 리포지토리 상수를 도메인이
#: 가져다 쓰면 의존 방향이 뒤집히고(도메인 → 리포지토리), 그렇다고 양쪽에 같은
#: 리터럴을 두면 한쪽만 바뀌는 날 **모든 사용자 입력이 조용히 수집 데이터로 분류된다.**
#: 그 순간 신뢰도 점수가 다시 붙는다(차단 ①). 그래서 정본은 여기 하나다 —
#: `app/repositories/base.LISTING_SOURCE_USER` 는 이 값을 import 해서 쓴다.
LISTING_SOURCE_USER = "user_entered"

#: 동(棟)별 실측에 필요한 최소 표본. 층대(3)와 같은 관대함이되, 동은 **상대 비율**이라
#: 이보다 적으면 한두 건의 우연이 편차로 둔갑한다. 미달 동은 실측하지 않고 폴백으로 넘긴다.
MIN_SAMPLE_DONG = 3

#: 동별 실측 전용 기간(개월). **적정가 밴드의 기간과 분리한다.**
#:
#: 왜 분리하는가 — 실데이터로 확인된 사실(2026-07-25, 12만 건 적재 후 실측):
#:   `aptDong` 은 **등기가 완료된 뒤에야 채워진다**. 등기일 있는 거래는 86.3% 가 동을
#:   가지고 있지만, 등기 전 거래는 2.0% 뿐이다. 그래서 최근 6개월만 보면 동 정보가
#:   33~58% 로 떨어져 실측이 대부분 실패한다(송파 상위 8단지: 6개월 4/8 → 24개월 8/8,
#:   coverage 79~93%). 거래가 많은 단지일수록 밴드가 6개월에서 멈춰 **가장 불리한 창**을 쓴다.
#:
#: 기간을 늘려도 왜곡되지 않는 이유: 동별 배율은 **같은 창의 단지 전체 중위 대비 상대값**이라
#: 기간이 길어져 생기는 시세 드리프트가 분자·분모에서 상쇄된다. 게다가 동별 서열(로열동 여부)은
#: 가격 수준과 달리 시간에 대해 안정적이다.
DONG_PERIOD_MONTHS = 24

#: 표본 부족 시 이 순서로 기간을 넓힌다(개월).
PERIOD_LADDER: tuple[int, ...] = (6, 12, 24, 36)


def floor_band(floor: int | None) -> str | None:
    if floor is None:
        return None
    for name, lo, hi in FLOOR_BANDS:
        if lo <= floor <= hi:
            return name
    return None


@dataclass(frozen=True)
class TradeRow:
    """실거래 한 건. DB 행을 그대로 옮긴 형태."""

    contract_date: dt.date
    price_krw: int
    area_m2: float
    floor: int | None = None
    is_cancelled: bool = False
    #: 동(棟). 운영 MOLIT API 가 77~93% 제공(erd §0 정정). F4 동별 실측에 쓴다.
    #: 없으면(None) 그 거래는 동 통계 표본에서 빠지고 좌표추정 폴백 대상이 된다.
    apt_dong: str | None = None


@dataclass(frozen=True)
class ListingRow:
    """호가 매물 한 건.

    ⚠️ **출처가 이 행의 성질을 결정한다** (migrations/016)
    ------------------------------------------------------
    호가는 두 갈래로 들어온다. 둘은 같은 숫자처럼 보이지만 **뒤에 붙은 신호가 다르다**:

      · 수집(`source` 가 `LISTING_SOURCE_USER` 가 아님) — 여러 중개사가 각각 올린 값이라
        "중복 등록 수"·"등록 후 경과일"·"최근 수집으로 살아있음 확인" 같은 **제3자 신호**가 있다.
        `dedup.trust_score` 는 그 신호들을 세는 함수다.
      · 사용자 수동 입력(`LISTING_SOURCE_USER`) — 사람이 하나 적은 값이다. 위 신호가
        **셋 중 셋 다 성립하지 않는다**(중개사 중복 없음 · 포털 등록일 모름 ·
        "확인됨"의 근거가 사용자 자신). 그래서 신뢰도를 매기면 안 된다.

    이 필드가 없던 동안 분석 계층은 두 갈래를 구분할 수 없었고, 사용자가 적은 한 건이
    `trust_score` 만점(=리스크 축 100점)을 받았다 — **비싼 매물을 입력할수록 총점이
    올라가는** 형태다. `source` 는 그 구분을 도메인까지 **끊기지 않게** 나르는 칸이다.

    ⚠️ 소유자(`created_by_user_id`)는 일부러 담지 않는다. 분기에 필요한 정보는
       "누가 적었나"가 아니라 "사람이 적었나"이고, 이 객체는 근거 문자열·LLM 프롬프트
       경로로 흘러간다 — 개인 식별자를 그 경로에 얹지 않는다(security.md §2.2).
       DB CHECK(`listing_user_source_pair`)가 `source='user_entered'` ⟺ 소유자 있음을
       강제하므로 두 값은 **같은 사실**이며, 그중 덜 위험한 쪽을 든다.
    """

    id: int
    ask_price_krw: int
    area_m2: float
    floor: int | None = None
    listed_at: dt.date | None = None
    collected_at: dt.date | None = None
    building_id: int | None = None
    agency: str | None = None
    status: str = "active"
    #: 출처. `None` = 미상(구형 호출부·수집 스텁) → **수집으로 취급한다.**
    #: 사용자 입력만 명시적으로 표시되며, 그 표시는 리포지토리가 붙인다.
    source: str | None = None
    #: 사용자가 이 호가를 **직접 확인한 날**. 수집분에는 없다(None).
    #: `collected_at` 과 값이 같을 수 있지만 뜻이 다르다 — 이쪽은 사람의 확인이다.
    as_of: dt.date | None = None

    @property
    def is_user_entered(self) -> bool:
        """사람이 손으로 적은 호가인가. **신뢰도 신호 유무의 유일한 판정식이다.**"""
        return self.source == LISTING_SOURCE_USER


@dataclass(frozen=True)
class PriceBand:
    """적정가 밴드. 표본이 부족하면 `available=False` 로 돌려주고 숫자를 만들지 않는다."""

    available: bool
    median_krw: int | None = None
    p25_krw: int | None = None
    p75_krw: int | None = None
    sample_size: int = 0
    period_months: int | None = None
    expanded: bool = False
    floor_effect: dict[str, float] = field(default_factory=dict)
    reason: str | None = None          # available=False 일 때 왜인지
    #: 시점 보정 결과(`app.domain.valuation.timeadjust.TimeAdjustment`).
    #:
    #: ⚠️ **None 은 "보정했다"가 아니라 "보정을 시도조차 안 했다"** 이다(지수 미전달).
    #: 보정을 시도했으면 성공이든 실패든 객체가 들어 있고 사유가 남는다. 호출부는
    #: `time_adjustment.applied` 로만 판단해야 한다 — 값의 유무로 판단하면
    #: 미보정 밴드를 보정된 것으로 오해한다.
    #: 타입을 `Any` 로 둔 이유: models 는 최하위 계층이라 timeadjust 를 import 하면
    #: 순환이 된다(timeadjust 가 TradeRow·MIN_SAMPLE 을 여기서 가져간다).
    time_adjustment: Any | None = None

    @property
    def is_time_adjusted(self) -> bool:
        """이 밴드가 실제로 시점 보정된 값인가. **표시 문구가 이 값으로 갈린다.**"""
        return bool(self.time_adjustment is not None and self.time_adjustment.applied)

    @property
    def as_of_label(self) -> str | None:
        """이 밴드가 말하는 **시점**. 보정했으면 기준월, 아니면 None(= 시점 불명 혼합)."""
        return self.time_adjustment.reference_ym if self.is_time_adjusted else None

    def to_evidence(self, source: str = "국토교통부 실거래가",
                    as_of: dt.date | None = None) -> list[dict[str, Any]]:
        if not self.available:
            return []
        adj = self.time_adjustment
        claim = f"중위 실거래가 {self.median_krw:,}원"
        source_label = source
        if self.is_time_adjusted:
            # 보정된 숫자를 원본 실거래 중위처럼 내보내면 안 된다 — 다른 값이다.
            claim = f"{adj.reference_ym} 시점 환산 중위 {self.median_krw:,}원"
            # ⚠️ **출처 문자열도 바꾼다**(CR34-5). 이 숫자는 국토부가 발표한 값이
            #    아니라 그 값에 **우리 지수를 곱한 결과**다. 꼬리표가 앞에 붙는다는
            #    이유로 출처를 원본 그대로 두면, 근거 목록만 따로 인용되는 자리
            #    (LLM 프롬프트·리포트 발췌)에서 우리 계산이 국토부 발표로 둔갑한다.
            source_label = f"{source} + 자체 시장지수 환산"
        return [{
            "claim": claim,
            "source": source_label,
            "as_of": (as_of or dt.date.today()).isoformat(),
            "data_rows": self.sample_size,
            "period_months": self.period_months,
            "expanded": self.expanded,
            "basis": adj.basis if adj is not None else "trade_raw",
            "time_adjusted": self.is_time_adjusted,
        }]


@dataclass(frozen=True)
class DongStat:
    """한 동(棟)의 단지 내 상대가격. ₩/㎡ 중위로 면적 구성 차이를 보정한다."""

    dong: str
    ratio: float                # 단지 평균(₩/㎡) 대비 배율. 1.08 = 단지 평균보다 8% 비쌈
    sample_size: int
    median_ppm_krw: int         # 이 동의 ₩/㎡ 중위

    @property
    def vs_complex_pct(self) -> float:
        """단지 평균 대비 %(+/-). UI·근거 문구용."""
        return round((self.ratio - 1) * 100, 1)


@dataclass(frozen=True)
class DongValuation:
    """동별 가치 차이(F4) 실측 결과.

    `available=True` 면 실거래 aptDong 기반 **실측**이다(높은 신뢰). False 면 표본이
    부족하거나 동 정보가 없어 실측 불가 — 호출부는 좌표추정 폴백으로 가야 한다.
    숫자를 지어내지 않는다: 미달 동은 dongs 에서 아예 빠진다.
    """

    available: bool
    method: str                 # 실측(aptDong) | 동표본부족 | 동정보없음 | 표본부족
    overall_median_ppm_krw: int | None = None
    dongs: tuple[DongStat, ...] = ()
    coverage_pct: float | None = None   # 동 정보가 있는 거래 비율(%) — 신뢰의 근거
    period_months: int | None = None
    reason: str | None = None

    def to_evidence(self, as_of: dt.date | None = None,
                    source: str = "국토교통부 실거래가") -> list[dict[str, Any]]:
        if not self.available:
            return []
        top = self.dongs[0]
        return [{
            "claim": (f"{top.dong}동 {top.vs_complex_pct:+.1f}%(단지 평균 대비, ₩/㎡ 실측)"),
            "source": source,
            "as_of": (as_of or dt.date.today()).isoformat(),
            "data_rows": top.sample_size,
            "coverage_pct": self.coverage_pct,
            "basis": "trade_measured",   # 좌표추정(listing_reported)과 구분
        }]


@dataclass(frozen=True)
class Liquidity:
    """환금성. 못 파는 자산은 오른 것도 의미가 없다."""

    turnover_12m_pct: float | None
    median_days_on_market: int | None
    active_listing_ratio_pct: float | None
    grade: str                          # 좋음 | 보통 | 나쁨 | 판단보류
