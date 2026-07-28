"""적정가 밴드 시점 보정 테스트.

이 테스트가 지키려는 것 (전부 '값을 지어내지 않는다'의 변주다)
--------------------------------------------------------------
1. **지수가 없으면 보정하지 않는다** — 없는 계수를 1.0 으로 가정하지 않는다.
2. **보정한 값과 안 한 값을 한 중위에 섞지 않는다** — 부분 보정 금지.
3. **기준월은 완결된 달이다** — 표본이 덜 찬 이번 달로 환산하면 며칠 뒤 값이 바뀐다.
4. **보정했으면 결과에 그 사실과 시점이 남는다** — "현재 시세"라고 말하지 않는다.
5. **해제 거래는 보정 후에도 들어오지 않는다** — 기존 방어가 새 경로로 뚫리면 안 된다.
6. **지수를 안 주면 예전과 완전히 같은 값** — 조용한 동작 변경 금지.
"""
from __future__ import annotations

import datetime as dt

import pytest

from app.domain.valuation.models import MIN_SAMPLE, PriceBand, TradeRow
from app.domain.valuation.stats import fair_price_band
from app.domain.valuation.timeadjust import (
    MIN_ADJUST_COVERAGE,
    MIN_INDEX_MONTH_SAMPLE,
    MIN_REFERENCE_MONTH_SAMPLE,
    REASON_LOW_COVERAGE,
    REASON_NO_INDEX,
    REASON_NO_REFERENCE,
    REASON_OUT_OF_RANGE,
    REASON_TOO_FEW,
    SCOPE_SIDO,
    SCOPE_SIGUNGU,
    IndexPoint,
    MarketIndex,
    adjust_trades,
    adjustment_evidence,
    build_index,
    index_coverage,
    open_ym,
    select_index,
    ym_of,
)

TODAY = dt.date(2026, 7, 28)
OKU = 100_000_000


def t(ym: str, price_oku: float, *, day: int = 15, area=84.97, floor=10,
      cancelled=False) -> TradeRow:
    y, m = (int(x) for x in ym.split("-"))
    return TradeRow(contract_date=dt.date(y, m, day), price_krw=int(price_oku * OKU),
                    area_m2=area, floor=floor, is_cancelled=cancelled)


def idx(values: dict[str, float], *, complete_through: str | None = None,
        scope: str = SCOPE_SIGUNGU, region: str = "11680",
        sample: int = MIN_REFERENCE_MONTH_SAMPLE) -> MarketIndex:
    """테스트용 지수. `complete_through` 이후 달은 미완결로 둔다."""
    points = {
        ym: IndexPoint(ym=ym, value=v, sample_size=sample,
                       is_complete=(complete_through is None or ym <= complete_through))
        for ym, v in values.items()
    }
    return MarketIndex(region_code=region, scope=scope, points=points)


#: 실측에 맞춘 상승장 지수(서울 2026 상반기 수준: 6개월 +6%).
RISING = {"2026-01": 1.00, "2026-02": 1.01, "2026-03": 1.02,
          "2026-04": 1.03, "2026-05": 1.045, "2026-06": 1.06, "2026-07": 1.07}
#: 하락장 — 보정이 **양방향**임을 고정한다(전부 오르면 변별력이 없다).
FALLING = {ym: 2.0 - v for ym, v in RISING.items()}


# ---------------------------------------------------------------------------
# 1. 지수가 없으면 보정하지 않는다
# ---------------------------------------------------------------------------

def test_지수가_없으면_보정하지_않고_사유를_남긴다():
    trades = [t("2026-03", 14.0), t("2026-04", 14.1)]
    kept, adj = adjust_trades(trades, None)
    assert kept == trades
    assert adj.applied is False
    assert adj.reason == REASON_NO_INDEX
    assert adj.basis == "trade_raw"


def test_지수가_비어있으면_보정하지_않는다():
    empty = MarketIndex(region_code="11680", scope=SCOPE_SIGUNGU, points={})
    kept, adj = adjust_trades([t("2026-03", 14.0)], empty)
    assert adj.applied is False
    assert adj.reason == REASON_NO_INDEX


def test_완결월이_하나도_없으면_보정하지_않는다():
    """전부 미완결이면 환산할 '시점'이 없다. 아무 달이나 골라 쓰지 않는다."""
    all_partial = MarketIndex(
        region_code="11680", scope=SCOPE_SIGUNGU,
        points={ym: IndexPoint(ym=ym, value=v, sample_size=500, is_complete=False)
                for ym, v in RISING.items()})
    kept, adj = adjust_trades([t("2026-03", 14.0)] * 6, all_partial)
    assert adj.applied is False
    assert adj.reason == REASON_NO_REFERENCE
    assert adj.reference_ym is None


