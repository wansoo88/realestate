"""적정가 밴드·층 보정·호가 갭·환금성 계산.

설계 근거: docs/02-design/agents/03-valuation-trader.md

이 모듈이 지키는 규칙
---------------------
1. **해제(취소) 거래는 제외한다.** 포함하면 허위 신고가가 시세를 왜곡한다.
2. **표본이 5건 미만이면 밴드를 만들지 않는다.** 기간을 넓혀보고, 그래도 부족하면
   `available=False` 로 정직하게 돌려준다. 숫자를 지어내지 않는다.
3. **기간을 넓혔으면 그 사실을 표시한다.** 6개월 통계와 36개월 통계는 의미가 다르다.
4. **동(棟)별 가격 차이는 여기서 계산하지 않는다.** 실거래에 동 정보가 없다
   (docs/02-design/erd.md §0). 층·타입까지가 실거래로 말할 수 있는 한계다.
"""
from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Iterable, Sequence

from app.domain.valuation.models import (
    FLOOR_BANDS,
    MIN_SAMPLE,
    PERIOD_LADDER,
    Liquidity,
    ListingRow,
    PriceBand,
    TradeRow,
    floor_band,
)

#: 전용면적 매칭 허용 오차(㎡). 같은 타입도 소수점 표기가 흔들린다.
AREA_TOLERANCE_M2 = 0.5


def _quantile(sorted_values: Sequence[int], q: float) -> int:
    """선형보간 분위수. statistics.quantiles 는 표본이 적으면 예외를 내서 직접 계산한다."""
    if not sorted_values:
        raise ValueError("빈 표본")
    if len(sorted_values) == 1:
        return int(sorted_values[0])
    pos = (len(sorted_values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return int(round(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac))


def eligible_trades(
    trades: Iterable[TradeRow],
    *,
    area_m2: float | None = None,
    months: int | None = None,
    as_of: dt.date | None = None,
    tolerance_m2: float = AREA_TOLERANCE_M2,
) -> list[TradeRow]:
    """통계에 쓸 수 있는 거래만 남긴다."""
    as_of = as_of or dt.date.today()
    cutoff = None
    if months is not None:
        # 월 단위를 일수로 환산 (달력 정확도보다 단순·예측 가능성을 택함)
        cutoff = as_of - dt.timedelta(days=int(months * 30.44))

    out: list[TradeRow] = []
    for t in trades:
        if t.is_cancelled:
            continue                      # 규칙 1
        if t.price_krw <= 0:
            continue
        if cutoff is not None and t.contract_date < cutoff:
            continue
        if t.contract_date > as_of:
            continue                      # 미래 거래는 데이터 오류
        if area_m2 is not None and abs(t.area_m2 - area_m2) > tolerance_m2:
            continue
        out.append(t)
    return out


def floor_effect(trades: Sequence[TradeRow]) -> dict[str, float]:
    """층대별 중위가 / 전체 중위가 비율.

    표본이 부족한 층대는 **비율을 만들지 않는다**(키 자체를 넣지 않음).
    """
    if not trades:
        return {}
    overall = statistics.median(t.price_krw for t in trades)
    if overall <= 0:
        return {}

    out: dict[str, float] = {}
    for name, _lo, _hi in FLOOR_BANDS:
        prices = [t.price_krw for t in trades if floor_band(t.floor) == name]
        if len(prices) < 3:               # 층대별은 더 관대하게 3건
            continue
        out[name] = round(statistics.median(prices) / overall, 4)
    return out


def fair_price_band(
    trades: Iterable[TradeRow],
    *,
    area_m2: float | None = None,
    as_of: dt.date | None = None,
    target_floor: int | None = None,
    ladder: Sequence[int] = PERIOD_LADDER,
) -> PriceBand:
    """적정가 밴드. 표본이 부족하면 기간을 넓히고, 그래도 부족하면 포기한다."""
    all_trades = list(trades)
    as_of = as_of or dt.date.today()

    chosen: list[TradeRow] = []
    chosen_months: int | None = None
    for idx, months in enumerate(ladder):
        subset = eligible_trades(all_trades, area_m2=area_m2, months=months, as_of=as_of)
        if len(subset) >= MIN_SAMPLE:
            chosen, chosen_months = subset, months
            expanded = idx > 0
            break
    else:
        # 사다리를 다 올라가도 부족 — 지어내지 않는다
        available = eligible_trades(all_trades, area_m2=area_m2,
                                    months=ladder[-1], as_of=as_of)
        return PriceBand(
            available=False,
            sample_size=len(available),
            period_months=ladder[-1],
            reason=(f"표본 {len(available)}건으로 최소 {MIN_SAMPLE}건에 미달합니다. "
                    f"최근 {ladder[-1]}개월까지 확장했으나 부족합니다."),
        )

    prices = sorted(t.price_krw for t in chosen)
    median = int(statistics.median(prices))
    p25 = _quantile(prices, 0.25)
    p75 = _quantile(prices, 0.75)
    effects = floor_effect(chosen)

    # 대상 층이 지정되면 층 보정을 곱한다. 해당 층대 표본이 없으면 보정하지 않는다.
    band_name = floor_band(target_floor)
    ratio = effects.get(band_name) if band_name else None
    if ratio:
        median = int(median * ratio)
        p25 = int(p25 * ratio)
        p75 = int(p75 * ratio)

    return PriceBand(
        available=True,
        median_krw=median,
        p25_krw=p25,
        p75_krw=p75,
        sample_size=len(chosen),
        period_months=chosen_months,
        expanded=expanded,
        floor_effect=effects,
    )


def ask_gap_pct(ask_price_krw: int, band: PriceBand) -> float | None:
    """호가가 적정가 중위 대비 몇 % 인지. 밴드가 없으면 None(추정 금지)."""
    if not band.available or not band.median_krw:
        return None
    return round((ask_price_krw - band.median_krw) / band.median_krw * 100, 2)


def liquidity(
    trades: Iterable[TradeRow],
    listings: Iterable[ListingRow],
    total_households: int | None,
    *,
    as_of: dt.date | None = None,
) -> Liquidity:
    """환금성 지표. 세대수를 모르면 회전율을 만들지 않는다."""
    as_of = as_of or dt.date.today()
    recent = eligible_trades(trades, months=12, as_of=as_of)
    active = [l for l in listings if l.status == "active"]

    turnover = None
    active_ratio = None
    if total_households and total_households > 0:
        turnover = round(len(recent) / total_households * 100, 2)
        active_ratio = round(len(active) / total_households * 100, 2)

    days = [
        (as_of - l.listed_at).days
        for l in active
        if l.listed_at is not None and (as_of - l.listed_at).days >= 0
    ]
    median_days = int(statistics.median(days)) if days else None

    if turnover is None:
        grade = "판단보류"
    elif turnover >= 5.0:
        grade = "좋음"
    elif turnover >= 2.0:
        grade = "보통"
    else:
        grade = "나쁨"

    return Liquidity(
        turnover_12m_pct=turnover,
        median_days_on_market=median_days,
        active_listing_ratio_pct=active_ratio,
        grade=grade,
    )
