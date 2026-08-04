"""자기 채점(백테스트) 테스트.

설계 정본: `docs/02-design/backtest.md`

이 파일의 규칙
--------------
1. **기대값은 손으로 적는다.** 구현을 돌려 나온 값을 붙여 넣지 않는다. 이 저장소는
   자기충족 테스트(구현이 바뀌면 기대값도 같이 바뀌어 아무것도 못 잡는 형태)를
   반복해서 잡아 왔다. 아래 숫자는 전부 주석에 계산 과정이 있다.
2. **누출 차단이 이 파일의 핵심이다**(`TestLookAhead`). T 이후 데이터를 아무리 넣어도
   결과가 바뀌지 않는 것을 단언하고, **그 독이 실제로 유효한지**도 같이 단언한다
   (가드를 끄면 결과가 바뀌어야 한다 — 안 바뀌면 테스트가 아무것도 안 지키는 것이다).
"""
from __future__ import annotations

import contextlib
import datetime as dt
import weakref
from dataclasses import replace

import pytest

from app.domain.backtest.asof import (
    REPORT_LAG_DAYS,
    CancellationPolicy,
    LookAheadError,
    as_of_trades,
    assert_as_of,
    visible_cutoff,
)
from app.domain.backtest.collect import (
    DEFAULT_CHUNK_ROWS,
    DEFAULT_MAX_SAMPLES,
    FoldCollector,
    SampleLimitExceeded,
    StreamAlreadyConsumed,
)
from app.domain.backtest.engine import (
    REGIME_FALLING,
    REGIME_RISING,
    REGIME_UNKNOWN,
    VERDICT_INSUFFICIENT_FOLDS,
    VERDICT_MEASURED,
    VERDICT_NO_FOLDS,
    VERDICT_RISING_ONLY,
    WARN_LOW_COVERAGE,
    WARN_NO_MARKET_BENCHMARK,
    WARN_NO_NULL_CONTROL,
    WARN_NO_PEER_BENCHMARK,
    WARN_TOP_LESS_LIQUID,
    WARN_UNIVERSE_SMALLER_THAN_TOP_N,
    FoldResult,
    build_cells,
    build_outcomes,
    classify_regime,
    fold_row,
    run_fold,
    summarize,
)
from app.domain.backtest.models import (
    AsOfCell,
    BacktestTrade,
    CellOutcome,
    CellRef,
    FoldSpec,
    PricePoint,
    add_months,
    area_band,
    sigungu_of,
)
from app.domain.backtest.outcome import (
    Benchmark,
    UnmeasuredPolicy,
    build_benchmark,
    excess_market_pct,
    excess_peer_pct,
    forward_return_pct,
    make_outcome,
    median_or_none,
    price_point,
)
from app.domain.backtest.repository import (
    BacktestTradeRepository,
    InMemoryBacktestRepository,
)
from app.domain.backtest.scorers import (
    AXIS_LIQUIDITY,
    AXIS_PRICE_ATTRACTIVENESS,
    AXIS_PRICE_TREND,
    CURRENT_TIMEVARYING_WEIGHTS,
    TIMEVARYING_WEIGHT_SUM,
    constant_scorer,
    percentile_ranks,
    random_scorer,
    raw_liquidity,
    raw_price_attractiveness,
    raw_price_trend,
    single_axis_scorer,
    universe_axis_summary,
    weighted_scorer,
)

# ---------------------------------------------------------------------------
# 공통 픽스처 — 손으로 따라갈 수 있는 최소 세계
#
#   T          = 2025-01-31   → cutoff(T)        = 2025-01-01  (T − 30일)
#   창(12개월)  = (2024-01-01, 2025-01-01]
#   직전 창     = (2023-01-01, 2024-01-01]        (prior_as_of = 2024-01-31)
#   결과 창     = (2025-01-01, 2026-01-01]        (T+12 = 2026-01-31)
#
# 세 창은 서로 겹치지 않는다. 아래 헬퍼가 만드는 거래는 전부 창 안에 들어간다.
# ---------------------------------------------------------------------------
T = dt.date(2025, 1, 31)
SPEC = FoldSpec(as_of=T, horizon_months=12, window_months=12)

REGION_A = "1168010100"          # 서울 강남구(11680)
REGION_B = "4113510100"          # 경기 성남 분당구(41135)
AREA = 84.0                      # → 면적대 "60~85"
BAND = "60~85"

WINDOW_START = dt.date(2024, 2, 1)      # T 창 안
PRIOR_START = dt.date(2023, 2, 1)       # 직전 창 안
OUTCOME_START = dt.date(2025, 2, 1)     # 결과 창 안


def make_trades(complex_id: int, start: dt.date, count: int, ppm: float, *,
                region: str = REGION_A, area: float = AREA, step_days: int = 30,
                **kwargs) -> list[BacktestTrade]:
    """같은 ₩/㎡ 로 `count` 건. 전부 같은 값이라 중위가 정확히 `ppm` 이다(손계산 가능).

    `step_days` 를 줄이면 좁은 구간(예: 신고지연 30일 안쪽)에 `count` 건을 다 넣을 수 있다 —
    중위를 실제로 움직이려면 표본의 **절반 이상**이 필요하기 때문이다.
    """
    price = int(round(ppm * area))
    return [
        BacktestTrade(complex_id=complex_id,
                      contract_date=start + dt.timedelta(days=step_days * i),
                      price_krw=price, area_m2=area, region_code=region, **kwargs)
        for i in range(count)
    ]


#: 5개 셀의 (T 시점 ₩/㎡, T+12 ₩/㎡) — 수익률이 손으로 나온다.
#:   1: 1000 → 1100  = +10%
#:   2: 1200 → 1260  = + 5%
#:   3:  900 →  900  =   0%
#:   4: 1100 → 1210  = +10%
#:   5:  800 →  760  = − 5%
#: 시장 중위(B1) = median(+10, +5, 0, +10, −5) = **+5.0%**
UNIVERSE = ((1, 1000.0, 1100.0), (2, 1200.0, 1260.0), (3, 900.0, 900.0),
            (4, 1100.0, 1210.0), (5, 800.0, 760.0))


def universe_trades() -> list[BacktestTrade]:
    rows: list[BacktestTrade] = []
    for cid, start_ppm, end_ppm in UNIVERSE:
        rows += make_trades(cid, PRIOR_START, 5, start_ppm)        # 직전 창(추세=0%)
        rows += make_trades(cid, WINDOW_START, 5, start_ppm)       # T 창
        rows += make_trades(cid, OUTCOME_START, 5, end_ppm)        # 결과 창
    return rows


HOUSEHOLDS = {1: 500, 2: 500, 3: 500, 4: 500, 5: 500}

#: 독(poison) — **신고지연 구간 안**(2025-01-15·18·21·24·27)에 5번 셀의 터무니없는 고가 5건.
#: cutoff(T)=2025-01-01 보다 뒤이므로 as-of 뷰는 전부 버려야 한다.
#: 5건인 이유: 기존 표본이 5건이라 **중위를 실제로 움직이려면 절반 이상**이 필요하다.
#: 가드를 끄면(`report_lag_days=0`) 5번 셀의 중위 ₩/㎡ 가 800 → 2900 이 된다
#: (800 다섯 · 5000 다섯 → 정렬 후 5·6번째 평균 = (800+5000)/2).
LAG_WINDOW_POISON = make_trades(5, dt.date(2025, 1, 15), 5, 5000.0, step_days=3)


# ===========================================================================
# 1. 기본 계산 — 면적대 · 달력 · 백분위
# ===========================================================================

@pytest.mark.parametrize("area, expected", [
    (10.0, "<60"),
    (59.99, "<60"),
    (60.0, "<60"),        # 경계는 **상한 포함**(법이 "60㎡ 이하"로 쓴다)
    (60.01, "60~85"),
    (84.97, "60~85"),
    (85.0, "60~85"),
    (85.01, "85~102"),
    (102.0, "85~102"),
    (102.01, "102~135"),
    (135.0, "102~135"),
    (135.01, ">135"),
    (200.0, ">135"),
    (0.0, None),
    (-1.0, None),
    (None, None),
])
def test_area_band_boundaries(area, expected):
    assert area_band(area) == expected


def test_sigungu_is_the_first_five_digits():
    assert sigungu_of("1168010100") == "11680"
    assert sigungu_of("11680") == "11680"
    assert sigungu_of("1168") is None          # 짧으면 지어내지 않는다
    assert sigungu_of(None) is None
    assert sigungu_of("") is None


@pytest.mark.parametrize("base, months, expected", [
    (dt.date(2025, 1, 31), 12, dt.date(2026, 1, 31)),
    (dt.date(2025, 1, 31), -12, dt.date(2024, 1, 31)),
    (dt.date(2024, 1, 31), -1, dt.date(2023, 12, 31)),
    (dt.date(2024, 1, 31), 1, dt.date(2024, 2, 29)),     # 윤년 말일로 잘린다
    (dt.date(2025, 1, 31), 1, dt.date(2025, 2, 28)),
    (dt.date(2024, 3, 31), -1, dt.date(2024, 2, 29)),
    (dt.date(2025, 6, 15), 0, dt.date(2025, 6, 15)),
])
def test_add_months_is_calendar_arithmetic(base, months, expected):
    """`timedelta(days=30*n)` 이면 12개월이 360일이 되어 지평이 5일 밀린다."""
    assert add_months(base, months) == expected


def test_percentile_ranks_are_symmetric_and_share_ties():
    """손계산: n=3 · 중간순위 = (lo+hi)/2 → /n × 100.

      [10,20,30] → 0.5/3, 1.5/3, 2.5/3 = 16.667 / 50.0 / 83.333
      [10,10,30] → 동점 둘은 (0+2)/2=1 → 33.333, 30 은 2.5/3 → 83.333
    """
    a, b, c = CellRef(1, BAND), CellRef(2, BAND), CellRef(3, BAND)
    ranks = percentile_ranks({a: 10.0, b: 20.0, c: 30.0})
    assert ranks[a] == pytest.approx(16.6667, abs=1e-4)
    assert ranks[b] == pytest.approx(50.0)
    assert ranks[c] == pytest.approx(83.3333, abs=1e-4)

    tied = percentile_ranks({a: 10.0, b: 10.0, c: 30.0})
    assert tied[a] == tied[b] == pytest.approx(33.3333, abs=1e-4)
    assert tied[c] == pytest.approx(83.3333, abs=1e-4)


def test_percentile_rank_keeps_none_as_none():
    """None 은 '모른다'다. 0 점(='나쁘다')으로 바꾸면 없는 판정이 생긴다."""
    a, b = CellRef(1, BAND), CellRef(2, BAND)
    assert percentile_ranks({a: 5.0, b: None}) == {a: 50.0, b: None}
    assert percentile_ranks({a: None, b: None}) == {a: None, b: None}


# ===========================================================================
# 2. ★ 누출 차단 (as-of 경계) — 이 파일의 핵심
# ===========================================================================