def test_기준월은_표본이_충분한_달만_된다():
    """기준월 오차는 모든 거래에 같은 방향으로 곱해져 상쇄되지 않는다 — 문턱이 더 높다."""
    thin = MIN_REFERENCE_MONTH_SAMPLE - 1
    index = MarketIndex(region_code="11680", scope=SCOPE_SIGUNGU, points={
        "2026-05": IndexPoint("2026-05", 1.045, MIN_REFERENCE_MONTH_SAMPLE, True),
        "2026-06": IndexPoint("2026-06", 1.060, thin, True),      # 완결이지만 표본 부족
    })
    # 표본이 얇은 2026-06 은 기준월이 아니다. 대신 2026-05 로 환산한다.
    assert index.reference_ym == "2026-05"


def test_기준월_후보가_전부_얇으면_보정하지_않는다():
    thin = MIN_REFERENCE_MONTH_SAMPLE - 1
    index = idx(RISING, complete_through="2026-06", sample=thin)
    kept, adj = adjust_trades([t("2026-01", 10.0) for _ in range(6)], index)
    assert adj.applied is False
    assert adj.reason == REASON_NO_REFERENCE


# ---------------------------------------------------------------------------
# 2. 부분 보정 금지 — 섞지 않는다
# ---------------------------------------------------------------------------

def test_지수_확보율이_낮으면_통째로_보정을_포기한다():
    """지수 있는 거래만 골라 보정하면 시점 분포가 편향된다. 그럴 바엔 안 한다."""
    partial = idx({"2026-06": 1.06}, complete_through="2026-06")
    trades = [t("2026-06", 14.0)] + [t("2025-01", 12.0) for _ in range(9)]
    kept, adj = adjust_trades(trades, partial)
    assert adj.applied is False
    assert adj.reason == REASON_LOW_COVERAGE
    assert kept == trades                       # 원본 그대로
    assert adj.coverage_pct == pytest.approx(10.0)


def test_커버리지_경계에서_보정된다():
    """경계값(정확히 MIN_ADJUST_COVERAGE)은 통과해야 한다 — 부등호 방향 고정."""
    covered = idx({"2026-06": 1.06, "2026-05": 1.045}, complete_through="2026-06")
    trades = ([t("2026-05", 14.0) for _ in range(8)]
              + [t("2024-01", 10.0) for _ in range(2)])   # 8/10 = 0.80
    kept, adj = adjust_trades(trades, covered)
    assert adj.applied is True
    assert adj.coverage_pct == pytest.approx(MIN_ADJUST_COVERAGE * 100)
    assert len(kept) == 8                       # 지수 없는 2건은 빠진다(섞지 않는다)


def test_보정후_표본이_최소치_미만이면_포기한다():
    small = idx({"2026-06": 1.06}, complete_through="2026-06")
    trades = [t("2026-06", 14.0) for _ in range(MIN_SAMPLE - 1)]
    kept, adj = adjust_trades(trades, small)
    assert adj.applied is False
    assert adj.reason == REASON_TOO_FEW


def test_보정배율이_비정상이면_포기한다():
    """지수가 깨졌을 때 조용히 2배짜리 추정가를 내느니 보정을 포기한다."""
    broken = idx({"2026-01": 0.01, "2026-06": 1.06}, complete_through="2026-06")
    trades = [t("2026-01", 14.0) for _ in range(6)]
    kept, adj = adjust_trades(trades, broken)
    assert adj.applied is False
    assert adj.reason == REASON_OUT_OF_RANGE
    assert kept == trades


# ---------------------------------------------------------------------------
# 3. 기준월 — 완결된 가장 최근 달
# ---------------------------------------------------------------------------

def test_미완결_최신월은_기준월이_되지_않는다():
    """이번 달은 신고 지연으로 표본이 덜 찼다. 기준으로 쓰면 값이 며칠 뒤 바뀐다."""
    index = idx(RISING, complete_through="2026-06")
    assert index.reference_ym == "2026-06"      # 2026-07 이 아니다
    assert index.reference_point.value == pytest.approx(1.06)


