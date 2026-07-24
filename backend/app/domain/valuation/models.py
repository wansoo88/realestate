"""시세 분석 입출력 모델. 순수 데이터클래스."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

#: 층대 구분. 실거래에 동 정보가 없으므로 층은 우리가 쓸 수 있는 몇 안 되는 축이다.
FLOOR_BANDS: tuple[tuple[str, int, int], ...] = (
    ("1-5", 1, 5),
    ("6-15", 6, 15),
    ("16+", 16, 10_000),
)

#: 표본이 이보다 적으면 밴드를 산출하지 않는다. 적은 표본의 통계는 근거가 아니라 착시다.
MIN_SAMPLE = 5

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


@dataclass(frozen=True)
class ListingRow:
    """호가 매물 한 건."""

    id: int
    ask_price_krw: int
    area_m2: float
    floor: int | None = None
    listed_at: dt.date | None = None
    collected_at: dt.date | None = None
    building_id: int | None = None
    agency: str | None = None
    status: str = "active"


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

    def to_evidence(self, source: str = "국토교통부 실거래가",
                    as_of: dt.date | None = None) -> list[dict[str, Any]]:
        if not self.available:
            return []
        return [{
            "claim": f"중위 실거래가 {self.median_krw:,}원",
            "source": source,
            "as_of": (as_of or dt.date.today()).isoformat(),
            "data_rows": self.sample_size,
            "period_months": self.period_months,
            "expanded": self.expanded,
        }]


@dataclass(frozen=True)
class Liquidity:
    """환금성. 못 파는 자산은 오른 것도 의미가 없다."""

    turnover_12m_pct: float | None
    median_days_on_market: int | None
    active_listing_ratio_pct: float | None
    grade: str                          # 좋음 | 보통 | 나쁨 | 판단보류
