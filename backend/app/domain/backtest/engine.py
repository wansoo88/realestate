"""폴드 실행 · 무작위 대조군 · 국면 라벨 · 집계와 판정. 순수 함수.

설계 정본: `docs/02-design/backtest.md` §3-C · §3-E · §4

여기서 반드시 지키는 것
-----------------------
1. **as-of 뷰를 만드는 곳은 `build_cells` 하나**다. `build_outcomes` 는 T+H 뷰를 따로
   만들지만 그건 결과 측정이고, **점수에는 절대 닿지 않는다**.
2. **벤치마크 유니버스 = 후보 유니버스.** 상위 N 과 벤치마크가 다른 모집단이면
   비교가 성립하지 않는다.
3. **판정(`verdict`)은 "우리 추천이 좋은가"를 말하지 않는다.** 이 모듈이 말하는 것은
   *"이 측정이 유효한가"* 뿐이다. 좋고 나쁨은 사람이 숫자를 보고 판단한다.
"""
from __future__ import annotations

import random
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from app.domain.backtest.asof import (
    REPORT_LAG_DAYS,
    CancellationPolicy,
)
from app.domain.backtest.collect import (
    DEFAULT_CHUNK_ROWS,
    KIND_END,
    KIND_PRIOR,
    KIND_START,
    FoldCollector,
    assert_rereadable,
)
from app.domain.backtest.models import (
    MIN_TRADES_PER_ENDPOINT,
    AsOfCell,
    BacktestTrade,
    CellOutcome,
    CellRef,
    FoldSpec,
)
from app.domain.backtest.outcome import (
    MIN_MEASURED_RATE_PCT,
    MIN_PEER_CELLS,
    Benchmark,
    UnmeasuredPolicy,
    build_benchmark,
    excess_market_pct,
    excess_peer_pct,
    median_or_none,
    resolved_return_pct,
)
from app.domain.backtest.scorers import Scorer

#: 상위 몇 개를 채점할 것인가. `enhancement-research §4` 가 첫 산출물로 제안한 값과 같다
#: ("as-of 2025-07 상위 30단지의 12개월 초과수익 분포 vs 무작위 30단지").
DEFAULT_TOP_N = 30

#: 무작위 대조군 추출 횟수. 1000 이면 백분위 해상도가 0.1%p 다.
DEFAULT_NULL_DRAWS = 1000

#: 대조군 시드. **고정한다** — 같은 입력에 같은 결과가 나와야 리포트를 인용할 수 있다.
DEFAULT_RNG_SEED = 20260804

# --- 국면 라벨 --------------------------------------------------------------
#: ⚠️ 임계값을 만들지 않는다. 우리가 재 본 적 없는 숫자를 "상승/보합 경계"라고 박으면
#:    그게 또 하나의 근거 없는 상수가 된다. **부호만** 쓰고 실제 값(`market_median_pct`)을
#:    항상 함께 낸다. 라벨은 설명용 꼬리표이지 계산 입력이 아니다(문서 §3-E).
REGIME_RISING = "rising"
REGIME_FALLING = "falling"
REGIME_FLAT = "flat"
REGIME_UNKNOWN = "unknown"

# --- 경고 -------------------------------------------------------------------
WARN_LOW_COVERAGE = "low_coverage"
WARN_UNIVERSE_SMALLER_THAN_TOP_N = "universe_smaller_than_top_n"
WARN_NO_MARKET_BENCHMARK = "no_market_benchmark"
WARN_NO_PEER_BENCHMARK = "no_peer_benchmark"
WARN_NO_NULL_CONTROL = "no_null_control"
WARN_TOP_LESS_LIQUID = "top_less_liquid_than_universe"

# --- 판정 -------------------------------------------------------------------
VERDICT_NO_FOLDS = "no_folds"
#: **하락기 폴드가 없다.** 상승장에서는 아무거나 사도 오른다 — 그 구간의 초과수익은
#: 상승장에서만 통하는 특성을 잡아낸 것일 수 있고, 하락장에서 정확히 반대로 작동한다.
VERDICT_RISING_ONLY = "rising_only"
VERDICT_INSUFFICIENT_FOLDS = "insufficient_folds"
VERDICT_MEASURED = "measured"