def test_기준월_지수로_환산된다():
    index = idx(RISING, complete_through="2026-06")
    # 2026-01(1.00) → 2026-06(1.06) = +6%
    kept, adj = adjust_trades([t("2026-01", 10.0) for _ in range(6)], index)
    assert adj.applied is True
    assert adj.reference_ym == "2026-06"
    assert all(k.price_krw == int(round(10.0 * OKU * 1.06)) for k in kept)
    assert adj.shift_pct == pytest.approx(6.0, abs=0.05)


# ---------------------------------------------------------------------------
# 4. 보정 사실과 시점이 결과에 남는다
# ---------------------------------------------------------------------------

def test_밴드에_보정시점이_남고_현재시세라고_말하지_않는다():
    index = idx(RISING, complete_through="2026-06")
    trades = [t("2026-01", 10.0 + i * 0.1) for i in range(8)]
    band = fair_price_band(trades, area_m2=84.97, as_of=TODAY, index=index)

    assert band.available
    assert band.is_time_adjusted is True
    assert band.as_of_label == "2026-06"
    note = band.time_adjustment.note()
    assert "2026-06 시점으로 환산" in note
    assert "현재 시세" not in note               # 단정하지 않는다
    ev = band.to_evidence(as_of=TODAY)[0]
    assert ev["time_adjusted"] is True
    assert ev["basis"] == "trade_time_adjusted"
    assert "2026-06 시점 환산 중위" in ev["claim"]


def test_보정하지_않은_밴드는_보정됐다고_말하지_않는다():
    """`time_adjustment` 가 있어도 applied=False 면 미보정이다 — 값의 유무로 판단 금지."""
    nothing = idx({"2000-01": 1.0}, complete_through="2000-01")
    trades = [t("2026-01", 10.0 + i * 0.1) for i in range(8)]
    band = fair_price_band(trades, area_m2=84.97, as_of=TODAY, index=nothing)

    assert band.available
    assert band.time_adjustment is not None      # 시도는 했다
    assert band.time_adjustment.applied is False # 하지만 적용되지 않았다
    assert band.is_time_adjusted is False
    assert band.as_of_label is None
    ev = band.to_evidence(as_of=TODAY)[0]
    assert ev["time_adjusted"] is False
    assert ev["basis"] == "trade_raw"
    assert "환산" not in ev["claim"]
    assert adjustment_evidence(band.time_adjustment) == []


# ---------------------------------------------------------------------------
# 5. 기존 방어가 새 경로로 뚫리지 않는다
# ---------------------------------------------------------------------------

def test_해제거래는_보정_경로에서도_들어오지_않는다():
    """시점 보정을 켜도 해제(취소) 거래가 밴드에 섞이면 안 된다."""
    index = idx(RISING, complete_through="2026-06")
    real = [t("2026-01", 10.0) for _ in range(6)]
    fake = [t("2026-06", 99.0, cancelled=True) for _ in range(6)]
    band = fair_price_band(real + fake, area_m2=84.97, as_of=TODAY, index=index)

    assert band.sample_size == 6
    assert band.median_krw is not None
    assert band.median_krw < 20 * OKU            # 99억 신고가가 반영되지 않았다


def test_표본부족이면_보정과_무관하게_숫자를_만들지_않는다():
    index = idx(RISING, complete_through="2026-06")
    band = fair_price_band([t("2026-01", 10.0)], area_m2=84.97, as_of=TODAY, index=index)
    assert band.available is False
    assert band.median_krw is None
    assert band.is_time_adjusted is False


# ---------------------------------------------------------------------------
# 6. 지수를 안 주면 예전과 같다 + 방향은 양방향이다
# ---------------------------------------------------------------------------

def test_지수를_주지_않으면_예전과_완전히_같은_값이다():
    trades = [t("2026-01", 10.0 + i * 0.1) for i in range(8)]
    before = fair_price_band(trades, area_m2=84.97, as_of=TODAY)
    after = fair_price_band(trades, area_m2=84.97, as_of=TODAY, index=None)
    assert before == after
    assert before.time_adjustment is None        # '시도조차 안 함'
    assert before.is_time_adjusted is False


