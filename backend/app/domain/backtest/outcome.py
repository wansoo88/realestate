"""실현 수익률 · 벤치마크 · 생존 편향. 순수 함수.

설계 정본: `docs/02-design/backtest.md` §3

여기서 정하는 세 가지
---------------------
1. **가격 시점** — 셀의 한 시점 ₩/㎡ 중위. 양 끝을 **같은 함수**로 만든다.
   한쪽만 신고 지연을 빼면 경과 시간이 12개월이 아니게 된다.
2. **비교 기준** — 성공기준 ④의 "시장 평균"이 무엇인지 문서 어디에도 없었다. 여기서 정의한다.
   **두 개를 함께 낸다**(B1 시장 중위 · B2 동종 중위). 하나만 고르면 반드시 오해가 생긴다.
3. **생존 편향** — T+12 에 거래가 없는 셀은 수익률이 없다. 그냥 빼면 "안 팔린 물건"이
   통계에서 사라진다. 지어내지도, 조용히 빼지도 않는다 — **커버리지를 항상 보고**하고
   민감도(`UnmeasuredPolicy`)로 반대쪽 가정도 함께 낸다.
"""
from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from app.domain.backtest.asof import REPORT_LAG_DAYS, visible_cutoff
from app.domain.backtest.models import (
    MIN_TRADES_PER_ENDPOINT,
    REASON_NO_TRADE,
    REASON_TOO_FEW,
    BacktestTrade,
    CellOutcome,
    CellRef,
    PricePoint,
    add_months,
)

#: 동종(B2) 벤치마크를 세울 최소 피어 셀 수. 이보다 적으면 **B2 를 만들지 않는다**.
#:
#: 왜 10인가 — 중위값의 표준오차는 표본이 작을수록 급히 커진다. 5개짜리 피어군의 중위는
#: 한두 셀의 우연에 좌우되고, 그 우연이 그대로 '초과수익'으로 보고된다.
#: ⚠️ 이 값은 **우리가 실측한 숫자가 아니다.** 시군구×면적대 피어군의 실제 크기 분포를
#:    아직 재 보지 않았다(백필 중이라 DB 를 두드리지 않았다). 첫 실행에서 이 문턱 때문에
#:    B2 가 얼마나 비는지 리포트에 나오므로, 그 실측을 보고 조정한다.
MIN_PEER_CELLS = 10

#: 상위 N 의 측정률이 이 값 미만이면 그 폴드는 **표제 숫자로 인용하지 못한다**(§3-D-4).
MIN_MEASURED_RATE_PCT = 70.0

#: `CellOutcome.reason` 문구.
REASON_NO_START = "T 시점 가격을 세울 표본이 없습니다"
REASON_NO_END = "T+H 시점 거래가 없어 실현 수익률을 잴 수 없습니다(생존 편향 대상)"


class UnmeasuredPolicy(str, Enum):
    """T+H 에 거래가 없는 셀을 어떻게 셀 것인가. **둘 다 돌려서 갈리면 결론을 내지 않는다.**"""

    #: 주 지표. 없는 수익률을 지어내지 않는다.
    #: ⚠️ 대신 **생존 편향**이 남는다 — 커버리지를 반드시 함께 읽어야 한다.
    DROP = "drop"

    #: 민감도. 미측정 셀에 시장 중위(B1)를 그대로 부여 → 초과수익 0.
    #: "시장만큼 움직였다"는 무정보 가정이고, 희석 방향이라 보수적이다.
    BENCHMARK = "benchmark"


def price_window(as_of: dt.date, *, window_months: int,
                 report_lag_days: int = REPORT_LAG_DAYS) -> tuple[dt.date, dt.date]:
    """가격 창 `(start, end]`. `end = cutoff(as_of)` · `start = end − window_months개월`.

    **창 경계를 만드는 유일한 자리다.** 일괄 계산(`price_point`)과 스트리밍 집계
    (`collect.FoldCollector`)가 서로 다른 창을 쓰면 같은 데이터에 두 가격이 생긴다 —
    `asof` 가 자르는 곳을 하나로 모은 것과 같은 이유다.
    """
    cutoff = visible_cutoff(as_of, report_lag_days=report_lag_days)
    return add_months(cutoff, -window_months), cutoff


