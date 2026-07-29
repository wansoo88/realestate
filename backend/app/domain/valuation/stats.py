"""적정가 밴드·층 보정·호가 갭·환금성 계산.

설계 근거: docs/02-design/agents/03-valuation-trader.md

이 모듈이 지키는 규칙
---------------------
1. **해제(취소) 거래는 제외한다.** 포함하면 허위 신고가가 시세를 왜곡한다.
2. **표본이 5건 미만이면 밴드를 만들지 않는다.** 기간을 넓혀보고, 그래도 부족하면
   `available=False` 로 정직하게 돌려준다. 숫자를 지어내지 않는다.
3. **기간을 넓혔으면 그 사실을 표시한다.** 6개월 통계와 36개월 통계는 의미가 다르다.
4. **동(棟)별 가격 차이는 실측한다(dong_effect).** 운영 MOLIT API 가 aptDong 을 77~93%
   제공함이 확인돼(erd §0 정정, 2026-07-25) 좌표추정이 아니라 실거래로 직접 측정한다.
   단, 동 표본이 MIN_SAMPLE_DONG 미만이거나 동 정보가 없으면 실측하지 않고 폴백을 알린다.
5. **시점을 섞지 않는다(선택).** `fair_price_band(index=...)` 를 주면 창 안 거래를 각각
   기준월 수준으로 환산한 뒤 분위수를 낸다. 안 주면 예전과 같은 값이다. 왜 필요한지와
   보정을 거부하는 조건은 `app/domain/valuation/timeadjust.py` 참조.
"""
from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Iterable, Sequence

from app.domain.valuation.models import (
    DONG_PERIOD_MONTHS,
    FLOOR_BANDS,
    MIN_SAMPLE,
    MIN_SAMPLE_DONG,
    PERIOD_LADDER,
    DongStat,
    DongValuation,
    Liquidity,
    ListingRow,
    PriceBand,
    TradeRow,
    floor_band,
)
from app.domain.valuation.timeadjust import MarketIndex, adjust_trades

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


def dong_effect(
    trades: Iterable[TradeRow],
    *,
    area_m2: float | None = None,
    months: int | None = DONG_PERIOD_MONTHS,
    as_of: dt.date | None = None,
    min_sample_dong: int = MIN_SAMPLE_DONG,
) -> DongValuation:
    """동(棟)별 가격 편차를 ₩/㎡ 중위로 실측한다(F4).

    ⚠️ 기간은 **적정가 밴드와 분리**한다(기본 DONG_PERIOD_MONTHS=24). aptDong 은 등기 후에만
    채워져서 최근 6개월 창에서는 동 정보가 33~58% 로 떨어진다 — 밴드 기간을 그대로 쓰면
    거래가 많은 단지일수록 실측이 실패한다(models.DONG_PERIOD_MONTHS 주석의 실측 근거 참조).

    면적 구성 차이를 보정하려고 절대가가 아니라 ₩/㎡ 를 쓴다: 큰 평형이 많은 동이
    입지와 무관하게 비싸 보이는 착시를 없앤다. 기준(분모)은 **단지 전체** 거래의
    ₩/㎡ 중위이므로 각 동의 배율은 "이 동 vs 단지 평균" 을 뜻한다.

    동 표본이 min_sample_dong 미만인 동은 결과에서 빼고, 실측 가능한 동이 하나도
    없으면 available=False 로 폴백(좌표추정)을 알린다 — 숫자를 지어내지 않는다.
    """
    elig = [t for t in eligible_trades(trades, area_m2=area_m2, months=months,
                                       as_of=as_of) if t.area_m2 > 0]
    if len(elig) < MIN_SAMPLE:
        return DongValuation(
            available=False, method="표본부족", period_months=months,
            reason=f"실거래 표본 {len(elig)}건으로 최소 {MIN_SAMPLE}건에 미달합니다.",
        )

    overall_ppm = statistics.median(t.price_krw / t.area_m2 for t in elig)
    with_dong = [t for t in elig if t.apt_dong]
    coverage = round(len(with_dong) / len(elig) * 100, 1)

    by_dong: dict[str, list[float]] = {}
    for t in with_dong:
        by_dong.setdefault(t.apt_dong, []).append(t.price_krw / t.area_m2)

    stats_out: list[DongStat] = []
    for dong, ppms in by_dong.items():
        if len(ppms) < min_sample_dong:
            continue
        m = statistics.median(ppms)
        stats_out.append(DongStat(
            dong=dong,
            ratio=round(m / overall_ppm, 4),
            sample_size=len(ppms),
            median_ppm_krw=int(round(m)),
        ))

    if not stats_out:
        method = "동정보없음" if coverage == 0.0 else "동표본부족"
        reason = ("실거래에 동 정보가 없습니다(좌표추정으로 폴백)."
                  if coverage == 0.0 else
                  f"동별 표본이 모두 최소 {min_sample_dong}건 미만입니다(동 정보 {coverage}%).")
        return DongValuation(
            available=False, method=method,
            overall_median_ppm_krw=int(round(overall_ppm)),
            coverage_pct=coverage, period_months=months, reason=reason,
        )

    # 비싼 동 → 싼 동 순(대표 동을 근거로 뽑기 쉽게).
    stats_out.sort(key=lambda s: s.ratio, reverse=True)
    return DongValuation(
        available=True, method="실측(aptDong)",
        overall_median_ppm_krw=int(round(overall_ppm)),
        dongs=tuple(stats_out), coverage_pct=coverage, period_months=months,
    )