def test_하락장에서는_추정가가_내려간다():
    """전부 올라가면 변별력이 없다. 지수가 내려가면 추정가도 내려가야 한다."""
    up = idx(RISING, complete_through="2026-06")
    down = idx(FALLING, complete_through="2026-06")
    trades = [t("2026-01", 10.0 + i * 0.1) for i in range(8)]

    raw = fair_price_band(trades, area_m2=84.97, as_of=TODAY)
    hi = fair_price_band(trades, area_m2=84.97, as_of=TODAY, index=up)
    lo = fair_price_band(trades, area_m2=84.97, as_of=TODAY, index=down)

    assert hi.median_krw > raw.median_krw
    assert lo.median_krw < raw.median_krw
    assert hi.time_adjustment.shift_pct > 0
    assert lo.time_adjustment.shift_pct < 0


def test_평평한_시장에서는_거의_움직이지_않는다():
    flat = idx({ym: 1.0 for ym in RISING}, complete_through="2026-06")
    trades = [t("2026-01", 10.0 + i * 0.1) for i in range(8)]
    raw = fair_price_band(trades, area_m2=84.97, as_of=TODAY)
    adj = fair_price_band(trades, area_m2=84.97, as_of=TODAY, index=flat)
    assert adj.median_krw == raw.median_krw
    assert adj.time_adjustment.shift_pct == pytest.approx(0.0)


def test_각_거래를_개별_보정한다_중위에_계수를_곱하지_않는다():
    """시점이 쏠린 표본에서 두 방식은 **다른 답**을 낸다. 개별 보정이 맞는 답이다.

    옛 거래(싸고 보정 큼) 5건 + 최근 거래(비싸고 보정 없음) 4건을 섞으면,
    보정 후 대소 관계가 뒤집혀 중위를 잡는 거래 자체가 바뀐다. 중위에 계수를
    한 번 곱하는 방식은 그 뒤집힘을 표현하지 못한다.
    """
    index = idx({"2026-01": 1.00, "2026-06": 1.20}, complete_through="2026-06")
    trades = ([t("2026-01", 10.0) for _ in range(5)]        # 보정 후 12.0억
              + [t("2026-06", 11.5) for _ in range(4)])     # 보정 없음 11.5억
    raw = fair_price_band(trades, area_m2=84.97, as_of=TODAY)
    band = fair_price_band(trades, area_m2=84.97, as_of=TODAY, index=index)

    # 보정 전 중위는 10.0억(옛 거래가 다수) — 보정 후에는 12.0억이 중위가 된다.
    assert raw.median_krw == pytest.approx(10.0 * OKU, rel=1e-6)
    assert band.median_krw == pytest.approx(12.0 * OKU, rel=1e-6)

    # '중위 × 계수 하나' 방식이 낼 수 있는 값들과 모두 다르다.
    avg_ratio = (5 * 1.20 + 4 * 1.00) / 9
    assert band.median_krw != pytest.approx(raw.median_krw * avg_ratio, rel=1e-3)
    assert band.median_krw != pytest.approx(raw.median_krw * 1.00, rel=1e-3)


# ---------------------------------------------------------------------------
# build_index — 표본 미달 월은 만들지 않는다 / 완결 판정
# ---------------------------------------------------------------------------

def test_표본_미달_월은_지수를_만들지_않는다():
    rows = [("2026-01", 1.00, MIN_INDEX_MONTH_SAMPLE),
            ("2026-02", 1.01, MIN_INDEX_MONTH_SAMPLE - 1),   # 미달 → 버린다
            ("2026-03", 1.02, MIN_INDEX_MONTH_SAMPLE + 5)]
    index = build_index(rows, region_code="11680", scope=SCOPE_SIGUNGU, as_of=TODAY)
    assert set(index.points) == {"2026-01", "2026-03"}


def test_표본이_급감한_달은_미완결로_표시된다():
    """건수 검사는 **그대로 살아 있다** — 수집 누락(한 달이 통째로 비는 일)을 잡는다."""
    rows = [(f"2026-{m:02d}", 1.0 + m / 100, 1000) for m in range(1, 5)]
    rows.append(("2026-05", 1.05, 400))          # 직전 중위의 40% → 미완결
    index = build_index(rows, region_code="11680", scope=SCOPE_SIGUNGU,
                        as_of=dt.date(2026, 7, 31))    # 달력으로는 2026-06 까지 완결 가능
    assert index.points["2026-05"].is_complete is False
    assert index.points["2026-04"].is_complete is True


# ---------------------------------------------------------------------------
# build_index — **달력 하한** (CR33-1)
#
# 운영에서 실제로 난 사고: 거래가 많은 4개 지역(수원권선·오산·용인처인·화성병점)이
# **진행 중인 달(2026-07)** 을 완결로 통과시켜 기준월로 썼다(581단지, 3.5%).
# 건수만 보면 못 잡는다 — 그 달들은 직전 중위의 78~98% 를 이미 채웠다.
# ---------------------------------------------------------------------------