def price_from_values(values: Sequence[float], *, window_months: int,
                      window_end: dt.date | None,
                      min_trades: int = MIN_TRADES_PER_ENDPOINT) -> PricePoint:
    """창 안 ₩/㎡ 값들 → 한 시점 가격. **중위와 표본 하한이 사는 유일한 자리.**

    표본이 `min_trades` 미만이면 **숫자를 만들지 않는다** — 적은 표본의 중위는
    근거가 아니라 착시다(`valuation.MIN_SAMPLE` 과 같은 태도).

    `values` 는 리스트여도 `array('d')` 여도 된다. 스트리밍 집계는 행을 버리고
    이 값들만 남기므로(§7-13), 그 통을 그대로 받을 수 있어야 한다.
    """
    if not len(values):
        return PricePoint(available=False, sample_size=0, window_months=window_months,
                          window_end=window_end, reason=REASON_NO_TRADE)
    if len(values) < min_trades:
        return PricePoint(available=False, sample_size=len(values),
                          window_months=window_months, window_end=window_end,
                          reason=REASON_TOO_FEW)
    return PricePoint(available=True,
                      median_ppm_krw=int(round(statistics.median(values))),
                      sample_size=len(values), window_months=window_months,
                      window_end=window_end)


def price_point(
    trades: Sequence[BacktestTrade],
    *,
    as_of: dt.date,
    window_months: int,
    min_trades: int = MIN_TRADES_PER_ENDPOINT,
    report_lag_days: int = REPORT_LAG_DAYS,
) -> PricePoint:
    """한 셀의 `as_of` 시점 ₩/㎡ 중위.

        창 = ( cutoff(as_of) − window_months , cutoff(as_of) ]

    `trades` 는 **그 셀의 거래**여야 하고, 이미 as-of 뷰를 거친 것이어야 한다.
    (창의 상한을 여기서 한 번 더 적용하므로 뷰를 거친 입력에 대해 멱등이다.)

    ⚠️ 이 함수는 **거래 객체를 들고 있는 호출부**를 위한 것이다. 전 구간을 한 번에
       들고 있으면 안 되는 자리(실행기)는 `collect.FoldCollector` 를 쓴다 — 같은
       `price_from_values` 로 끝난다.
    """
    start, cutoff = price_window(as_of, window_months=window_months,
                                 report_lag_days=report_lag_days)
    values = [t.ppm_krw for t in trades if start < t.contract_date <= cutoff]
    return price_from_values(values, window_months=window_months, window_end=cutoff,
                             min_trades=min_trades)


def forward_return_pct(start: PricePoint, end: PricePoint) -> float | None:
    """두 시점 가격의 변화율(%). 어느 한쪽이라도 없으면 None."""
    if not (start.available and end.available):
        return None
    if not start.median_ppm_krw or not end.median_ppm_krw:
        return None
    return round((end.median_ppm_krw / start.median_ppm_krw - 1) * 100, 3)


def make_outcome(ref: CellRef, sigungu: str | None, *,
                 start: PricePoint, end: PricePoint) -> CellOutcome:
    """가격 두 개 → 결과 하나. 못 잰 이유를 반드시 남긴다."""
    ret = forward_return_pct(start, end)
    if ret is None:
        reason = REASON_NO_START if not start.available else REASON_NO_END
        return CellOutcome(ref=ref, sigungu=sigungu, measured=False, ret_pct=None,
                           start=start, end=end, reason=reason)
    return CellOutcome(ref=ref, sigungu=sigungu, measured=True, ret_pct=ret,
                       start=start, end=end)