#: 가중치 교정 입력으로 쓸 수 없을 때 리포트에 붙는 문장(문서 §4-C · §6-1).
CALIBRATION_BLOCKED_NOTE = (
    "하락기 폴드(시장 중위 수익률 < 0)가 없어 이 결과를 '검증됨'이라 부르지 않으며, "
    "총점 가중치 교정의 입력으로 쓸 수 없습니다(docs/02-design/backtest.md §4-C).")
FOLDS_NOT_INDEPENDENT_NOTE = (
    "폴드끼리 가격 창이 겹치므로 서로 독립이 아닙니다 — 폴드 수를 표본 수처럼 읽지 마세요.")
STATIC_AXES_EXCLUDED_NOTE = (
    "학군·교통·생활인프라(현행 총점 가중치의 55%)는 과거 상태를 알 수 없어 채점 대상에서 "
    "제외했습니다. 이 결과는 '우리 총점의 성적'이 아니라 시변 축 셋의 성적입니다(§0).")


# ---------------------------------------------------------------------------
# 1) as-of 유니버스
# ---------------------------------------------------------------------------

def build_cells(
    trades: Iterable[BacktestTrade],
    *,
    spec: FoldSpec,
    households: Mapping[int, int | None] | None = None,
    policy: CancellationPolicy = CancellationPolicy.EXCLUDE_FINAL,
    min_trades: int = MIN_TRADES_PER_ENDPOINT,
    report_lag_days: int = REPORT_LAG_DAYS,
    min_peer_cells: int = MIN_PEER_CELLS,
    chunk_rows: int = DEFAULT_CHUNK_ROWS,
) -> list[AsOfCell]:
    """T 시점 후보 유니버스.

    **해제 여부(`is_cancelled`)를 제외하면 출력은 T 이후 데이터에 의존하지 않는다.**
    기본 정책(`EXCLUDE_FINAL`)은 *사후에 확정된* 해제여부로 T 시점 표본을 청소하므로
    그 축만은 누출이 맞고, 그건 §2-D 의 상·하한(두 정책을 다 돌린다)으로만 말한다.
    나머지 축(계약일 경계·`apt_dong`·미래 날짜 칸)에 대해서는 테스트가 직접 단언한다 —
    T 이후 거래를 아무리 넣어도 이 함수의 출력은 한 글자도 바뀌지 않는다.

    T 시점 가격이 서지 않는 셀은 **유니버스에서 빠진다**. 점수도 벤치마크도 만들 수
    없는 셀을 남겨 두면 분모만 부풀어 커버리지 지표가 거짓말을 한다.

    ⚠️ 집계는 `collect.FoldCollector` 가 한다 — **행을 통째로 들고 있지 않기 위해서다**
    (CR49-3). 여기서 `trades` 는 한 번만 순회되고, 실행기는 같은 수집기를 폴드 여럿에
    **한 번의 순회로** 재사용한다.

    ⛔ `trades` 는 **다시 훑을 수 있어야** 한다(리스트 등). 이터레이터를 주면 `TypeError` 다 —
       같은 것을 `build_outcomes` 에 또 넘기는 순간 조용히 0행이 되기 때문이다(CR50-3).
       스트리밍이 필요하면 `FoldCollector` 를 직접 쓴다(실행기가 그렇게 한다).
    """
    assert_rereadable(trades, where="build_cells")
    collector = FoldCollector([spec], policy=policy, report_lag_days=report_lag_days,
                              min_trades=min_trades, min_peer_cells=min_peer_cells,
                              kinds=(KIND_START, KIND_PRIOR), chunk_rows=chunk_rows)
    collector.feed(trades)
    return collector.cells(spec, households=households)


# ---------------------------------------------------------------------------
# 2) T+H 결과
# ---------------------------------------------------------------------------