def test_진행_중인_달은_표본이_많아도_완결이_아니다():
    """★ CR33-1. 변이: `_complete_flags` 의 달력 하한(`ym >= open_ym`)을 지우면
    2026-07 이 다시 완결이 되어 여기서 잡힌다.

    운영 실측을 그대로 본뜬다 — 2026-07 표본이 직전 달들과 **같은 수준**이라
    건수 검사(80%)는 통과한다. 그래도 완결이 아니다: 7월은 끝나지 않았고
    신고 지연(30일)도 안 지났다.
    """
    rows = [(f"2026-{m:02d}", 1.0 + m / 100, 1000) for m in range(1, 7)]
    rows.append(("2026-07", 1.07, 980))          # 직전 중위의 98% — 건수로는 통과한다
    index = build_index(rows, region_code="41113", scope=SCOPE_SIGUNGU, as_of=TODAY)

    assert index.points["2026-07"].is_complete is False, "진행 중인 달은 완결이 아니다"
    assert index.points["2026-07"].sample_size == 980, "지수 자체는 남는다(보정에는 쓴다)"
    assert index.reference_ym == "2026-05", "기준월은 신고 지연까지 지난 달이어야 한다"


def test_이번_달은_기준월이_되지_않아_며칠_뒤에도_같은_값을_낸다():
    """★ 재현성. '새 정보 없이 날짜만 지나 밴드가 뒤집히는' 것이 CR33-1 의 피해다.

    같은 입력을 7/28 · 7/29 · 7/30 로 세 번 판정해 기준월이 **움직이지 않는지** 본다.
    (7/31 에는 2026-06 이 정상적으로 열린다 — 그건 새 달이 정착한 것이라 옳다.)
    """
    rows = [(f"2026-{m:02d}", 1.0 + m / 100, 1000) for m in range(1, 7)]
    rows.append(("2026-07", 1.07, 980))
    refs = {d: build_index(rows, region_code="41113", scope=SCOPE_SIGUNGU,
                           as_of=dt.date(2026, 7, d)).reference_ym
            for d in (28, 29, 30, 31)}
    assert refs[28] == refs[29] == refs[30] == "2026-05"
    assert refs[31] == "2026-06", "6월 말 계약의 신고기한(7/30)이 지나면 6월이 열린다"


def test_open_ym_은_신고기한이_지난_달만_연다():
    """경계를 값으로 못박는다. 계약월 M 의 마지막 계약은 M말+30일까지 신고할 수 있다."""
    assert open_ym(dt.date(2026, 7, 28)) == "2026-06"   # 6월은 아직 안 닫혔다(7/30 까지)
    assert open_ym(dt.date(2026, 7, 30)) == "2026-06"
    assert open_ym(dt.date(2026, 7, 31)) == "2026-07"   # 이제 6월까지 완결 후보
    assert open_ym(dt.date(2026, 1, 5)) == "2025-12"    # 연말 경계


def test_build_index_는_시계를_읽지_않는다():
    """★ 변이: `as_of` 에 기본값(오늘)을 주면 이 테스트가 실패한다.

    시계를 함수 안에서 읽으면 같은 입력이 날짜에 따라 다른 답을 내고, 그 순간
    '며칠 뒤 이유 없이 값이 바뀐다'(모듈 규칙 3)를 이 모듈이 스스로 저지른다.
    """
    import inspect

    sig = inspect.signature(build_index)
    assert sig.parameters["as_of"].default is inspect.Parameter.empty, (
        "as_of 는 반드시 주입돼야 한다 — 기본값을 주면 시계 의존이 되살아난다")

    rows = [(f"2025-{m:02d}", 1.0, 1000) for m in range(1, 13)]
    old = build_index(rows, region_code="11680", scope=SCOPE_SIGUNGU,
                      as_of=dt.date(2026, 1, 31))
    new = build_index(rows, region_code="11680", scope=SCOPE_SIGUNGU,
                      as_of=dt.date(2030, 1, 1))
    assert old.reference_ym == new.reference_ym == "2025-12"