class TestLookAhead:
    """T 이후 데이터가 결과에 **한 글자도** 닿지 못하는지."""

    def test_cutoff_is_report_deadline_before_as_of(self):
        """cutoff(2025-01-31) = 2025-01-01. 30일은 신고기한(부동산거래신고법 §3①)."""
        assert REPORT_LAG_DAYS == 30
        assert visible_cutoff(T) == dt.date(2025, 1, 1)
        assert visible_cutoff(dt.date(2026, 3, 2)) == dt.date(2026, 1, 31)

    def test_boundary_contract_date_is_inclusive(self):
        """cutoff 당일 계약은 **들어오고**, 하루 뒤는 빠진다."""
        on = BacktestTrade(complex_id=1, contract_date=dt.date(2025, 1, 1),
                           price_krw=100, area_m2=AREA)
        after = BacktestTrade(complex_id=1, contract_date=dt.date(2025, 1, 2),
                              price_krw=100, area_m2=AREA)
        kept = as_of_trades([on, after], as_of=T)
        assert [t.contract_date for t in kept] == [dt.date(2025, 1, 1)]

    def test_trade_inside_report_lag_is_excluded(self):
        """T−10일 계약은 T 시점 어느 화면에도 없었다 — 넣으면 그게 누출이다."""
        recent = BacktestTrade(complex_id=1, contract_date=dt.date(2025, 1, 21),
                               price_krw=100, area_m2=AREA)
        assert as_of_trades([recent], as_of=T) == []

    def test_future_trades_do_not_change_the_as_of_view(self):
        """★ T 이후 거래를 **아무리** 넣어도 as-of 뷰가 같다."""
        base = universe_trades()
        poison = (
            # ① 신고지연 구간(2025-01-15~27) — 계약은 T 이전이지만 T 시점엔 안 보였다
            LAG_WINDOW_POISON
            # ② 완전한 미래(2025-06-01~)
            + make_trades(1, dt.date(2025, 6, 1), 5, 9999.0)
        )
        assert as_of_trades(base, as_of=T) == as_of_trades(base + poison, as_of=T)

    def test_future_trades_do_not_change_cells_or_picks(self):
        """★ 유니버스·점수·상위 N 이 전부 그대로여야 한다."""
        base = universe_trades()
        poison = LAG_WINDOW_POISON
        scorer = single_axis_scorer(AXIS_PRICE_ATTRACTIVENESS)

        clean = build_cells(base, spec=SPEC, households=HOUSEHOLDS, min_peer_cells=3)
        dirty = build_cells(base + poison, spec=SPEC, households=HOUSEHOLDS,
                            min_peer_cells=3)
        assert clean == dirty

        picks_clean = run_fold(spec=SPEC, cells=clean,
                               outcomes=build_outcomes(base, clean, spec=SPEC),
                               scorer=scorer, top_n=2, null_draws=0,
                               min_peer_cells=3).picked
        picks_dirty = run_fold(spec=SPEC, cells=dirty,
                               outcomes=build_outcomes(base + poison, dirty, spec=SPEC),
                               scorer=scorer, top_n=2, null_draws=0,
                               min_peer_cells=3).picked
        assert picks_clean == picks_dirty

    def test_the_poison_is_actually_potent(self):
        """★ 변이 시험 — **가드를 끄면 결과가 바뀌어야** 한다.

        이게 없으면 위 두 테스트는 "독이 원래 무해했다"는 이유로도 통과한다.
        `report_lag_days=0` 은 순진한 필터(`contract_date <= T`)와 같다.
        """
        base = universe_trades()
        poison = LAG_WINDOW_POISON

        naive_clean = as_of_trades(base, as_of=T, report_lag_days=0)
        naive_dirty = as_of_trades(base + poison, as_of=T, report_lag_days=0)
        assert naive_clean != naive_dirty, "독이 무해하다 — 테스트가 아무것도 안 지킨다"

        # 순위까지 실제로 뒤집힌다. 손계산(가드 끈 상태):
        #   5번 셀 중위 ₩/㎡ 800 → 2900 · 피어 중위 1000 → 1100
        #   가격매력 = (1100 − own)/1100×100 → c3(900) +18.2 · c1(1000) +9.1 ·
        #              c4(1100) 0 · c2(1200) −9.1 · c5(2900) −163.6
        #   → 상위 2 가 (c5, c3) 에서 **(c3, c1)** 로 바뀐다.
        scorer = single_axis_scorer(AXIS_PRICE_ATTRACTIVENESS)
        cells_clean = build_cells(base, spec=SPEC, households=HOUSEHOLDS,
                                  min_peer_cells=3, report_lag_days=0)
        cells_dirty = build_cells(base + poison, spec=SPEC, households=HOUSEHOLDS,
                                  min_peer_cells=3, report_lag_days=0)
        top_clean = run_fold(spec=SPEC, cells=cells_clean, outcomes={}, scorer=scorer,
                             top_n=2, null_draws=0, min_peer_cells=3).picked
        top_dirty = run_fold(spec=SPEC, cells=cells_dirty, outcomes={}, scorer=scorer,
                             top_n=2, null_draws=0, min_peer_cells=3).picked
        assert top_clean == (CellRef(5, BAND), CellRef(3, BAND))
        assert top_dirty == (CellRef(3, BAND), CellRef(1, BAND))

    def test_apt_dong_is_masked_before_registration(self):
        """동은 **등기 후에야** 채워진다 → T 시점 미등기 거래의 동은 몰랐다(§2-B)."""
        registered = BacktestTrade(complex_id=1, contract_date=dt.date(2024, 6, 1),
                                   price_krw=100, area_m2=AREA,
                                   registered_at=dt.date(2024, 8, 1), apt_dong="101")
        later = BacktestTrade(complex_id=1, contract_date=dt.date(2024, 6, 2),
                              price_krw=100, area_m2=AREA,
                              registered_at=dt.date(2025, 6, 1), apt_dong="102")
        never = BacktestTrade(complex_id=1, contract_date=dt.date(2024, 6, 3),
                              price_krw=100, area_m2=AREA, apt_dong="103")

        kept = {t.contract_date: t for t in as_of_trades([registered, later, never],
                                                         as_of=T)}
        assert kept[dt.date(2024, 6, 1)].apt_dong == "101"      # 그때 이미 등기됨
        assert kept[dt.date(2024, 6, 2)].apt_dong is None       # 등기가 T 이후
        assert kept[dt.date(2024, 6, 2)].registered_at is None  # 미래 날짜도 지운다
        assert kept[dt.date(2024, 6, 3)].apt_dong is None       # 미등기

    def test_apt_dong_masking_is_load_bearing_in_the_build_cells_path(self):
        """★ 마스킹이 **파이프라인에서도** 하중을 받는가 (CR49-6).

        전용 단위 검사(`test_apt_dong_is_masked_before_registration`)만 있으면,
        마스킹을 통째로 지우는 변이가 그 1건만 죽이고 `build_cells` 는 멀쩡히 통과한다
        — 픽스처가 `apt_dong` 을 안 심기 때문이다. 여기서는 심는다.

        마스킹이 살아 있으면 셀 5개가 정상으로 나오고, 지우면 `assert_as_of` 의
        동 그물이 걸려 **LookAheadError 로 멈춘다.**
        """
        registered_after_t = dt.date(2025, 6, 1)           # T = 2025-01-31 보다 뒤
        rows = [replace(t, apt_dong="101", registered_at=registered_after_t)
                for t in universe_trades()]
        assert all(t.registered_at > T and t.apt_dong for t in rows)

        cells = build_cells(rows, spec=SPEC, households=HOUSEHOLDS, min_peer_cells=3)
        assert [c.ref for c in cells] == [CellRef(i, BAND) for i in (1, 2, 3, 4, 5)]
        assert {c.price.median_ppm_krw for c in cells} == {1000, 1200, 900, 1100, 800}

    def test_assert_as_of_catches_a_bypassed_view(self):
        """계산 직전 그물 — 뷰를 거치지 않은 경로가 생기면 **멈춘다**."""
        leaked = [BacktestTrade(complex_id=1, contract_date=dt.date(2025, 1, 20),
                                price_krw=100, area_m2=AREA)]
        with pytest.raises(LookAheadError, match="cutoff"):
            assert_as_of(leaked, as_of=T)

        dong_leak = [BacktestTrade(complex_id=1, contract_date=dt.date(2024, 6, 1),
                                   price_krw=100, area_m2=AREA, apt_dong="101")]
        with pytest.raises(LookAheadError, match="apt_dong"):
            assert_as_of(dong_leak, as_of=T)

    def test_as_of_view_is_a_function_of_the_set_not_the_order(self):
        """입력 순서를 뒤집어도 같은 뷰 — 그래야 누출 테스트가 순서 때문에 통과하지 않는다."""
        base = universe_trades()
        assert as_of_trades(base, as_of=T) == as_of_trades(list(reversed(base)), as_of=T)


# ===========================================================================
# 3. 해제 거래 정책 — 못 막는 축. 상·하한으로만 말한다
# ===========================================================================

class TestCancellationPolicy:
    NORMAL = BacktestTrade(complex_id=1, contract_date=dt.date(2024, 6, 1),
                           price_krw=100, area_m2=AREA)
    NO_DATE = BacktestTrade(complex_id=1, contract_date=dt.date(2024, 6, 2),
                            price_krw=100, area_m2=AREA, is_cancelled=True)
    BEFORE_T = BacktestTrade(complex_id=1, contract_date=dt.date(2024, 6, 3),
                             price_krw=100, area_m2=AREA, is_cancelled=True,
                             cancelled_on=dt.date(2024, 8, 1))
    AFTER_T = BacktestTrade(complex_id=1, contract_date=dt.date(2024, 6, 4),
                            price_krw=100, area_m2=AREA, is_cancelled=True,
                            cancelled_on=dt.date(2025, 6, 1))

    def test_exclude_final_matches_production(self):
        """기본값 — 운영 코드(`NOT is_cancelled`)와 같다. **그리고 그게 누출이다.**"""
        kept = as_of_trades([self.NORMAL, self.NO_DATE, self.BEFORE_T, self.AFTER_T],
                            as_of=T, policy=CancellationPolicy.EXCLUDE_FINAL)
        assert [t.contract_date for t in kept] == [dt.date(2024, 6, 1)]

    def test_include_all_is_the_other_bound(self):
        kept = as_of_trades([self.NORMAL, self.NO_DATE, self.BEFORE_T, self.AFTER_T],
                            as_of=T, policy=CancellationPolicy.INCLUDE_ALL)
        assert len(kept) == 4

    def test_exclude_known_at_refuses_to_guess(self):
        """해제일이 없으면 **조용히 근사하지 않고 멈춘다**(trade 에 컬럼이 없다)."""
        with pytest.raises(LookAheadError, match="cancelled_on"):
            as_of_trades([self.NO_DATE], as_of=T,
                         policy=CancellationPolicy.EXCLUDE_KNOWN_AT)

    def test_exclude_known_at_is_the_correct_rule_when_data_exists(self):
        """마이그레이션 017 이후에 쓸 자리 — T 시점에 살아 있던 것만 남는다."""
        kept = as_of_trades([self.NORMAL, self.BEFORE_T, self.AFTER_T], as_of=T,
                            policy=CancellationPolicy.EXCLUDE_KNOWN_AT)
        assert [t.contract_date for t in kept] == [dt.date(2024, 6, 1),
                                                   dt.date(2024, 6, 4)]
        # 미래의 해제일도 뷰에서 지운다(하위가 실수로 쓰지 못하게).
        assert kept[1].cancelled_on is None