def build_outcomes(
    trades: Iterable[BacktestTrade],
    cells: Sequence[AsOfCell],
    *,
    spec: FoldSpec,
    policy: CancellationPolicy = CancellationPolicy.EXCLUDE_FINAL,
    min_trades: int = MIN_TRADES_PER_ENDPOINT,
    report_lag_days: int = REPORT_LAG_DAYS,
    chunk_rows: int = DEFAULT_CHUNK_ROWS,
) -> dict[CellRef, CellOutcome]:
    """`cells` 각각의 T+H 실현 결과.

    T+H 시점 가격도 **같은 함수**(`price_from_values`)로 만든다. 한쪽만 신고 지연을
    빼면 경과 시간이 지평(H)과 달라진다.

    ⚠️ 여기서 만든 뷰는 **미래를 본다**. 그게 이 함수의 일이다. 대신 이 결과가 점수로
       역류하지 않게, 반환 타입에 점수가 없고 `run_fold` 가 점수를 먼저 확정한다.

    ⛔ `build_cells` 와 같은 이유로 이터레이터를 받지 않는다 — **바로 이 짝**이
       "두 번째 순회에 조용히 0행" 함정의 실제 재현 경로였다(CR50-3).
    """
    assert_rereadable(trades, where="build_outcomes")
    collector = FoldCollector([spec], policy=policy, report_lag_days=report_lag_days,
                              min_trades=min_trades, kinds=(KIND_END,),
                              chunk_rows=chunk_rows)
    collector.feed(trades)
    return collector.outcomes(spec, cells)


# ---------------------------------------------------------------------------
# 3) 폴드 실행
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FoldResult:
    """폴드 하나의 채점표. **커버리지와 대조군 없이 초과수익만 읽으면 안 된다.**"""

    spec: FoldSpec
    scorer_name: str
    unmeasured_policy: UnmeasuredPolicy
    top_n: int

    #: 후보 셀 수(= T 시점 가격이 선 셀 전부).
    universe_size: int
    #: 그중 **점수가 나온** 셀 수. 벤치마크·대조군의 모집단은 이쪽이다(§3-B).
    scored_size: int
    picked: tuple[CellRef, ...] = ()

    market_median_pct: float | None = None
    regime: str = REGIME_UNKNOWN

    top_median_ret_pct: float | None = None
    top_median_excess_market_pct: float | None = None
    top_median_excess_peer_pct: float | None = None
    top_hit_rate_pct: float | None = None

    top_measured: int = 0
    top_measured_rate_pct: float | None = None
    #: ⚠️ 분모가 `universe_size` 가 **아니다** — 점수가 매겨진 풀(`scored_size`) 기준이다
    #:    (`bench.universe_size`). 상위 N 측정률과 같은 모집단이어야 나란히 읽을 수 있다.
    universe_measured_rate_pct: float | None = None

    null_percentile: float | None = None
    null_draws: int = 0
    null_median_of_medians_pct: float | None = None

    warnings: tuple[str, ...] = ()

    @property
    def quotable(self) -> bool:
        """이 폴드의 숫자를 표제로 인용해도 되는가. 커버리지 가드(§3-D-4)."""
        return WARN_LOW_COVERAGE not in self.warnings and self.top_measured > 0