# ---------------------------------------------------------------------------
# 지수 선택 정책 (`select_index`) — 커버리지 → **최신 기준월** → 시군구 tie-break
#
# ⚠️ 이 정책은 한동안 배선 계층(`orchestrator._freshest_index`)에 있었고, 그동안
#    `select_index` 는 폐기된 정책("시군구 우선")을 공개 API 로 선언했다. 도메인이
#    안내하는 정식 경로(`fair_price_band(index=select_index(...))`)가 남산타운
#    −12.3% 를 내는 상태였다(CR33-2). 정책은 여기 있고, 여기서 고정한다.
# ---------------------------------------------------------------------------

def test_기준월이_같으면_더_정밀한_시군구를_쓴다():
    fine = idx(RISING, complete_through="2026-06", scope=SCOPE_SIGUNGU, region="11680")
    coarse = idx(RISING, complete_through="2026-06", scope=SCOPE_SIDO, region="11")
    trades = [t("2026-01", 10.0) for _ in range(6)]
    assert select_index(trades, sigungu=fine, sido=coarse) is fine


def test_시군구_기준월이_낡았으면_시도_지수를_쓴다():
    """★ CR33-2. 변이: `select_index` 를 '시군구 우선'으로 되돌리면 여기서 잡힌다.

    운영 실측(11140 중구: 기준월 2025-06, 시도는 2026-06)이 근거다. 상승장에서 낡은
    기준월로 환산하면 값이 **내려가고**(남산타운 15.00억 → 13.16억), 한 목록 안에서
    후보마다 환산 시점이 갈려 한 예산으로 비교할 수 없게 된다.
    """
    stale = idx({ym: v for ym, v in RISING.items() if ym <= "2026-03"},
                complete_through="2026-03", scope=SCOPE_SIGUNGU, region="11140")
    fresh = idx(RISING, complete_through="2026-06", scope=SCOPE_SIDO, region="11")
    trades = [t("2026-01", 10.0) for _ in range(6)]

    chosen = select_index(trades, sigungu=stale, sido=fresh)
    assert chosen is fresh
    assert chosen.reference_ym == "2026-06"

    # 그리고 그 선택이 값에서 드러난다 — 낡은 지수를 썼다면 밴드가 더 낮았을 것이다.
    _kept, adj_fresh = adjust_trades(trades, chosen)
    _kept, adj_stale = adjust_trades(trades, stale)
    assert adj_fresh.shift_pct > adj_stale.shift_pct


def test_시군구_지수에_구멍이_있으면_시도로_내려간다():
    """구멍 뚫린 정밀 지수는 보정을 통째로 막는다. 거친 지수로라도 시점을 맞춘다."""
    holey = idx({"2026-06": 1.06}, complete_through="2026-06", scope=SCOPE_SIGUNGU)
    coarse = idx(RISING, complete_through="2026-06", scope=SCOPE_SIDO, region="11")
    trades = [t("2026-01", 10.0) for _ in range(6)]           # 시군구에 2026-01 없음
    chosen = select_index(trades, sigungu=holey, sido=coarse)
    assert chosen is coarse
    _kept, adj = adjust_trades(trades, chosen)
    assert adj.applied is True
    assert adj.scope == SCOPE_SIDO


def test_둘_다_못_덮으면_지수를_고르지_않는다():
    trades = [t("2020-01", 10.0) for _ in range(6)]
    fine = idx(RISING, complete_through="2026-06", scope=SCOPE_SIGUNGU)
    coarse = idx(RISING, complete_through="2026-06", scope=SCOPE_SIDO, region="11")
    assert select_index(trades, sigungu=fine, sido=coarse) is None
    assert index_coverage(trades, fine) == 0.0


def test_지수값이_0_이하면_거부한다():
    with pytest.raises(ValueError):
        IndexPoint(ym="2026-01", value=0.0, sample_size=100)


def test_ym_of_는_계약일을_월키로_바꾼다():
    assert ym_of(dt.date(2026, 7, 5)) == "2026-07"
    assert ym_of(dt.date(2026, 12, 31)) == "2026-12"


def test_시도_폴백_지수도_라벨이_남는다():
    """시군구 지수가 없어 시도로 폴백했으면 근거에 그렇게 적힌다."""
    sido = idx(RISING, complete_through="2026-06", scope=SCOPE_SIDO, region="11")
    kept, adj = adjust_trades([t("2026-01", 10.0) for _ in range(6)], sido)
    assert adj.applied is True
    assert adj.scope == SCOPE_SIDO
    assert "시도" in adj.note()
    assert adjustment_evidence(adj)[0]["basis"] == "trade_time_adjusted"