# ===========================================================================
# 4. 가격 시점 · 실현 수익률
# ===========================================================================

def test_price_point_uses_the_trailing_window_and_needs_min_sample():
    """창 = (cutoff − 12개월, cutoff]. 5건 미만이면 **숫자를 만들지 않는다**."""
    rows = make_trades(1, WINDOW_START, 5, 1000.0)
    point = price_point(as_of_trades(rows, as_of=T), as_of=T, window_months=12)
    assert point.available is True
    assert point.median_ppm_krw == 1000            # 전부 같은 값 → 중위 = 1000
    assert point.sample_size == 5
    assert point.window_end == dt.date(2025, 1, 1)

    short = price_point(as_of_trades(rows[:4], as_of=T), as_of=T, window_months=12)
    assert short.available is False
    assert short.sample_size == 4
    assert short.median_ppm_krw is None
    assert "최소 표본" in (short.reason or "")


def test_price_point_ignores_trades_outside_the_window():
    """직전 창(2023년) 거래는 T 창에 들어오지 않는다 — 두 창은 겹치지 않는다."""
    rows = make_trades(1, PRIOR_START, 5, 1000.0)
    assert price_point(rows, as_of=T, window_months=12).available is False
    assert price_point(rows, as_of=SPEC.prior_as_of, window_months=12).available is True


def test_price_point_median_of_odd_and_even_samples():
    """손계산: [800,900,1000,1100,1200] → 1000 · 짝수면 가운데 둘의 평균."""
    odd = [make_trades(1, WINDOW_START + dt.timedelta(days=i), 1, ppm)[0]
           for i, ppm in enumerate((800.0, 900.0, 1000.0, 1100.0, 1200.0))]
    assert price_point(odd, as_of=T, window_months=12).median_ppm_krw == 1000

    even = odd + make_trades(1, WINDOW_START + dt.timedelta(days=5), 1, 1400.0)
    # 정렬 [800,900,1000,1100,1200,1400] → (1000+1100)/2 = 1050
    assert price_point(even, as_of=T, window_months=12).median_ppm_krw == 1050


def test_forward_return_is_the_ratio_of_two_price_points():
    start = PricePoint(available=True, median_ppm_krw=1000, sample_size=5)
    end = PricePoint(available=True, median_ppm_krw=1100, sample_size=5)
    assert forward_return_pct(start, end) == pytest.approx(10.0)
    assert forward_return_pct(end, start) == pytest.approx(-9.091, abs=1e-3)

    missing = PricePoint(available=False, reason="x")
    assert forward_return_pct(start, missing) is None
    assert forward_return_pct(missing, end) is None


def test_outcome_records_why_it_could_not_be_measured():
    ok = PricePoint(available=True, median_ppm_krw=1000, sample_size=5)
    gone = PricePoint(available=False, sample_size=0, reason="창 안에 거래가 없습니다")
    out = make_outcome(CellRef(1, BAND), "11680", start=ok, end=gone)
    assert out.measured is False and out.ret_pct is None
    assert "생존 편향" in (out.reason or "")


# ===========================================================================
# 5. 벤치마크 — 무엇을 "시장 평균"이라 부르는가
# ===========================================================================

def outcome_of(cid: int, ret: float | None, sigungu: str = "11680") -> CellOutcome:
    ok = PricePoint(available=True, median_ppm_krw=1000, sample_size=5)
    if ret is None:
        return CellOutcome(ref=CellRef(cid, BAND), sigungu=sigungu, measured=False,
                           ret_pct=None, start=ok,
                           end=PricePoint(available=False, reason="없음"),
                           reason="T+H 시점 거래가 없어 실현 수익률을 잴 수 없습니다")
    end = PricePoint(available=True, median_ppm_krw=int(1000 * (1 + ret / 100)),
                     sample_size=5)
    return CellOutcome(ref=CellRef(cid, BAND), sigungu=sigungu, measured=True,
                       ret_pct=ret, start=ok, end=end)


def test_benchmark_is_equal_weighted_median_of_the_same_universe():
    """손계산.

      전체 측정치 [1, 2, 3, 10, 20] → **B1 중위 = 3.0**
      피어 11680 = [1,2,3] (3개 ≥ min 3) → **B2 = 2.0**
      피어 41135 = [10,20] (2개 < 3)    → **키 자체가 없다**(지어내지 않는다)
    """
    rows = [outcome_of(1, 1.0), outcome_of(2, 2.0), outcome_of(3, 3.0),
            outcome_of(4, 10.0, "41135"), outcome_of(5, 20.0, "41135")]
    bench = build_benchmark(rows, min_peer_cells=3)

    assert bench.market_median_pct == pytest.approx(3.0)
    assert bench.peer_median_pct[("11680", BAND)] == pytest.approx(2.0)
    assert ("41135", BAND) not in bench.peer_median_pct
    assert bench.universe_size == 5 and bench.measured_size == 5
    assert bench.measured_rate_pct == pytest.approx(100.0)

    assert excess_market_pct(rows[0], bench) == pytest.approx(-2.0)   # 1 − 3
    assert excess_peer_pct(rows[0], bench) == pytest.approx(-1.0)     # 1 − 2
    assert excess_market_pct(rows[3], bench) == pytest.approx(7.0)    # 10 − 3
    assert excess_peer_pct(rows[3], bench) is None                    # 피어 없음 ≠ 0


def test_benchmark_excludes_unmeasured_from_the_median():
    """미측정을 0%로 채우면 '안 움직였다'는 없는 사실이 생긴다.

    손계산: 측정치 [1,2,3] → 중위 2.0. 미측정 2건은 분모(universe)에만 들어간다
    → 측정률 3/5 = 60.0%.
    """
    rows = [outcome_of(1, 1.0), outcome_of(2, 2.0), outcome_of(3, 3.0),
            outcome_of(4, None), outcome_of(5, None)]
    bench = build_benchmark(rows, min_peer_cells=3)
    assert bench.market_median_pct == pytest.approx(2.0)
    assert bench.measured_size == 3 and bench.universe_size == 5
    assert bench.measured_rate_pct == pytest.approx(60.0)


def test_unmeasured_policy_changes_only_the_unmeasured_cells():
    """DROP → None(집계에서 빠짐) · BENCHMARK → 초과 정확히 0.0(희석)."""
    rows = [outcome_of(1, 1.0), outcome_of(2, 2.0), outcome_of(3, 3.0),
            outcome_of(4, None)]
    bench = build_benchmark(rows, min_peer_cells=3)
    dead = rows[3]
    assert excess_market_pct(dead, bench, UnmeasuredPolicy.DROP) is None
    assert excess_market_pct(dead, bench, UnmeasuredPolicy.BENCHMARK) == 0.0
    assert excess_peer_pct(dead, bench, UnmeasuredPolicy.BENCHMARK) == 0.0
    # 측정된 셀은 정책에 영향받지 않는다.
    assert excess_market_pct(rows[0], bench, UnmeasuredPolicy.BENCHMARK) == \
        excess_market_pct(rows[0], bench, UnmeasuredPolicy.DROP)


def test_median_or_none_drops_none_and_never_returns_zero():
    assert median_or_none([1.0, None, 3.0]) == pytest.approx(2.0)
    assert median_or_none([None, None]) is None
    assert median_or_none([]) is None


def test_empty_benchmark_has_no_median():
    bench = build_benchmark([])
    assert bench.market_median_pct is None
    assert bench.measured_rate_pct is None
    assert bench.peer_median_pct == {}


# ===========================================================================
# 6. 점수 함수 — 원값과 결합
# ===========================================================================

def cell(cid: int, *, ppm: int | None = 1000, peer: int | None = 1000,
         prior: int | None = 1000, households: int | None = 500,
         count: int = 10, window: int = 12) -> AsOfCell:
    price = (PricePoint(available=True, median_ppm_krw=ppm, sample_size=count,
                        window_months=window)
             if ppm is not None else
             PricePoint(available=False, window_months=window, reason="없음"))
    prior_point = (PricePoint(available=True, median_ppm_krw=prior, sample_size=count,
                              window_months=window)
                   if prior is not None else
                   PricePoint(available=False, window_months=window, reason="없음"))
    return AsOfCell(ref=CellRef(cid, BAND), as_of=T, sigungu="11680", price=price,
                    prior_price=prior_point, window_trade_count=count,
                    total_households=households, peer_median_ppm_krw=peer)


def test_raw_axis_values_are_hand_checkable():
    """손계산.

      가격매력 = (peer − own)/peer×100 = (1000 − 800)/1000×100 = **20.0**
      가격추세 = (now/before − 1)×100  = (1100/1000 − 1)×100  = **10.0**
      환금성   = 거래 10건 ÷ 세대 500 × (12/12) × 100        = ** 2.0**
    """
    c = cell(1, ppm=800, peer=1000, prior=1000, households=500, count=10)
    assert raw_price_attractiveness(c) == pytest.approx(20.0)

    trend = cell(1, ppm=1100, prior=1000)
    assert raw_price_trend(trend) == pytest.approx(10.0)

    liq = cell(1, households=500, count=10, window=12)
    assert raw_liquidity(liq) == pytest.approx(2.0)
    # 창이 6개월이면 연율 환산으로 두 배가 된다: 10×(12/6)/500×100 = 4.0
    assert raw_liquidity(cell(1, households=500, count=10, window=6)) == \
        pytest.approx(4.0)


def test_raw_axes_return_none_instead_of_inventing_a_score():
    assert raw_price_attractiveness(cell(1, peer=None)) is None
    assert raw_price_trend(cell(1, prior=None)) is None
    assert raw_liquidity(cell(1, households=None)) is None
    assert raw_liquidity(cell(1, households=0)) is None      # 0 이면 무한이 된다


def test_current_weights_are_the_documented_heuristic_and_sum_to_045():
    """`hexagon-report-data.md §8` 의 총점 가중치 중 **시변 축 셋**. 합 0.45.

    나머지 0.55(학군 .20 · 교통 .20 · 인프라 .15)는 과거를 몰라 채점 대상 밖이다.
    이 숫자가 조용히 바뀌면 '무엇을 채점하고 있는지'가 달라진다 — 그래서 고정한다.
    """
    assert CURRENT_TIMEVARYING_WEIGHTS[AXIS_PRICE_ATTRACTIVENESS] == pytest.approx(0.20)
    assert CURRENT_TIMEVARYING_WEIGHTS[AXIS_LIQUIDITY] == pytest.approx(0.15)
    assert CURRENT_TIMEVARYING_WEIGHTS[AXIS_PRICE_TREND] == pytest.approx(0.10)
    assert TIMEVARYING_WEIGHT_SUM == pytest.approx(0.45)