def run_fold(
    *,
    spec: FoldSpec,
    cells: Sequence[AsOfCell],
    outcomes: Mapping[CellRef, CellOutcome],
    scorer: Scorer,
    top_n: int = DEFAULT_TOP_N,
    unmeasured_policy: UnmeasuredPolicy = UnmeasuredPolicy.DROP,
    min_peer_cells: int = MIN_PEER_CELLS,
    null_draws: int = DEFAULT_NULL_DRAWS,
    rng_seed: int = DEFAULT_RNG_SEED,
    min_measured_rate_pct: float = MIN_MEASURED_RATE_PCT,
) -> FoldResult:
    """점수 → 상위 N → 실현 수익률 → 벤치마크 → 무작위 대조군.

    순서가 중요하다. **점수를 먼저 확정한 뒤에** 결과를 붙인다 — 그래야
    "결과를 보고 뽑았다"가 구조적으로 불가능하다.
    """
    scores = scorer(cells)
    # 정렬은 (점수 내림차순, 단지ID, 면적대). 동점일 때도 결정적이어야 대조군과 비교된다.
    scored = sorted(
        ((ref, value) for ref, value in scores.items() if value is not None),
        key=lambda item: (-item[1], item[0].complex_id, item[0].band))
    pool = [ref for ref, _ in scored]
    picked = tuple(pool[:top_n])

    # 벤치마크 유니버스 = **점수가 매겨진 풀**(후보가 될 수 있었던 셀들). §3-B
    pool_outcomes = [outcomes[ref] for ref in pool if ref in outcomes]
    bench = build_benchmark(pool_outcomes, min_peer_cells=min_peer_cells)

    picked_outcomes = [outcomes[ref] for ref in picked if ref in outcomes]
    top_measured = sum(1 for o in picked_outcomes if o.measured)

    rets = [resolved_return_pct(o, bench, unmeasured_policy) for o in picked_outcomes]
    ex_market = [excess_market_pct(o, bench, unmeasured_policy) for o in picked_outcomes]
    ex_peer = [excess_peer_pct(o, bench, unmeasured_policy) for o in picked_outcomes]

    hits = [v for v in ex_market if v is not None]
    hit_rate = (round(sum(1 for v in hits if v > 0) / len(hits) * 100, 1)
                if hits else None)

    top_rate = (round(top_measured / len(picked_outcomes) * 100, 1)
                if picked_outcomes else None)
    universe_rate = bench.measured_rate_pct

    null_pct, null_median = _null_control(
        pool=pool, outcomes=outcomes, bench=bench, top_n=top_n,
        actual=median_or_none(ex_market), draws=null_draws, seed=rng_seed,
        policy=unmeasured_policy)

    warnings: list[str] = []
    if len(pool) < top_n:
        warnings.append(WARN_UNIVERSE_SMALLER_THAN_TOP_N)
    if bench.market_median_pct is None:
        warnings.append(WARN_NO_MARKET_BENCHMARK)
    if not any(v is not None for v in ex_peer):
        warnings.append(WARN_NO_PEER_BENCHMARK)
    if top_rate is not None and top_rate < min_measured_rate_pct:
        warnings.append(WARN_LOW_COVERAGE)
    if (top_rate is not None and universe_rate is not None
            and top_rate < universe_rate):
        # 상위 N 이 유니버스보다 덜 팔린다 = 우리 점수가 환금성 나쁜 쪽으로 쏠린다.
        # 초과수익보다 중요할 수 있는 결과다(§3-D-1).
        warnings.append(WARN_TOP_LESS_LIQUID)
    if null_pct is None:
        warnings.append(WARN_NO_NULL_CONTROL)

    return FoldResult(
        spec=spec, scorer_name=scorer.name, unmeasured_policy=unmeasured_policy,
        top_n=top_n, universe_size=len(cells), scored_size=len(pool), picked=picked,
        market_median_pct=bench.market_median_pct,
        regime=classify_regime(bench.market_median_pct),
        top_median_ret_pct=median_or_none(rets),
        top_median_excess_market_pct=median_or_none(ex_market),
        top_median_excess_peer_pct=median_or_none(ex_peer),
        top_hit_rate_pct=hit_rate,
        top_measured=top_measured, top_measured_rate_pct=top_rate,
        universe_measured_rate_pct=universe_rate,
        null_percentile=null_pct, null_draws=null_draws if null_pct is not None else 0,
        null_median_of_medians_pct=null_median,
        warnings=tuple(warnings))