def fair_price_band(
    trades: Iterable[TradeRow],
    *,
    area_m2: float | None = None,
    as_of: dt.date | None = None,
    target_floor: int | None = None,
    ladder: Sequence[int] = PERIOD_LADDER,
    index: MarketIndex | None = None,
) -> PriceBand:
    """적정가 밴드. 표본이 부족하면 기간을 넓히고, 그래도 부족하면 포기한다.

    `index` 를 주면 창 안의 거래를 **각각** 기준월 수준으로 환산한 뒤 분위수를 낸다
    (규칙 5). 주지 않으면 예전과 **완전히 같은 값**을 낸다 — 보정은 선택이고, 켜지
    않았는데 조용히 값이 달라지는 일은 없다.
    """
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

    # 시점 보정 — 창을 고른 **뒤에** 한다. 창 선택은 건수로만 정해지므로 보정과 무관하고,
    # 순서를 바꾸면 보정 실패 시 창까지 달라져 재현이 안 된다.
    chosen, adjustment = adjust_trades(chosen, index)

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
        # 보정을 **시도한 경우에만** 결과를 싣는다. index 를 안 준 호출에는 None 이 남아
        # "보정 안 함"과 "보정 시도 안 함"이 구분된다(models.PriceBand 주석).
        time_adjustment=adjustment if index is not None else None,
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
    """환금성 지표. 세대수를 모르면 회전율을 만들지 않는다.

    ⚠️ **등급(`grade`)과 가치 축 점수는 오직 `turnover`(실거래) 로만 정해진다.**
       `active_listing_ratio_pct` 는 참고 값이고 지금 어디에도 표시되지 않는다.
       이 값을 화면·점수에 연결하려는 사람에게: `listings` 에는 사용자가 손으로
       입력한 호가(migrations/016)가 섞여 들어온다. 그걸 "시장에 나와 있는 물량"으로
       읽으면, 사용자가 자기 관심 단지를 입력할수록 그 단지의 매물이 많아 보인다
       — 출처를 갈라 세거나(`ListingRow.is_user_entered`) 쓰지 말 것.
       `median_days_on_market` 은 `listed_at`(포털 등록일) 기준이라 사용자 입력에는
       구조적으로 없다(None) — 그쪽은 자동으로 안전하다.
    """
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