def test_weighted_scorer_renormalizes_missing_axes():
    """손계산 (`scoring.py` 와 같은 재정규화 규칙).

      A: 가격매력 raw 20 · B: raw −20 → 백분위 A=75.0 · B=25.0 (n=2)
      A 만 추세·환금성이 있으므로 그 두 축은 n=1 → A=50.0 · B=None
      A = (0.20×75 + 0.15×50 + 0.10×50) / 0.45 = 27.5/0.45 = **61.1111**
      B = (0.20×25) / 0.20                                  = **25.0**
    """
    a = cell(1, ppm=800, peer=1000, prior=1000, households=500, count=10)
    b = cell(2, ppm=1200, peer=1000, prior=None, households=None, count=10)
    scores = weighted_scorer()([a, b])
    assert scores[a.ref] == pytest.approx(61.1111, abs=1e-4)
    assert scores[b.ref] == pytest.approx(25.0)


def test_weighted_scorer_returns_none_when_no_axis_has_a_signal():
    """근거가 하나도 없으면 **점수를 만들지 않는다**(0 점이 아니다)."""
    blind = cell(1, peer=None, prior=None, households=None)
    assert weighted_scorer()([blind])[blind.ref] is None


def test_random_scorer_is_deterministic_and_order_independent():
    """대조군이 목록 순서에 흔들리면 대조군 구실을 못 한다."""
    cells = [cell(i) for i in (1, 2, 3, 4, 5)]
    first = random_scorer(7)(cells)
    assert first == random_scorer(7)(list(reversed(cells)))
    assert first != random_scorer(8)(cells)
    assert all(0.0 <= v < 100.0 for v in first.values())


def test_constant_scorer_ties_everything():
    cells = [cell(i) for i in (1, 2, 3)]
    assert set(constant_scorer()(cells).values()) == {50.0}


def test_universe_axis_summary_reports_coverage_first():
    """무엇이 비는지 먼저 본다 — 커버리지가 낮으면 초과수익은 읽을 수 없다."""
    cells = [cell(1, ppm=800), cell(2, ppm=1200, households=None)]
    summary = universe_axis_summary(cells)
    assert summary[AXIS_LIQUIDITY]["cells"] == 2
    assert summary[AXIS_LIQUIDITY]["with_value"] == 1
    assert summary[AXIS_LIQUIDITY]["coverage_pct"] == pytest.approx(50.0)
    assert summary[AXIS_PRICE_ATTRACTIVENESS]["coverage_pct"] == pytest.approx(100.0)


# ===========================================================================
# 7. 폴드 실행 — 통합 (손계산 유니버스)
# ===========================================================================

def build_fold(scorer, *, top_n=2, null_draws=0,
               unmeasured=UnmeasuredPolicy.DROP) -> FoldResult:
    trades = universe_trades()
    cells = build_cells(trades, spec=SPEC, households=HOUSEHOLDS, min_peer_cells=3)
    outcomes = build_outcomes(trades, cells, spec=SPEC)
    return run_fold(spec=SPEC, cells=cells, outcomes=outcomes, scorer=scorer,
                    top_n=top_n, null_draws=null_draws, min_peer_cells=3,
                    unmeasured_policy=unmeasured)


def test_universe_is_built_from_the_as_of_view_only():
    """5개 셀 전부 T 창에 5건씩 → 유니버스 5. 피어 중위 ₩/㎡ = median(1000,1200,900,1100,800) = 1000."""
    cells = build_cells(universe_trades(), spec=SPEC, households=HOUSEHOLDS,
                        min_peer_cells=3)
    assert len(cells) == 5
    assert [c.ref for c in cells] == [CellRef(i, BAND) for i in (1, 2, 3, 4, 5)]
    assert {c.price.median_ppm_krw for c in cells} == {1000, 1200, 900, 1100, 800}
    assert all(c.peer_median_ppm_krw == 1000 for c in cells)
    assert all(c.sigungu == "11680" for c in cells)
    # 직전 창도 채워진다 → 추세 = 0% (직전 창과 T 창의 ₩/㎡ 를 같게 만들었다)
    assert all(c.prior_price.available for c in cells)
    assert all(raw_price_trend(c) == pytest.approx(0.0) for c in cells)


def test_fold_metrics_match_hand_calculation():
    """★ 손계산 전부.

      수익률   c1 +10 · c2 +5 · c3 0 · c4 +10 · c5 −5
      B1(시장 중위) = median(+10,+5,0,+10,−5) = **+5.0** → 국면 rising
      가격매력 raw  = (1000 − own)/1000×100
                    c1 0 · c2 −20 · c3 +10 · c4 −10 · c5 +20
      백분위(n=5)   c5 90 · c3 70 · c1 50 · c4 30 · c2 10
      상위 2        = **c5, c3**
      상위 수익률   median(−5, 0)          = **−2.5**
      초과(B1 대비) median(−10, −5)        = **−7.5**
      적중률        둘 다 ≤ 0             = **0.0%**
      (동종 B2 는 피어가 같은 한 그룹이라 B1 과 같은 5.0 → 초과도 −7.5)
    """
    result = build_fold(single_axis_scorer(AXIS_PRICE_ATTRACTIVENESS))

    assert result.universe_size == 5 and result.scored_size == 5
    assert result.picked == (CellRef(5, BAND), CellRef(3, BAND))
    assert result.market_median_pct == pytest.approx(5.0)
    assert result.regime == REGIME_RISING
    assert result.top_median_ret_pct == pytest.approx(-2.5)
    assert result.top_median_excess_market_pct == pytest.approx(-7.5)
    assert result.top_median_excess_peer_pct == pytest.approx(-7.5)
    assert result.top_hit_rate_pct == pytest.approx(0.0)
    assert result.top_measured == 2
    assert result.top_measured_rate_pct == pytest.approx(100.0)
    assert result.universe_measured_rate_pct == pytest.approx(100.0)
    assert result.quotable is True


def test_null_control_percentile_matches_the_exact_distribution():
    """★ 무작위 대조군 — 분포를 손으로 다 적을 수 있는 크기로 만든다.

    초과수익(B1=+5 기준): c1 +5 · c2 0 · c3 −5 · c4 +5 · c5 −10
    2개 표본의 중위 = 두 값의 평균. 10가지 조합:
        (1,2) 2.5 · (1,3) 0 · (1,4) 5 · (1,5) −2.5 · (2,3) −2.5
        (2,4) 2.5 · (2,5) −5 · (3,4) 0 · (3,5) **−7.5** · (4,5) −2.5
    실제 상위 2(c5,c3)의 중위 = −7.5 → 이하인 조합은 **(3,5) 하나뿐 = 10%**.
    2000회 추출의 표준편차 ≈ √(0.1×0.9/2000) ≈ 0.67%p → 3σ 안에서 7~13%.
    """
    result = build_fold(single_axis_scorer(AXIS_PRICE_ATTRACTIVENESS),
                        null_draws=2000)
    assert result.null_percentile is not None
    assert 7.0 <= result.null_percentile <= 13.0
    # 같은 시드 → 같은 값. 인용할 수 없는 숫자를 리포트에 싣지 않기 위해.
    again = build_fold(single_axis_scorer(AXIS_PRICE_ATTRACTIVENESS), null_draws=2000)
    assert again.null_percentile == result.null_percentile


def test_null_control_with_full_universe_is_always_the_hundredth_percentile():
    """N = 유니버스 크기면 무작위 표본이 곧 전체다 → 중위가 같아 백분위 100.0.

    손계산: 전체 초과수익 median(+5, 0, −5, +5, −10) = **0.0**, 모든 추출도 0.0
    → `median <= actual` 이 100%.
    """
    result = build_fold(single_axis_scorer(AXIS_PRICE_ATTRACTIVENESS),
                        top_n=5, null_draws=50)
    assert result.top_median_excess_market_pct == pytest.approx(0.0)
    assert result.null_percentile == pytest.approx(100.0)


def test_run_backtest_composes_the_whole_pipeline():
    """`run_backtest` 이 build_cells → build_outcomes → run_fold → summarize 를 잇는다.

    폴드가 하나뿐이고 그 폴드가 상승기(B1=+5.0)이므로 판정은 **rising_only** 다 —
    "한 폴드라도 돌았으니 검증됐다"가 되지 않는 것이 §4-C 의 전부다.
    """
    from app.domain.backtest.engine import run_backtest

    report = run_backtest(universe_trades(), [SPEC],
                          scorer=single_axis_scorer(AXIS_PRICE_ATTRACTIVENESS),
                          households=HOUSEHOLDS, top_n=2, min_peer_cells=3,
                          null_draws=0)
    assert len(report.folds) == 1
    assert report.folds[0].picked == (CellRef(5, BAND), CellRef(3, BAND))
    assert report.folds[0].top_median_excess_market_pct == pytest.approx(-7.5)
    assert report.verdict == VERDICT_RISING_ONLY
    assert report.may_calibrate_weights is False


def test_fold_row_is_flat_and_carries_no_personal_data():
    row = fold_row(build_fold(constant_scorer()))
    assert row["as_of"] == "2025-01-31"
    assert row["horizon_months"] == 12
    assert set(row) >= {"universe_size", "top_measured_rate_pct",
                        "universe_measured_rate_pct", "null_percentile",
                        "quotable", "warnings"}
    assert not any(k in row for k in ("user_id", "email", "assets", "income"))


# ===========================================================================
# 8. 생존 편향 — 커버리지 경고
# ===========================================================================

def test_low_coverage_flags_the_fold_as_not_quotable():
    """상위 N 이 하나도 안 팔렸을 때. 손계산: 상위 2의 측정률 0% < 70% → 인용 불가.

    c5·c3 의 결과 창 거래를 지운다(그 둘이 가격매력 상위 2다).
    """
    trades = [t for t in universe_trades()
              if not (t.complex_id in (3, 5) and t.contract_date >= OUTCOME_START)]
    cells = build_cells(trades, spec=SPEC, households=HOUSEHOLDS, min_peer_cells=3)
    outcomes = build_outcomes(trades, cells, spec=SPEC)
    result = run_fold(spec=SPEC, cells=cells, outcomes=outcomes,
                      scorer=single_axis_scorer(AXIS_PRICE_ATTRACTIVENESS),
                      top_n=2, null_draws=0, min_peer_cells=3)

    assert result.picked == (CellRef(5, BAND), CellRef(3, BAND))
    assert result.top_measured == 0
    assert result.top_measured_rate_pct == pytest.approx(0.0)
    # 유니버스 5개 중 3개만 측정 → 60.0%
    assert result.universe_measured_rate_pct == pytest.approx(60.0)
    assert WARN_LOW_COVERAGE in result.warnings
    assert WARN_TOP_LESS_LIQUID in result.warnings
    assert result.quotable is False
    # DROP 정책에서는 미측정이 집계에 들어가지 않으므로 초과수익이 **없다**(0 이 아니다).
    assert result.top_median_excess_market_pct is None