def _null_control(*, pool: Sequence[CellRef], outcomes: Mapping[CellRef, CellOutcome],
                  bench: Benchmark, top_n: int, actual: float | None, draws: int,
                  seed: int, policy: UnmeasuredPolicy) -> tuple[float | None, float | None]:
    """무작위로 N 개를 `draws` 번 뽑아 **초과수익 중위의 분포**를 만든다(§3-C).

    상위 N 의 `+1.2%p` 같은 값 하나로는 아무 말도 못 한다 — 표본 30개의 중위는 그 정도로
    흔들린다. 백분위가 나와야 "우연과 구별되는가"를 물을 수 있다.

    무작위 표본도 **같은 풀**에서 뽑고 **같은 측정 탈락 규칙**을 받는다. 그러지 않으면
    대조군만 측정률이 높아져 비교가 깨진다.
    """
    if actual is None or draws <= 0 or len(pool) < top_n or top_n <= 0:
        return None, None
    rng = random.Random(seed)
    # 루프 밖에서 한 번만 만든다. 기본 draws=1000 이라 안에 두면 유니버스(운영에서 수만 셀)를
    # **1,000번** 새로 복사한다 — 이 스크립트가 도는 서버는 가용 261MB 다(CR49 잔가지).
    population = list(pool)
    medians: list[float] = []
    for _ in range(draws):
        sample = rng.sample(population, top_n)
        values = [excess_market_pct(outcomes[ref], bench, policy)
                  for ref in sample if ref in outcomes]
        median = median_or_none(values)
        if median is not None:
            medians.append(median)
    if not medians:
        return None, None
    below = sum(1 for m in medians if m <= actual)
    return (round(below / len(medians) * 100, 1),
            round(statistics.median(medians), 3))


def classify_regime(market_median_pct: float | None) -> str:
    """국면 라벨. **부호만** 본다 — 임계값을 지어내지 않는다."""
    if market_median_pct is None:
        return REGIME_UNKNOWN
    if market_median_pct > 0:
        return REGIME_RISING
    if market_median_pct < 0:
        return REGIME_FALLING
    return REGIME_FLAT


# ---------------------------------------------------------------------------
# 4) 집계와 판정
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BacktestReport:
    """폴드 여러 개의 집계. `verdict` 는 **측정이 유효한가**만 말한다."""

    scorer_name: str
    folds: tuple[FoldResult, ...]
    verdict: str
    regimes: tuple[str, ...] = ()
    median_excess_market_pct: float | None = None
    median_excess_peer_pct: float | None = None
    quotable_folds: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def may_calibrate_weights(self) -> bool:
        """이 결과를 총점 가중치 교정의 입력으로 써도 되는가(§6-1)."""
        return self.verdict == VERDICT_MEASURED and self.quotable_folds >= 2


def summarize(results: Sequence[FoldResult], *,
              min_folds: int = 2) -> BacktestReport:
    """폴드들 → 리포트. **하락기 폴드가 없으면 `rising_only` 로 막는다**(§4-C).

    집계는 **폴드 동일가중 중위**다. 거래가 많은 시기가 결론을 지배하지 않게 하기 위해서다.
    폴드끼리 창이 겹쳐 독립이 아니므로 폴드별 값을 항상 함께 낸다.
    """
    folds = tuple(results)
    if not folds:
        return BacktestReport(scorer_name="", folds=(), verdict=VERDICT_NO_FOLDS,
                              notes=(STATIC_AXES_EXCLUDED_NOTE,))

    regimes = tuple(f.regime for f in folds)
    quotable = tuple(f for f in folds if f.quotable)

    if REGIME_FALLING not in regimes:
        verdict = VERDICT_RISING_ONLY
    elif len(folds) < min_folds:
        verdict = VERDICT_INSUFFICIENT_FOLDS
    else:
        verdict = VERDICT_MEASURED

    notes = [STATIC_AXES_EXCLUDED_NOTE]
    if verdict == VERDICT_RISING_ONLY:
        notes.append(CALIBRATION_BLOCKED_NOTE)
    if len(folds) > 1:
        notes.append(FOLDS_NOT_INDEPENDENT_NOTE)
    if len(quotable) < len(folds):
        notes.append(
            f"커버리지 미달로 표제 인용에서 제외된 폴드 {len(folds) - len(quotable)}개 "
            f"— 상위 N 측정률 {MIN_MEASURED_RATE_PCT:.0f}% 미만(§3-D-4).")

    return BacktestReport(
        scorer_name=folds[0].scorer_name,
        folds=folds,
        verdict=verdict,
        regimes=regimes,
        median_excess_market_pct=median_or_none(
            f.top_median_excess_market_pct for f in quotable),
        median_excess_peer_pct=median_or_none(
            f.top_median_excess_peer_pct for f in quotable),
        quotable_folds=len(quotable),
        notes=tuple(notes),
    )