@dataclass(frozen=True)
class Benchmark:
    """비교 기준 둘. **유니버스는 후보가 될 수 있었던 셀들과 같아야 한다**(§3-B).

    다른 모집단(예: 수도권 전 거래)과 비교하면 채점이 무의미해진다 — 그 값은
    "내가 한 채 샀을 때의 대안"과 무관하다.
    """

    #: B1 — 유니버스 전체 셀의 수익률 **중위**(셀 동일가중).
    #: 왜 거래 가중이 아닌가: 사용자는 한 채를 산다. 올바른 대조군은 포트폴리오가 아니라
    #: **무작위 한 채**다.
    market_median_pct: float | None
    #: B2 — (시군구, 면적대) 별 수익률 중위. 피어 `< MIN_PEER_CELLS` 면 **키 자체가 없다**.
    peer_median_pct: Mapping[tuple[str, str], float]
    peer_size: Mapping[tuple[str, str], int]
    universe_size: int
    measured_size: int
    min_peer_cells: int = MIN_PEER_CELLS

    @property
    def measured_rate_pct(self) -> float | None:
        """유니버스의 측정률. 상위 N 의 측정률과 **나란히 읽어야** 생존 편향이 보인다."""
        if self.universe_size <= 0:
            return None
        return round(self.measured_size / self.universe_size * 100, 1)

    def peer_for(self, outcome: CellOutcome) -> float | None:
        key = outcome.peer_key
        return self.peer_median_pct.get(key) if key else None


def build_benchmark(outcomes: Iterable[CellOutcome], *,
                    min_peer_cells: int = MIN_PEER_CELLS) -> Benchmark:
    """유니버스 결과들 → 벤치마크. **측정된 셀만** 중위에 들어간다.

    ⚠️ 미측정 셀을 여기서 0%로 채우지 않는다. 그건 "안 움직였다"는 없는 사실이다.
       미측정을 어떻게 셀지는 호출부의 `UnmeasuredPolicy` 가 정하고, 그 선택은
       **상위 N 과 벤치마크 양쪽에 똑같이** 적용된다(한쪽에만 적용하면 비교가 깨진다).
    """
    rows = list(outcomes)
    measured = [o for o in rows if o.measured and o.ret_pct is not None]

    peer_values: dict[tuple[str, str], list[float]] = {}
    for out in measured:
        key = out.peer_key
        if key is None:
            continue
        peer_values.setdefault(key, []).append(out.ret_pct)   # type: ignore[arg-type]

    peer_median = {k: round(statistics.median(v), 3)
                   for k, v in peer_values.items() if len(v) >= min_peer_cells}
    peer_size = {k: len(v) for k, v in peer_values.items()}

    market = (round(statistics.median(o.ret_pct for o in measured), 3)  # type: ignore[misc]
              if measured else None)
    return Benchmark(market_median_pct=market, peer_median_pct=peer_median,
                     peer_size=peer_size, universe_size=len(rows),
                     measured_size=len(measured), min_peer_cells=min_peer_cells)


def resolved_return_pct(outcome: CellOutcome, bench: Benchmark,
                        policy: UnmeasuredPolicy) -> float | None:
    """정책을 반영한 수익률. `DROP` 이면 미측정은 None(집계에서 빠진다)."""
    if outcome.measured:
        return outcome.ret_pct
    if policy is UnmeasuredPolicy.BENCHMARK:
        return bench.market_median_pct
    return None


def excess_market_pct(outcome: CellOutcome, bench: Benchmark,
                      policy: UnmeasuredPolicy = UnmeasuredPolicy.DROP) -> float | None:
    """B1 대비 초과(%p). 미측정 + `BENCHMARK` 정책이면 정확히 0.0 이다."""
    if not outcome.measured:
        return 0.0 if policy is UnmeasuredPolicy.BENCHMARK else None
    if bench.market_median_pct is None or outcome.ret_pct is None:
        return None
    return round(outcome.ret_pct - bench.market_median_pct, 3)


def excess_peer_pct(outcome: CellOutcome, bench: Benchmark,
                    policy: UnmeasuredPolicy = UnmeasuredPolicy.DROP) -> float | None:
    """B2(같은 시군구·면적대) 대비 초과(%p). 피어가 모자라면 None — **0 이 아니다**."""
    if not outcome.measured:
        return 0.0 if policy is UnmeasuredPolicy.BENCHMARK else None
    peer = bench.peer_for(outcome)
    if peer is None or outcome.ret_pct is None:
        return None
    return round(outcome.ret_pct - peer, 3)


def median_or_none(values: Iterable[float | None]) -> float | None:
    """None 을 **버리고** 중위. 하나도 없으면 None(0 이 아니다)."""
    kept = [v for v in values if v is not None]
    return round(statistics.median(kept), 3) if kept else None