def test_benchmark_policy_fills_unmeasured_with_zero_excess():
    """민감도 — 같은 상황에서 `BENCHMARK` 정책이면 초과가 정확히 0.0 이 된다.

    두 결론(값 없음 vs 0)이 다르다는 사실 자체가 §3-D 가 말하는 '갈리면 결론 없음'이다.
    """
    trades = [t for t in universe_trades()
              if not (t.complex_id in (3, 5) and t.contract_date >= OUTCOME_START)]
    cells = build_cells(trades, spec=SPEC, households=HOUSEHOLDS, min_peer_cells=3)
    outcomes = build_outcomes(trades, cells, spec=SPEC)
    result = run_fold(spec=SPEC, cells=cells, outcomes=outcomes,
                      scorer=single_axis_scorer(AXIS_PRICE_ATTRACTIVENESS),
                      top_n=2, null_draws=0, min_peer_cells=3,
                      unmeasured_policy=UnmeasuredPolicy.BENCHMARK)
    assert result.top_median_excess_market_pct == pytest.approx(0.0)
    assert result.top_measured == 0                      # 커버리지 사실은 그대로 남는다
    assert WARN_LOW_COVERAGE in result.warnings


# ===========================================================================
# 9. 빈 결과 — 없는 것을 지어내지 않는다
# ===========================================================================

def test_no_trades_yields_no_universe():
    assert build_cells([], spec=SPEC) == []
    assert build_outcomes([], [], spec=SPEC) == {}


def test_trades_below_min_sample_yield_no_universe():
    """4건이면 T 시점 가격이 서지 않는다 → 후보가 아니다(분모도 부풀지 않는다)."""
    assert build_cells(make_trades(1, WINDOW_START, 4, 1000.0), spec=SPEC) == []


def test_empty_fold_reports_every_missing_piece():
    result = run_fold(spec=SPEC, cells=[], outcomes={}, scorer=constant_scorer(),
                      top_n=30, null_draws=100)
    assert result.universe_size == 0 and result.scored_size == 0
    assert result.picked == ()
    assert result.market_median_pct is None
    assert result.regime == REGIME_UNKNOWN
    assert result.top_median_excess_market_pct is None
    assert result.top_measured_rate_pct is None
    assert result.quotable is False
    assert set(result.warnings) == {WARN_UNIVERSE_SMALLER_THAN_TOP_N,
                                    WARN_NO_MARKET_BENCHMARK,
                                    WARN_NO_PEER_BENCHMARK,
                                    WARN_NO_NULL_CONTROL}


def test_cells_without_area_are_dropped():
    """면적이 없으면 면적대를 못 정한다 — 셀이 성립하지 않는다."""
    broken = [BacktestTrade(complex_id=9, contract_date=WINDOW_START,
                            price_krw=100, area_m2=0.0) for _ in range(5)]
    assert build_cells(broken, spec=SPEC) == []


# ===========================================================================
# 10. 폴드 집계와 판정 — 하락기 없으면 '검증됨'이 아니다
# ===========================================================================

def fake_fold(regime_ret: float | None, *, measured: int = 30,
              warnings: tuple[str, ...] = ()) -> FoldResult:
    return FoldResult(spec=SPEC, scorer_name="current_weights",
                      unmeasured_policy=UnmeasuredPolicy.DROP, top_n=30,
                      universe_size=100, scored_size=100,
                      market_median_pct=regime_ret,
                      regime=classify_regime(regime_ret),
                      top_median_excess_market_pct=1.0,
                      top_median_excess_peer_pct=0.5,
                      top_measured=measured, top_measured_rate_pct=100.0,
                      warnings=warnings)


@pytest.mark.parametrize("value, expected", [
    (5.0, REGIME_RISING), (-5.0, REGIME_FALLING), (0.0, "flat"),
    (None, REGIME_UNKNOWN),
])
def test_regime_uses_only_the_sign(value, expected):
    """임계값을 지어내지 않는다 — 부호만 쓰고 실제 값을 항상 함께 낸다."""
    assert classify_regime(value) == expected


def test_no_folds_is_not_an_error_but_a_verdict():
    report = summarize([])
    assert report.verdict == VERDICT_NO_FOLDS
    assert report.may_calibrate_weights is False


def test_rising_only_blocks_the_verdict_and_the_calibration():
    """★ §4-C — 상승장에서는 아무거나 사도 오른다. 그 결과로 저울을 고치면 안 된다."""
    report = summarize([fake_fold(5.0), fake_fold(3.0), fake_fold(12.0)])
    assert report.verdict == VERDICT_RISING_ONLY
    assert report.may_calibrate_weights is False
    assert any("하락기" in n for n in report.notes)


def test_single_falling_fold_is_still_insufficient():
    report = summarize([fake_fold(-4.0)])
    assert report.verdict == VERDICT_INSUFFICIENT_FOLDS
    assert report.may_calibrate_weights is False


def test_measured_verdict_requires_a_falling_fold_and_two_folds():
    report = summarize([fake_fold(-4.0), fake_fold(6.0)])
    assert report.verdict == VERDICT_MEASURED
    assert report.regimes == (REGIME_FALLING, REGIME_RISING)
    assert report.quotable_folds == 2
    assert report.may_calibrate_weights is True
    # 집계는 폴드 동일가중 중위 — 둘 다 1.0 이므로 1.0.
    assert report.median_excess_market_pct == pytest.approx(1.0)
    assert report.median_excess_peer_pct == pytest.approx(0.5)
    assert any("독립이 아닙니다" in n for n in report.notes)


def test_low_coverage_folds_are_excluded_from_the_headline_number():
    """손계산: 인용 가능한 폴드는 하락 폴드 하나뿐 → 집계 중위 = 그 폴드 값(1.0)."""
    report = summarize([fake_fold(-4.0),
                        fake_fold(6.0, warnings=(WARN_LOW_COVERAGE,))])
    assert report.quotable_folds == 1
    assert report.median_excess_market_pct == pytest.approx(1.0)
    assert any("커버리지 미달" in n for n in report.notes)
    assert report.may_calibrate_weights is False        # 인용 가능 폴드가 2개 미만


def test_every_report_says_the_static_axes_are_excluded():
    """총점의 55%가 채점 대상 밖이라는 사실이 **모든** 리포트에 붙어야 한다."""
    for report in (summarize([]), summarize([fake_fold(-1.0), fake_fold(1.0)])):
        assert any("55%" in n for n in report.notes)


# ===========================================================================
# 11. 계층 경계 — 도메인은 SQL 을 모른다
# ===========================================================================

def test_in_memory_repository_satisfies_the_protocol():
    repo = InMemoryBacktestRepository(universe_trades(), HOUSEHOLDS)
    assert isinstance(repo, BacktestTradeRepository)
    rows = list(repo.trades_for_backtest(start=dt.date(2024, 1, 1),
                                         end=dt.date(2024, 12, 31)))
    assert rows and all(r.contract_date.year == 2024 for r in rows)
    assert repo.household_counts([1, 99]) == {1: 500, 99: None}


def test_repository_does_not_pre_filter_cancelled_trades():
    """리포지토리가 미리 거르면 `INCLUDE_ALL` 정책이 조용히 무력화된다."""
    cancelled = BacktestTrade(complex_id=1, contract_date=dt.date(2024, 6, 1),
                              price_krw=100, area_m2=AREA, is_cancelled=True)
    repo = InMemoryBacktestRepository([cancelled])
    rows = list(repo.trades_for_backtest(start=dt.date(2024, 1, 1),
                                         end=dt.date(2024, 12, 31)))
    assert rows == [cancelled]


#: 쓰기 SQL 토큰. 이 스크립트·도메인에 **있으면 안 된다**.
WRITE_SQL_TOKENS = ("INSERT ", "UPDATE ", "DELETE ", "TRUNCATE", "DROP ", "ALTER ")


def _module_facts(path) -> tuple[set[str], list[str]]:
    """(임포트한 최상위 모듈, **독스트링이 아닌** 문자열 상수들).

    ⚠️ 왜 AST 인가 — 예전 판은 소스를 정규식으로 훑었고, 그러면 **설명하는 산문**이
       걸린다(이 저장소의 코드는 주석에 SQL 을 자주 인용한다). 실제로 `asof.py` 의
       "적재 SQL 의 INSERT 컬럼 목록에 이름이 없다"는 문장 때문에 검사가 빨개졌다.
       "산문에 SQL 을 적는 것"과 "SQL 을 쓰는 것"은 다른 일이다.
    """
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    doc_ids: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            doc_ids.add(id(first.value))

    modules: set[str] = set()
    literals: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in doc_ids):
            literals.append(node.value)
    return modules, literals


def test_backtest_domain_contains_no_sql_or_engine():
    """★ 계층 위반을 정적으로 막는다 — 도메인에 SQL 이 스며드는 순간 순수성이 끝난다."""
    from pathlib import Path

    package = Path(__file__).resolve().parents[1] / "app" / "domain" / "backtest"
    files = sorted(package.glob("*.py"))
    assert len(files) >= 6, f"검사 범위가 비었습니다: {files}"   # 범위가 조용히 줄지 않게

    offenders: list[str] = []
    for path in files:
        modules, literals = _module_facts(path)
        for banned in ("sqlalchemy", "psycopg", "sqlite3", "asyncpg"):
            if banned in modules:
                offenders.append(f"{path.name}: import {banned}")
        for text in literals:
            for token in ("SELECT ", *WRITE_SQL_TOKENS):
                if token in text.upper():
                    offenders.append(f"{path.name}: SQL 리터럴 {token!r}")
    assert not offenders, (
        "백테스트 도메인은 SQL·엔진을 몰라야 합니다(backtest.md §5-1): " + str(offenders))


def _runner_path():
    """실행기 스크립트 경로. DB 에 닿지 않는다."""
    from pathlib import Path

    return Path(__file__).resolve().parents[1] / "scripts" / "run_backtest.py"