def run_backtest(
    trades: Sequence[BacktestTrade],
    specs: Sequence[FoldSpec],
    *,
    scorer: Scorer,
    households: Mapping[int, int | None] | None = None,
    policy: CancellationPolicy = CancellationPolicy.EXCLUDE_FINAL,
    top_n: int = DEFAULT_TOP_N,
    unmeasured_policy: UnmeasuredPolicy = UnmeasuredPolicy.DROP,
    min_trades: int = MIN_TRADES_PER_ENDPOINT,
    min_peer_cells: int = MIN_PEER_CELLS,
    report_lag_days: int = REPORT_LAG_DAYS,
    null_draws: int = DEFAULT_NULL_DRAWS,
    rng_seed: int = DEFAULT_RNG_SEED,
) -> BacktestReport:
    """전 과정을 한 번에. **여전히 순수 함수**다.

    ⚠️ 거래를 **한 번만** 순회한다(폴드가 몇 개든). 실행기(`scripts/run_backtest.py`)도
       같은 수집기를 쓰는데, 거기서는 그게 취향이 아니라 필수다 — 전 구간을 리스트로
       접으면 서버 가용 메모리의 90%를 먹는다(CR49-3 · `collect.py` 머리주석).
    """
    collector = FoldCollector(specs, policy=policy, report_lag_days=report_lag_days,
                              min_trades=min_trades, min_peer_cells=min_peer_cells)
    collector.feed(trades)

    results = []
    for spec in specs:
        cells = collector.cells(spec, households=households)
        outcomes = collector.outcomes(spec, cells)
        results.append(run_fold(
            spec=spec, cells=cells, outcomes=outcomes, scorer=scorer, top_n=top_n,
            unmeasured_policy=unmeasured_policy, min_peer_cells=min_peer_cells,
            null_draws=null_draws, rng_seed=rng_seed))
    return summarize(results)


def fold_row(result: FoldResult) -> dict[str, object]:
    """리포트 출력용 평평한 dict. **개인 정보가 들어가지 않는다** — 통계와 셀 식별자뿐."""
    return {
        "fold": result.spec.name,
        "as_of": result.spec.as_of.isoformat(),
        "horizon_months": result.spec.horizon_months,
        "window_months": result.spec.window_months,
        "scorer": result.scorer_name,
        "unmeasured_policy": result.unmeasured_policy.value,
        "universe_size": result.universe_size,
        "scored_size": result.scored_size,
        "top_n": result.top_n,
        "regime": result.regime,
        "market_median_pct": result.market_median_pct,
        "top_median_ret_pct": result.top_median_ret_pct,
        "top_median_excess_market_pct": result.top_median_excess_market_pct,
        "top_median_excess_peer_pct": result.top_median_excess_peer_pct,
        "top_hit_rate_pct": result.top_hit_rate_pct,
        "top_measured_rate_pct": result.top_measured_rate_pct,
        "universe_measured_rate_pct": result.universe_measured_rate_pct,
        "null_percentile": result.null_percentile,
        "null_draws": result.null_draws,
        "quotable": result.quotable,
        "warnings": list(result.warnings),
    }


__all__ = [
    "DEFAULT_NULL_DRAWS",
    "DEFAULT_RNG_SEED",
    "DEFAULT_TOP_N",
    "BacktestReport",
    "FoldResult",
    "build_cells",
    "build_outcomes",
    "classify_regime",
    "fold_row",
    "run_backtest",
    "run_fold",
    "summarize",
]