def _load_runner():
    """`scripts/run_backtest.py` 를 모듈로 읽는다(import 만 — 엔진에 닿지 않는다)."""
    import importlib.util
    import sys

    scripts_dir = _runner_path().parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    spec = importlib.util.spec_from_file_location("_t_run_backtest", _runner_path())
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_runner_script_implements_the_repository_protocol():
    """실행기의 운영 리포지토리가 실제로 같은 계약을 만족하는지.

    Protocol 은 선언만으로는 아무것도 강제하지 않는다 — 구현이 어긋나도
    import 는 성공한다. 그래서 여기서 확인한다(엔진에 닿지 않는다).
    """
    scripts_dir = _runner_path().parent
    module = _load_runner()

    repo = module.PostgresBacktestRepository(engine=None)
    assert isinstance(repo, BacktestTradeRepository)

    # 스크립트는 **읽기 전용**이다. 쓰기 SQL 이 생기면 여기서 잡힌다.
    # (산문이 아니라 실제 문자열 리터럴만 본다 — `_module_facts` 주석 참조.)
    _, literals = _module_facts(scripts_dir / "run_backtest.py")
    sql_like = [t for t in literals if "SELECT" in t.upper()]
    assert sql_like, "SELECT 문이 하나도 없습니다 — 검사 대상을 잘못 잡았습니다"
    for text in literals:
        for token in WRITE_SQL_TOKENS:
            assert token not in text.upper(), (
                f"백테스트 실행기에 쓰기 SQL 이 있습니다: {token!r}")


def test_fold_spec_knows_what_data_it_needs():
    """스크립트가 데이터 유무를 먼저 보게 한다.

    손계산 (T=2025-01-31 · W=H=12 · 지연 30일):
      상한 = cutoff(2026-01-31)              = **2026-01-01**
      하한 = cutoff(2024-01-31) − 12개월     = 2024-01-01 − 12개월 = **2023-01-01**
    """
    start, end = SPEC.required_contract_range(report_lag_days=REPORT_LAG_DAYS)
    assert start == dt.date(2023, 1, 1)
    assert end == dt.date(2026, 1, 1)
    assert SPEC.outcome_as_of == dt.date(2026, 1, 31)
    assert SPEC.prior_as_of == dt.date(2024, 1, 31)

    # 추세 축을 빼면 창이 하나 덜 필요하다: cutoff(2025-01-31) − 12개월 = **2024-01-01**.
    # 이 12개월 차이가 백필 계획을 가른다 — 2021-01 백필로는 하락기 폴드(T=2022-01)의
    # 직전 창(2020-01~)이 비어 가격추세 축이 통째로 빠진다(backtest.md §4-D).
    minimal_start, minimal_end = SPEC.required_contract_range(
        report_lag_days=REPORT_LAG_DAYS, include_prior=False)
    assert minimal_start == dt.date(2024, 1, 1)
    assert minimal_end == end
    assert add_months(minimal_start, -SPEC.window_months) == start


def test_falling_regime_folds_need_one_more_year_than_the_running_backfill():
    """★ 백필 계획의 근거를 코드에 고정한다(backtest.md §4-D).

    손계산 — F1(T=2022-01-31, W=H=12, 지연 30일):
      추세 제외 → cutoff(2022-01-31)=2022-01-01, −12개월 = **2021-01-01** (백필 범위 안)
      추세 포함 → cutoff(2021-01-31)=2021-01-01, −12개월 = **2020-01-01** (범위 **밖**)
    즉 지금 도는 2021-01 백필로는 **하락기 폴드에서만 하필 가격추세 축이 빠진다.**
    """
    f1 = FoldSpec(as_of=dt.date(2022, 1, 31))
    with_trend, _ = f1.required_contract_range(report_lag_days=REPORT_LAG_DAYS)
    without_trend, _ = f1.required_contract_range(report_lag_days=REPORT_LAG_DAYS,
                                                  include_prior=False)
    assert with_trend == dt.date(2020, 1, 1)
    assert without_trend == dt.date(2021, 1, 1)


def test_fold_spec_rejects_nonsense():
    with pytest.raises(ValueError):
        FoldSpec(as_of=T, horizon_months=0)
    with pytest.raises(ValueError):
        FoldSpec(as_of=T, window_months=-1)


def test_benchmark_dataclass_is_frozen_so_results_cannot_be_edited_after_the_fact():
    """채점표를 나중에 손대지 못하게. (자기 채점 도구에서 이건 형식이 아니라 원칙이다.)"""
    bench = Benchmark(market_median_pct=1.0, peer_median_pct={}, peer_size={},
                      universe_size=1, measured_size=1)
    with pytest.raises(Exception):
        bench.market_median_pct = 99.0        # type: ignore[misc]


# ===========================================================================
# 12. ★ 메모리 상한 — 실행기가 전 구간을 손에 쥐지 못하게 (CR49-3)
#
# 실측 근거(2026-08-05): `trade` 1,076,262행 · 문서 §8 첫 실행 범위만 613,228행 ·
# 1행 383B → **235MB**, 서버 가용 261MB. 즉 "조심해서 쓰면 된다"가 대책이 될 수 없다.
# 여기서는 상한이 **실제로 지켜지는지** 살아 있는 객체 수를 세어 확인한다.
#
# ⚠️ CR50-1 — 이 절의 옛 판은 **두 군데가 동시에 공허**했다:
#   ① 픽스처가 `apt_dong`·`registered_at` 을 안 심어 **마스킹 경로를 한 번도 안 지났다**
#      (CR49-6 이 `apt_dong` 가드에서 지적한 사각지대가 메모리 검사에서 그대로 재발).
#   ② 카운터가 스트림이 만든 **원본에만** `finalize` 를 걸어, as-of 뷰가 만드는
#      `dataclasses.replace()` **사본을 한 개도 세지 못했다.**
# 둘이 겹쳐서 "순간 보유 ≤ chunk_rows" 를 단언했는데, 운영 모양(동 보유율 77~93%)에서는
# 실제로 **2배**다. 지금은 픽스처가 마스킹을 지나고, 카운터가 사본까지 센다.
# ===========================================================================

class LiveTradeCounter:
    """살아 있는 `BacktestTrade` 수를 **실제로** 센다 — 주석이 아니라 측정이다.

    `weakref.finalize` 는 마지막 참조가 사라지는 순간 불린다(CPython 참조계수).
    `BacktestTrade` 는 순환 참조가 없으므로 GC 세대를 기다리지 않는다.

    `made` 는 **원본 + 사본** 전부, `sourced` 는 스트림이 만든 원본만이다.
    둘이 같으면 마스킹을 안 지났다는 뜻이라 검사가 공허해진다 → `copies > 0` 로 단언한다.
    """

    def __init__(self) -> None:
        self.live = 0
        self.peak = 0
        self.made = 0
        self.sourced = 0

    def track(self, trade: BacktestTrade) -> BacktestTrade:
        self.live += 1
        self.made += 1
        self.peak = max(self.peak, self.live)
        weakref.finalize(trade, self._released)
        return trade

    def _released(self) -> None:
        self.live -= 1

    @property
    def copies(self) -> int:
        """as-of 뷰가 만든 `dataclasses.replace()` 사본 수."""
        return self.made - self.sourced


class _TrackedTrade(BacktestTrade):
    """카운터가 **사본까지** 셀 수 있게 하는 하위형.

    `dataclasses.replace(obj, ...)` 는 `obj.__class__(**changes)` 를 부른다 —
    그래서 원본이 이 형이면 `asof.as_of_trades` 가 만드는 마스킹 사본도 이 형이 되고,
    카운터의 눈을 피할 수 없다. 옛 판은 스트림 안에서 `counter.track(...)` 을 부르는
    구조라 **사본에는 손이 닿지 않았다**(CR50-1).

    카운터를 클래스 변수로 두는 이유: `BacktestTrade` 가 얼린(frozen) 데이터클래스라
    인스턴스에 아무것도 붙일 수 없다.
    """

    counter: LiveTradeCounter | None = None

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if _TrackedTrade.counter is not None:
            _TrackedTrade.counter.track(self)


@contextlib.contextmanager
def tracking():
    """이 블록 안에서 만들어지는 모든 `_TrackedTrade`(사본 포함)를 센다."""
    counter = LiveTradeCounter()
    previous, _TrackedTrade.counter = _TrackedTrade.counter, counter
    try:
        yield counter
    finally:
        _TrackedTrade.counter = previous


#: 세 창을 골고루 덮는 계약일. (2023-01-01, 2026-01-01] 안에서 하루씩 민다 →
#: 각 거래는 직전 창·T 창·결과 창 **정확히 하나**에 든다(창이 서로 겹치지 않는다).
STREAM_FIRST_DAY = dt.date(2023, 2, 1)

#: ★ **운영 모양**으로 만든다. `apt_dong` 이 차 있고 등기가 T 이후면 as-of 뷰가
#: `replace()` 사본을 만든다(`asof.py` ③ — 그 시점엔 동을 몰랐다). 운영 `apt_dong`
#: 보유율은 77~93%(erd §0)라 **운영 경로는 사실상 전부 이 모양**이다.
STREAM_APT_DONG = "101"
#: 어떤 폴드의 T·T+H 보다도 뒤 → 이 픽스처의 모든 행이 항상 마스킹된다(사본이 된다).
STREAM_REGISTERED_AT = dt.date(2030, 1, 1)


def tracked_stream(counter: LiveTradeCounter, *, rows: int,
                   complexes: int = 400):
    """제너레이터. **리스트로 만들지 않는다** — 소비자가 접으면 그게 잡히도록."""
    for i in range(rows):
        counter.sourced += 1
        yield _TrackedTrade(
            complex_id=i % complexes,
            contract_date=STREAM_FIRST_DAY + dt.timedelta(days=i % 1000),
            price_krw=int(1000.0 * AREA), area_m2=AREA, region_code=REGION_A,
            registered_at=STREAM_REGISTERED_AT, apt_dong=STREAM_APT_DONG)


class TestStreamingMemoryBound:

    ROWS = 20_000
    CHUNK = 250

    def test_collector_never_holds_more_than_two_chunks_of_rows(self):
        """★ 순간 보유 행 수가 상한 안에 머문다. **상한은 `2 × chunk_rows` 다.**

        손계산 — 살아 있는 것은 (청크 하나) + (그 청크의 as-of 뷰 하나)뿐이다.
        뷰는 원본을 가리킬 수도, `replace()` 사본일 수도 있는데 **운영 모양에서는
        거의 전부 사본**이다(동 마스킹). 이 픽스처는 그 모양으로 만들었으므로
        결과 창 뷰(cutoff 2026-01-01 — 모든 행이 통과)에서 정확히 250 + 250 = **500**.

        변이 시험:
          · `feed` 의 `islice(source, chunk_rows)` → `list(source)` : peak 20,000 → 죽는다
          · `asof.py` 의 `apt_dong` 마스킹 제거: `copies == 0` → 죽는다(픽스처가 공허해진다)
        """
        with tracking() as counter:
            collector = FoldCollector([SPEC], min_peer_cells=3, chunk_rows=self.CHUNK)
            collector.feed(tracked_stream(counter, rows=self.ROWS))

        assert counter.sourced == self.ROWS       # 전부 흘러갔다(검사가 공허하지 않다)
        assert collector.rows_seen == self.ROWS
        assert collector.peak_chunk_rows == self.CHUNK
        # ★ 픽스처가 **마스킹 경로를 지났다**. 이 단언이 없으면 위·아래가 전부 공허하다.
        assert counter.copies > 0, (
            "as-of 뷰가 사본을 하나도 안 만들었습니다 — 픽스처가 마스킹 경로를 "
            "지나지 않습니다(그러면 메모리 상한을 운영 모양에서 재지 못합니다 · CR50-1).")
        # 코드가 스스로 잰 값(로그·운영에서도 이 값이 찍힌다).
        assert collector.peak_live_rows == 2 * self.CHUNK
        # 바깥에서 잰 값 — 청크 + 뷰 + 제너레이터가 붙들고 있는 한둘.
        assert counter.peak <= 2 * self.CHUNK + 8, (
            f"순간 보유 행이 {counter.peak}개 — 상한 {2 * self.CHUNK}개를 넘었습니다. "
            "거래 스트림을 어딘가에서 통째로 붙들고 있습니다(CR49-3).")
        # 그리고 수집기는 **행이 아니라 값**을 남긴다: 창 셋이 겹치지 않으므로
        # 거래 하나당 표본 정확히 하나다(8바이트 double).
        assert collector.samples == self.ROWS

    def test_feed_leaves_no_row_alive_afterwards(self):
        """수집이 끝나면 거래 객체는 **한 개도** 남지 않는다 — 집계는 값만 들고 있다.

        사본까지 포함해서다(카운터가 사본도 센다).
        """
        with tracking() as counter:
            collector = FoldCollector([SPEC], min_peer_cells=3, chunk_rows=self.CHUNK)
            collector.feed(tracked_stream(counter, rows=2_000))
        assert counter.copies > 0
        assert counter.live == 0

    def test_many_folds_do_not_increase_the_row_bound(self):
        """폴드를 늘려도 **행** 보유량은 그대로다(느는 것은 값 통뿐).

        이것이 '폴드마다 다시 조회'(안 ①) 대신 '한 번 순회'(안 ②)를 고른 이유다 —
        폴드 하나짜리 범위가 이미 235MB 였으므로 창을 좁히는 것만으로는 못 막는다.
        폴드가 셋이면 as-of 뷰도 여섯 개지만 **한 번에 하나씩** 만들고 버리므로 상한은 같다.
        """
        specs = [SPEC,
                 FoldSpec(as_of=dt.date(2024, 7, 31)),
                 FoldSpec(as_of=dt.date(2025, 7, 31))]
        with tracking() as counter:
            collector = FoldCollector(specs, min_peer_cells=3, chunk_rows=self.CHUNK)
            collector.feed(tracked_stream(counter, rows=self.ROWS))
        assert counter.copies > 0
        assert collector.peak_live_rows == 2 * self.CHUNK
        assert counter.peak <= 2 * self.CHUNK + 8
        assert counter.live == 0

    def test_collector_refuses_to_swallow_more_samples_than_the_cap(self):
        """★ 상한을 코드가 스스로 지킨다 — 넘으면 **멈춘다**(조용히 스왑으로 흐르지 않는다).

        변이 시험: `_feed_chunk` 의 `SampleLimitExceeded` 를 지우면 이 검사가 죽는다.

        손계산(CR50-7 — 옛 단언 `<= 350` / `<= 400` 은 "청크 두 개마다 검사"로 바꿔도
        통과했다): 청크 100행 · 상한 250. 창 셋이 겹치지 않아 **행 하나당 표본 하나**이므로
        누적은 100 → 200 → 300 이고, 세 번째 청크를 다 넣은 직후 300 > 250 으로 죽는다.
        따라서 **정확히 300 / 300**이다.
        """
        with tracking() as counter:
            collector = FoldCollector([SPEC], min_peer_cells=3, chunk_rows=100,
                                      max_samples=250)
            with pytest.raises(SampleLimitExceeded, match="상한"):
                collector.feed(tracked_stream(counter, rows=5_000))
        # 상한 근처에서 멈췄다 — 끝까지 다 읽고 나서 우는 게 아니다.
        assert collector.samples == 300
        assert collector.rows_seen == 300

    def test_default_bounds_are_the_ones_the_document_justifies(self):
        """기본값이 조용히 바뀌면 §7-13 의 계산이 거짓이 된다."""
        assert DEFAULT_CHUNK_ROWS == 5_000            # ≈ 1.9MB (383B × 5,000)
        assert DEFAULT_MAX_SAMPLES == 2_000_000       # ≈ 값 16MB + 버킷 부대비용

    @pytest.mark.parametrize("chunk_rows", [1, 2, 7, 10_000])
    def test_chunk_size_does_not_change_the_result(self, chunk_rows):
        """청크 경계가 결과에 새면 상한을 조절할 수 없게 된다.

        손계산은 `test_fold_metrics_match_hand_calculation` 과 같다 — 상위 2 = (c5, c3).
        """
        trades = universe_trades()
        cells = build_cells(trades, spec=SPEC, households=HOUSEHOLDS, min_peer_cells=3,
                            chunk_rows=chunk_rows)
        assert [c.ref for c in cells] == [CellRef(i, BAND) for i in (1, 2, 3, 4, 5)]
        assert {c.price.median_ppm_krw for c in cells} == {1000, 1200, 900, 1100, 800}
        assert all(c.peer_median_ppm_krw == 1000 for c in cells)
        outcomes = build_outcomes(trades, cells, spec=SPEC, chunk_rows=chunk_rows)
        result = run_fold(spec=SPEC, cells=cells, outcomes=outcomes,
                          scorer=single_axis_scorer(AXIS_PRICE_ATTRACTIVENESS),
                          top_n=2, null_draws=0, min_peer_cells=3)
        assert result.picked == (CellRef(5, BAND), CellRef(3, BAND))
        assert result.top_median_excess_market_pct == pytest.approx(-7.5)

    def test_one_pass_over_many_folds_matches_the_per_fold_path(self):
        """실행기가 쓰는 '한 번 순회' 경로가 `build_cells`/`build_outcomes` 와 같은 답인가.

        같지 않으면 우리가 채점하는 대상이 두 개가 된다.
        """
        specs = [SPEC, FoldSpec(as_of=dt.date(2024, 7, 31))]
        trades = universe_trades()

        collector = FoldCollector(specs, min_peer_cells=3)
        collector.feed(iter(trades))
        assert collector.complex_ids == {1, 2, 3, 4, 5}

        for spec in specs:
            expected_cells = build_cells(trades, spec=spec, households=HOUSEHOLDS,
                                         min_peer_cells=3)
            actual_cells = collector.cells(spec, households=HOUSEHOLDS)
            assert actual_cells == expected_cells
            assert (collector.outcomes(spec, actual_cells)
                    == build_outcomes(trades, expected_cells, spec=spec))

    def test_collector_rejects_a_fold_it_never_collected(self):
        """모르는 폴드를 물으면 **빈 결과를 지어내지 않고** 멈춘다."""
        collector = FoldCollector([SPEC], min_peer_cells=3)
        collector.feed(iter(universe_trades()))
        with pytest.raises(ValueError, match="모르는 폴드"):
            collector.cells(FoldSpec(as_of=dt.date(2021, 1, 31)))


# ===========================================================================
# 12-B. ★ "두 번째 순회에 조용히 0행" 함정 — 구조적으로 불가능하게 (CR50-3)
#
# 이 함정은 세 모양으로 살아 있었고 **셋 다 예외 없이 조용했다**:
#   ① `build_cells(gen)` → `build_outcomes(gen)` : 두 번째가 0행 → `measured 0/N`,
#      경고 4개가 붙지만 **리포트는 나온다**(리뷰어가 직접 재현).
#   ② `feed` 재호출 : `rows_seen`·`sample_size` 가 **두 배**. 그 표본 수는 환금성 축의 분자다.
#   ③ 같은 `FoldSpec` 두 번 : 뒤 창은 채워지되 안 읽히고 `max_samples` 만 먹는다.
# "운영 경로엔 없다"는 대책이 아니다 — 다음 사람이 그 경로를 만든다. 그래서 예외로 막는다.
# ===========================================================================

class TestAbortedCollectorYieldsNothing:
    """⛔ CR51-1 — 상한에 걸려 **중단된** 수집이 부분 결과를 조용히 내면 안 된다.

    리뷰어 재현: 정상 5셀짜리 원천을 `max_samples=40` 으로 먹이면 예외가 나는데,
    그 예외를 잡고 `cells()` 를 물으면 **3셀이 measured 로** 나왔다(경고 0).
    `60` 이면 5셀인데 `outcomes` 는 **4/5**. "덜 본 것"이 "없는 것"과 같아 보인다 —
    이 저장소가 반복해 고쳐 온 바로 그 형태다.

    변이 시험: `_feed_chunk` 의 `self._aborted = True` 를 지우면 이 검사가 죽는다.
    """

    def test_상한초과후_산출을_물으면_거부한다(self):
        collector = FoldCollector([SPEC], min_peer_cells=3, chunk_rows=100,
                                  max_samples=250)
        with tracking() as counter:
            with pytest.raises(SampleLimitExceeded, match="상한"):
                collector.feed(tracked_stream(counter, rows=5_000))
        # ★ 여기가 핵심 — 예외를 **잡은 뒤에도** 산출은 못 얻는다.
        with pytest.raises(SampleLimitExceeded, match="부분 결과"):
            collector.cells(SPEC)
        with pytest.raises(SampleLimitExceeded, match="부분 결과"):
            collector.outcomes(SPEC, {})

    def test_상한에_안_걸리면_평소대로_낸다(self):
        """대조군 — 이 가드가 정상 경로를 막으면 그게 더 나쁘다."""
        collector = FoldCollector([SPEC], min_peer_cells=3, chunk_rows=100,
                                  max_samples=None)
        with tracking() as counter:
            collector.feed(tracked_stream(counter, rows=300))
        cells = collector.cells(SPEC)   # 예외가 안 나야 한다
        collector.outcomes(SPEC, cells)


class TestSecondPassTrap:

    def test_the_exact_reproduction_now_raises_instead_of_reporting_zero(self):
        """★ 리뷰어가 재현한 그 코드. 예전엔 `measured 0/5` 로 **조용히** 끝났다."""
        gen = iter(universe_trades())          # ← list_iterator: 한 번 쓰면 빈다
        with pytest.raises(TypeError, match="다시 훑을 수 있는"):
            build_cells(gen, spec=SPEC, households=HOUSEHOLDS, min_peer_cells=3)

    def test_the_same_guard_covers_generators_and_the_outcome_half(self):
        """제너레이터도, 짝의 나머지 반쪽도 같이 막힌다."""
        cells = build_cells(universe_trades(), spec=SPEC, households=HOUSEHOLDS,
                            min_peer_cells=3)
        assert len(cells) == 5                                  # 정상 경로는 그대로
        with pytest.raises(TypeError, match="다시 훑을 수 있는"):
            build_outcomes((t for t in universe_trades()), cells, spec=SPEC)

    def test_a_list_is_still_accepted_twice(self):
        """⚠️ 가드가 정상 경로를 막지 않는다 — 리스트는 `iter()` 가 매번 새 커서를 준다."""
        trades = universe_trades()
        cells = build_cells(trades, spec=SPEC, households=HOUSEHOLDS, min_peer_cells=3)
        outcomes = build_outcomes(trades, cells, spec=SPEC)
        assert sum(1 for o in outcomes.values() if o.measured) == 5

    def test_feeding_twice_raises_instead_of_silently_doubling(self):
        """★ 예전엔 `rows_seen` 75→150 · `sample_size` 5→10 으로 **조용히 두 배**였다."""
        collector = FoldCollector([SPEC], min_peer_cells=3)
        collector.feed(universe_trades())
        before = (collector.rows_seen, collector.samples)
        with pytest.raises(StreamAlreadyConsumed, match="한 번만"):
            collector.feed(universe_trades())
        assert (collector.rows_seen, collector.samples) == before   # 두 배가 안 됐다
        # 그리고 환금성 축의 분자가 온전하다 — 셀당 창 안 거래 5건(픽스처 그대로).
        assert {c.window_trade_count for c in collector.cells(SPEC)} == {5}

    def test_two_collectors_cannot_share_one_generator(self):
        """소진된 제너레이터를 다른 수집기에 넘기면 멈춘다(조용히 0행이 아니다)."""
        stream = (t for t in universe_trades())
        FoldCollector([SPEC], min_peer_cells=3).feed(stream)
        with pytest.raises(StreamAlreadyConsumed, match="이미 다른 수집기"):
            FoldCollector([SPEC], min_peer_cells=3).feed(stream)

    def test_duplicate_folds_are_rejected(self):
        """같은 폴드를 두 번 주면 뒤 창은 채워지되 안 읽힌다 — 만들지 못하게 한다."""
        with pytest.raises(ValueError, match="같은 폴드가 두 번"):
            FoldCollector([SPEC, FoldSpec(as_of=dt.date(2024, 7, 31)), SPEC])

    def test_outputs_before_feed_do_not_invent_an_empty_universe(self):
        """`feed` 를 잊으면 빈 유니버스가 아니라 예외다 — 빈 결과는 '데이터 없음'으로 읽힌다."""
        collector = FoldCollector([SPEC], min_peer_cells=3)
        with pytest.raises(RuntimeError, match="feed"):
            collector.cells(SPEC)
        with pytest.raises(RuntimeError, match="feed"):
            collector.outcomes(SPEC, [])


def test_runner_never_materialises_the_trade_stream():
    """★ CR49-3 회귀 방지 — `list(repo.trades_for_backtest(...))` 가 돌아오면 붉어진다.

    실행기는 리포지토리가 약속한 스트리밍을 **소비 쪽에서** 무효로 만들 수 있는
    유일한 자리다. 그 한 줄이 서버 가용 메모리의 90%를 먹었다.
    """
    import ast

    tree = ast.parse(_runner_path().read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name not in ("list", "tuple", "set", "sorted", "frozenset"):
            continue
        for arg in node.args:
            inner = getattr(arg, "func", None)
            if getattr(inner, "attr", None) == "trades_for_backtest":
                offenders.append(f"{name}(...trades_for_backtest...) 줄 {node.lineno}")
    assert not offenders, (
        "거래 스트림을 통째로 메모리에 올립니다(CR49-3) — "
        f"{offenders}. FoldCollector.feed 로 넘기세요.")


def test_runner_forces_read_only_at_the_database_not_just_in_a_lint():
    """★ SR45-6 — '읽기 전용'이 정적 토큰 검사뿐이면 우회가 조용히 통과한다.

    순서까지 본다: `SET default_transaction_read_only` 는 **다음 트랜잭션**부터라
    그것만으로는 지금 도는 트랜잭션을 못 막는다. `SET TRANSACTION READ ONLY` 가
    첫 질의 앞에 와야 한다.
    """
    module = _load_runner()
    guards = list(module.SESSION_GUARDS)
    assert guards[0].upper().startswith("SET TRANSACTION READ ONLY"), guards
    assert any("default_transaction_read_only" in g for g in guards), guards


# ===========================================================================
# 13-B. ★ 세션 가드의 **전제**와 드라이버 버퍼 (CR50-6 · CR50-2)
#
# 위 검사는 상수 튜플의 순서만 본다. 그 순서가 통하는 **전제**(트랜잭션 안일 것)를
# 아무도 안 봤고, 드라이버가 시군구 하나치를 통째로 버퍼하는 것도 아무도 안 봤다.
# 여기서는 가짜 연결로 실제 호출을 받아 본다 — DB 에 닿지 않는다.
# ===========================================================================

class _FakeResult:
    def __init__(self, scalar=None, rows=()):
        self._scalar = scalar
        self._rows = list(rows)

    def scalar(self):
        return self._scalar

    def all(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _FakeConn:
    """`Connection` 흉내. **무엇을 물었고 어떤 실행옵션을 줬는지** 기록한다."""

    def __init__(self, *, options=None, read_only="on", rows=()):
        self._options = dict(options or {})
        self._read_only = read_only
        self._rows = list(rows)
        self.statements: list[str] = []
        self.exec_options: list[dict] = []
        self.engine = self                      # engine.get_execution_options 용

    def get_execution_options(self):
        return dict(self._options)

    def execute(self, statement, parameters=None, *, execution_options=None):
        sql = str(statement)
        self.statements.append(sql)
        if execution_options:
            self.exec_options.append(dict(execution_options))
        if sql.strip().upper().startswith("SHOW TRANSACTION_READ_ONLY"):
            return _FakeResult(scalar=self._read_only)
        return _FakeResult(rows=self._rows)

    # `with engine.connect() as conn:` 흉내
    def connect(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_read_only_guard_checks_its_own_premise_and_refuses_autocommit():
    """★ CR50-6 — `SET TRANSACTION READ ONLY` 는 트랜잭션 블록 안에서만 뜻이 있다.

    AUTOCOMMIT 이면 첫 가드가 **조용히 무효**가 되는데, 상수 튜플 순서만 보는 검사는
    그대로 초록이다. 그래서 전제를 실행 시점에 단언한다.
    """
    module = _load_runner()

    # ① 정상 — 트랜잭션 연결. 가드를 순서대로 걸고, 마지막에 DB 에 되묻는다.
    conn = _FakeConn()
    module.apply_session_guards(conn)
    assert conn.statements[:len(module.SESSION_GUARDS)] == list(module.SESSION_GUARDS)
    assert conn.statements[-1] == module.READ_ONLY_PROBE

    # ② AUTOCOMMIT — 거부한다. **가드를 걸어 보지도 않는다**(전제가 깨졌으므로).
    auto = _FakeConn(options={"isolation_level": "AUTOCOMMIT"})
    with pytest.raises(RuntimeError, match="AUTOCOMMIT"):
        module.apply_session_guards(auto)
    assert auto.statements == []

    # ③ 전제가 어떤 이유로든 깨져 DB 가 'off' 라 답하면 멈춘다(철자가 아니라 효과를 본다).
    off = _FakeConn(read_only="off")
    with pytest.raises(RuntimeError, match="transaction_read_only=off"):
        module.apply_session_guards(off)


def test_runner_streams_trades_from_the_database_instead_of_buffering_a_sigungu():
    """★ CR50-2 — `chunk_rows` 는 **도메인 객체**의 상한일 뿐이다.

    `stream_results` 가 없으면 psycopg 가 클라이언트 커서를 써서 `execute()` 가
    돌아오는 순간 **그 질의 결과 전부**(= 시군구 하나치)가 클라이언트 메모리에 있다.
    질의는 시군구 단위이므로 실제 상한이 "가장 큰 시군구의 행 수"가 돼 버린다.
    """
    module = _load_runner()
    conn = _FakeConn()
    repo = module.PostgresBacktestRepository(conn, pause_sec=0.0, stream_rows=250)

    rows = list(repo.trades_for_backtest(start=dt.date(2024, 1, 1),
                                         end=dt.date(2025, 1, 1),
                                         region_codes=["11680"]))
    assert rows == []                       # 가짜 연결이라 행은 없다 — 보는 것은 옵션이다
    assert conn.exec_options == [{"stream_results": True, "max_row_buffer": 250}], (
        "거래 질의에 stream_results 가 없습니다 — 드라이버가 시군구 하나치를 "
        "통째로 버퍼합니다(CR50-2).")


def test_stream_buffer_follows_chunk_rows_so_there_is_only_one_bound():
    """드라이버 버퍼와 수집기 청크가 **같은 숫자**여야 '상한'이 하나로 읽힌다."""
    module = _load_runner()
    default_repo = module.PostgresBacktestRepository(engine=None)
    assert default_repo._stream_rows == DEFAULT_CHUNK_ROWS
    # 실행기가 `--chunk-rows` 를 리포지토리까지 내려보내는지 (소스로 확인 — DB 무접촉).
    source = _runner_path().read_text(encoding="utf-8")
    assert "stream_rows=chunk_rows" in source, (
        "--chunk-rows 가 드라이버 버퍼에 반영되지 않습니다 — 상한이 두 개가 됩니다.")


def test_report_payload_says_which_cancellation_policy_made_it():
    """★ CR49-4 — 상·하한 두 번 돌린 산출물이 **파일 내용으로 구별**되어야 한다.

    `--cancellation` 도움말이 직접 "두 번 돌려 범위로 보고하라"고 지시한다.
    그런데 예전 payload 에는 그 정책이 없어서, 두 파일이 서로 어느 끝인지 말하지 못했다.
    """
    module = _load_runner()
    report = summarize([fake_fold(-4.0), fake_fold(6.0)])

    def payload_for(policy: CancellationPolicy) -> dict:
        params = module.run_params(
            folds=[T], scorer_name="current_weights", top_n=30, horizon_months=12,
            window_months=12, min_trades=5, min_peer_cells=10, policy=policy,
            unmeasured=UnmeasuredPolicy.DROP, null_draws=1000, seed=1,
            chunk_rows=DEFAULT_CHUNK_ROWS, max_samples=DEFAULT_MAX_SAMPLES)
        return module.report_payload(report, params)

    low = payload_for(CancellationPolicy.EXCLUDE_FINAL)
    high = payload_for(CancellationPolicy.INCLUDE_ALL)

    assert low["params"]["cancellation"] == "exclude_final"
    assert high["params"]["cancellation"] == "include_all"
    assert low != high, "두 해제 정책의 산출물이 내용만으로 구별되지 않습니다(CR49-4)"
    # 재현에 필요한 나머지도 함께 실린다.
    assert set(low["params"]) >= {"min_trades", "min_peer_cells", "report_lag_days",
                                  "seed", "null_draws", "unmeasured", "folds",
                                  "chunk_rows", "max_samples"}
    # 개인 정보는 여전히 없다.
    assert not any(k in low for k in ("user_id", "email", "assets", "income"))
