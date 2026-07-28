"""시점 보정 **배선** 테스트 — 도메인이 아니라 '실제로 연결됐는가'를 고정한다.

왜 파일을 따로 두는가
---------------------
`test_valuation_timeadjust.py` 는 순수 함수(`adjust_trades`·`select_index`)가 옳게
계산하는지를 본다. 그런데 이 기능이 실패하는 가장 현실적인 방식은 **계산이 틀리는 것이
아니라 아무 데도 연결되지 않는 것**이다. 실제로 그 상태로 한 라운드가 끝났다:
도메인·SQL·배치가 다 있는데 `reference_band()` 가 `index=None` 으로 불려서
**동작 변화가 0 이었다.** 오류도, 경고도, 다른 숫자도 없었다.

그래서 여기서 고정하는 것은 값이 아니라 **경로**다:

    Candidate.region_code → ctx.market_indexes → reference_band(indexes=…)
      → fair_price_band(index=…) → PriceBand.time_adjustment
      → 예산 판정(reference_price_krw) · 근거 문구 · 결과 notes

각 테스트에 **변이(mutation)** 를 적어 둔다 — 그 줄을 되돌렸을 때 여기서 잡히는가.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from app.agents.orchestrator import (
    EXCLUDED_OVER_BUDGET,
    AnalysisContext,
    Candidate,
    candidate_index,
    reference_band,
    region_index_keys,
    run_mvp_pipeline,
    valuation_finding,
)
from app.agents.recommend import load_market_indexes
from app.domain.affordability.engine import compute_affordability
from app.domain.affordability.models import Borrower, PropertyFacts
from app.domain.rules.loader import load_rules
from app.domain.valuation.models import TradeRow
from app.domain.valuation.timeadjust import (
    MIN_REFERENCE_MONTH_SAMPLE,
    REASON_NO_INDEX,
    SCOPE_SIDO,
    SCOPE_SIGUNGU,
    IndexPoint,
    MarketIndex,
)

TODAY = dt.date(2026, 7, 28)
OKU = 100_000_000

#: 서울 실측을 본뜬 상승 지수(2025-08 → 2026-06 약 +12%).
#: 기준월은 2026-06 이다 — 2026-07 은 신고 지연으로 미완결이라 기준월이 될 수 없다.
SEOUL_RISING = {
    "2025-08": 0.95, "2025-09": 0.96, "2025-10": 0.97, "2025-11": 0.98,
    "2025-12": 0.99, "2026-01": 1.00, "2026-02": 1.01, "2026-03": 1.02,
    "2026-04": 1.04, "2026-05": 1.05, "2026-06": 1.06, "2026-07": 1.07,
}
#: 인천 실측을 본뜬 하락 지수. **양방향으로 움직여야** 보정이 살아 있는 것이다.
FALLING = {ym: round(2.0 - v, 4) for ym, v in SEOUL_RISING.items()}


def _index(values: dict[str, float], *, region: str, scope: str = SCOPE_SIGUNGU,
           incomplete_from: str = "2026-07") -> MarketIndex:
    return MarketIndex(region_code=region, scope=scope, points={
        ym: IndexPoint(ym=ym, value=v, sample_size=MIN_REFERENCE_MONTH_SAMPLE,
                       is_complete=ym < incomplete_from)
        for ym, v in values.items()
    })


def _trades(price_oku: float, *, months: tuple[int, ...] = (1, 3, 5, 7, 9, 11),
            area: float = 84.97) -> list[TradeRow]:
    """같은 명목가로 여러 달에 걸친 거래. **명목가가 같으므로** 밴드 중위가 움직이면
    그건 오직 시점 보정 때문이다(다른 변수를 남기지 않는다)."""
    out = []
    for m in months:
        d = TODAY - dt.timedelta(days=30 * m)
        out.append(TradeRow(contract_date=d, price_krw=int(price_oku * OKU),
                            area_m2=area, floor=10))
    return out


def _candidate(*, region_code: str | None = "1168010100", price_oku: float = 10.0,
               complex_id: int = 1, name: str = "○○아파트") -> Candidate:
    """호가가 **없는** 후보 — 이 경우 밴드 중위가 곧 예산 판정 기준가다."""
    return Candidate(complex_id=complex_id, complex_name=name, unit_type_id=None,
                     area_m2=84.97, region_code=region_code, group=None,
                     trades=_trades(price_oku), total_households=500, listings=[])


def _ctx(candidates, *, indexes, budget_oku: float = 10.5) -> AnalysisContext:
    rules = load_rules(Path(__file__).parent / "fixtures" / "tax_rules_test.yaml")
    afford = compute_affordability(
        Borrower(cash_krw=int(budget_oku * OKU), annual_income_krw=100_000_000),
        rules, prop=PropertyFacts(area_m2=84.0))
    return AnalysisContext(affordability=afford, candidates=list(candidates),
                           as_of=TODAY, market_indexes=indexes,
                           budget_krw=int(budget_oku * OKU))


def _band_of(item) -> dict:
    return item["price_band"]


# ---------------------------------------------------------------------------
# 1. 배선 — 지수가 실제로 밴드까지 닿는가
# ---------------------------------------------------------------------------

def test_파이프라인이_지수를_밴드에_먹인다():
    """★ 핵심. 변이: `reference_band(cand, ctx.as_of)` 로 되돌리면(=indexes 미전달)
    `time_adjusted` 가 False 가 되어 여기서 잡힌다."""
    idx = {"11680": _index(SEOUL_RISING, region="11680")}
    out = run_mvp_pipeline(_ctx([_candidate()], indexes=idx, budget_oku=99.0), llm=None)

    band = _band_of(out["items"][0])
    assert band["time_adjusted"] is True
    assert band["as_of_ym"] == "2026-06"
    assert band["time_adjustment"]["applied"] is True
    assert band["time_adjustment"]["scope"] == SCOPE_SIGUNGU
    assert band["time_adjustment"]["region_code"] == "11680"


def test_보정이_밴드_중위를_실제로_올린다():
    """명목가가 모두 같으므로 중위가 움직이면 원인은 시점 보정뿐이다."""
    cand = _candidate()
    raw = reference_band(cand, TODAY)                       # 보정 없음(예전 동작)
    adjusted = reference_band(cand, TODAY,
                              indexes={"11680": _index(SEOUL_RISING, region="11680")})

    assert raw.median_krw is not None and adjusted.median_krw is not None
    assert adjusted.median_krw > raw.median_krw, "상승장에서 보정값이 더 높아야 한다"
    assert raw.time_adjustment is None                       # 시도조차 안 함
    assert adjusted.time_adjustment.applied is True


def test_하락장에서는_보정이_밴드를_내린다():
    """★ 양방향. 변이: 보정을 '항상 올리는' 방향으로 잘못 구현하면 여기서 잡힌다."""
    cand = _candidate(region_code="2818510300")
    raw = reference_band(cand, TODAY)
    adjusted = reference_band(cand, TODAY,
                              indexes={"28185": _index(FALLING, region="28185")})

    assert adjusted.median_krw < raw.median_krw
    assert adjusted.time_adjustment.shift_pct < 0


# ---------------------------------------------------------------------------
# 2. 예산 판정 — 이 작업의 진짜 목적
# ---------------------------------------------------------------------------

def test_보정하면_예산_안이던_후보가_밖으로_나간다():
    """★ 이 배선의 존재 이유. 호가가 없는 후보는 밴드 중위가 **예산 판정 기준가**다.
    시점 보정을 안 하면 상승장에서 그 값이 낮게 나와 **못 사는 단지가 통과한다.**

    변이: 파이프라인이 `ctx.market_indexes` 를 안 넘기면 후보가 다시 '예산 안'이 되어
    여기서 잡힌다.
    """
    # 명목 10억, 보정 후 약 10.6억. 예산 10.3억 — 보정 여부가 판정을 가른다.
    cand = _candidate(price_oku=10.0)
    idx = {"11680": _index(SEOUL_RISING, region="11680")}

    before = run_mvp_pipeline(_ctx([cand], indexes=None, budget_oku=10.3), llm=None)
    after = run_mvp_pipeline(_ctx([cand], indexes=idx, budget_oku=10.3), llm=None)

    assert [it["complex"]["id"] for it in before["items"]] == [1], "보정 전엔 예산 안"
    assert not after["items"], "보정 후엔 예산 초과라 추천에서 빠져야 한다"
    reason = after["excluded"][0]
    assert reason["reason_code"] == EXCLUDED_OVER_BUDGET
    # 사유 문장이 **어느 시점의 추정치인지** 말해야 한다("최근 실거래"라고만 하면
    # 사용자는 원본 체결가로 읽는다).
    assert "2026-06 시점 환산" in reason["reason"]


def test_예산_판정에_쓴_값과_카드에_표시되는_값이_같다():
    """`est_price_krw`(판정에 쓴 값)와 밴드 중위가 어긋나면 화면과 판정이 다른 말을 한다."""
    idx = {"11680": _index(SEOUL_RISING, region="11680")}
    out = run_mvp_pipeline(_ctx([_candidate()], indexes=idx, budget_oku=99.0), llm=None)
    item = out["items"][0]
    assert item["est_price_krw"] == item["price_band"]["median_krw"]


# ---------------------------------------------------------------------------
# 3. 조용한 실패 금지 — 보정을 못 했으면 반드시 말한다
# ---------------------------------------------------------------------------

def test_지수가_비어_있으면_조용히_통과하지_않는다():
    """★ 변이: `candidate_index` 가 `select_index` 의 None 을 그대로 돌려주면
    `time_adjustment` 자체가 사라져(=시도조차 안 한 것과 구분 불가) 여기서 잡힌다."""
    out = run_mvp_pipeline(_ctx([_candidate()], indexes={}, budget_oku=99.0), llm=None)

    band = _band_of(out["items"][0])
    assert band["time_adjusted"] is False
    assert band["time_adjustment"] is not None, "조회했는데 결과가 통째로 비면 안 된다"
    assert band["time_adjustment"]["applied"] is False
    assert band["time_adjustment"]["reason"] == REASON_NO_INDEX
    assert band["as_of_ym"] is None                    # 시점을 말할 수 없다
    # 결과 상단에도 남는다(카드를 하나씩 열지 않아도 알 수 있게).
    assert any("시점 보정을 적용하지 못해" in n for n in out["notes"])


def test_보정_실패는_시세_판정의_리스크로도_남는다():
    f = valuation_finding(_candidate(), TODAY, indexes={})
    assert any("시점 보정" in r.detail for r in f.risks)


def test_지수를_조회조차_안_하면_시도_안_함으로_구분된다():
    """'배치를 안 돌렸다'와 '배선이 빠졌다'는 운영에서 완전히 다른 사고다."""
    out = run_mvp_pipeline(_ctx([_candidate()], indexes=None, budget_oku=99.0), llm=None)

    band = _band_of(out["items"][0])
    assert band["time_adjustment"] is None
    assert band["time_adjusted"] is False
    assert any("시장지수 미조회" in n for n in out["notes"])


def test_지역코드가_없으면_보정하지_않는다():
    """모르는 지역에 아무 지수나 붙이지 않는다(지수 1.0 가정 금지)."""
    idx = {"11680": _index(SEOUL_RISING, region="11680")}
    cand = _candidate(region_code=None)
    band = reference_band(cand, TODAY, indexes=idx)
    assert band.is_time_adjusted is False


def test_다른_지역_지수를_끌어다_쓰지_않는다():
    """경기 단지에 서울 지수를 붙이면 편향이 커진다(서울 +10% vs 경기 +3%)."""
    idx = {"11680": _index(SEOUL_RISING, region="11680")}
    band = reference_band(_candidate(region_code="4113510300"), TODAY, indexes=idx)
    assert band.is_time_adjusted is False


# ---------------------------------------------------------------------------
# 4. 근거 문구 — "현재 시세"라고 말하지 않는다
# ---------------------------------------------------------------------------

def test_근거와_문구에_기준월이_박힌다():
    idx = {"11680": _index(SEOUL_RISING, region="11680")}
    band = reference_band(_candidate(), TODAY, indexes=idx)
    f = valuation_finding(_candidate(), TODAY, band=band)

    claims = " ".join(e.claim for e in f.evidence)
    assert "2026-06 시점 환산" in claims
    assert "2026-06 시점 환산" in f.rationale
    assert "현재 시세" not in f.rationale and "현재 시세" not in claims
    # 보정 근거(시장지수)가 실거래 근거와 **따로** 실린다 — 하나로 뭉치면 어느 쪽이
    # 실거래고 어느 쪽이 우리 계산인지 사라진다.
    assert any("시장지수" in e.claim for e in f.evidence)


def test_보정_안_한_밴드는_환산이라고_말하지_않는다():
    f = valuation_finding(_candidate(), TODAY, indexes={})
    assert "시점 환산" not in f.rationale
    assert all("시점 환산" not in e.claim for e in f.evidence)


# ---------------------------------------------------------------------------
# 5. 조회 비용 — 후보 루프 밖에서 지역당 한 번
# ---------------------------------------------------------------------------

class _CountingRepo:
    """`market_index` 호출 횟수를 세는 리포지토리 더블."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def market_index(self, region_code: str, scope: str) -> MarketIndex:
        self.calls.append((region_code, scope))
        return MarketIndex(region_code=region_code, scope=scope, points={})


def test_후보가_많아도_지역당_한_번만_조회한다():
    """★ 변이: 후보 루프 안에서 조회하면 60회가 되어 여기서 잡힌다.
    (후보 상한 200 × 2층위 = 400 쿼리가 되는 자리다.)"""
    repo = _CountingRepo()
    cands = ([_candidate(region_code="1168010100", complex_id=i) for i in range(30)]
             + [_candidate(region_code="4113510300", complex_id=100 + i)
                for i in range(30)])

    out = load_market_indexes(repo, cands)

    assert len(repo.calls) == 4, repo.calls          # 11680·11 · 41135·41
    assert set(out) == {"11680", "11", "41135", "41"}
    assert {s for _, s in repo.calls} == {SCOPE_SIGUNGU, SCOPE_SIDO}


class _SeededRepo(_CountingRepo):
    """`_assemble_candidates` 가 쓰는 최소 duck-typing 리포지토리."""

    def __init__(self, region: str) -> None:
        super().__init__()
        from app.repositories.base import ComplexSummary
        self._complex = ComplexSummary(
            id=1, name="테스트단지", lon=127.05, lat=37.51, region_code=region,
            built_year=2015, total_households=500,
            recent_price_krw=10 * OKU, price_as_of=TODAY.isoformat(),
            active_listings=0)

    def recommendation_candidates(self, **_kw):
        return [self._complex]

    def listings_for_complex(self, _cid):
        return []

    def trades_for_complex(self, _cid):
        return _trades(10.0)


def test_후보_조립이_지역코드를_실어_보낸다():
    """★ 변이: `_build` 에서 `region_code=` 를 빼면 지수 키가 안 만들어져 여기서 잡힌다.

    이 줄이 없으면 조회는 도는데 **키가 하나도 없어** 아무 후보도 보정되지 않는다
    — 오류 없이 기능만 사라지는, 이 라운드에서 실제로 있었던 형태의 실패다.
    """
    from app.agents.recommend import _assemble_candidates

    repo = _SeededRepo("1168010100")
    assembly = _assemble_candidates(repo, {}, None, None)

    assert assembly.candidates, "후보 조립 자체가 실패했다"
    assert assembly.candidates[0].region_code == "1168010100"
    assert set(load_market_indexes(repo, assembly.candidates)) == {"11680", "11"}


def test_지수_조회가_계산방법을_거른다():
    """★ CR33-4. 변이: `_MARKET_INDEX_SQL` 에서 `method = :method` 를 빼면 잡힌다.

    표는 방법별로 값을 따로 보관한다(migration 015). 조회가 그걸 안 보면 v2 로 일부
    지역만 재계산하는 날 `idx(A)/idx(B)` 가 시장 변화가 아니라 **방법 차이**를 잰다.
    오류는 안 나고 값만 틀리는 종류라, 여기서 파라미터까지 확인한다.

    DB 없이 돈다 — 엔진 자리에 기록용 더블을 끼운다(실 조회는 needs_db 쪽에서 본다).
    """
    from app.domain.valuation.timeadjust import INDEX_METHOD
    from app.repositories.postgis import PostgisRepository

    seen: list[tuple[str, dict]] = []

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, statement, params):
            seen.append((str(statement), dict(params)))
            return self

        def all(self):
            return []

    repo = object.__new__(PostgisRepository)
    repo._engine = type("E", (), {"connect": staticmethod(_Conn)})()

    index = repo.market_index("11680", SCOPE_SIGUNGU)

    assert index.points == {}
    sql, params = seen[0]
    assert "method = :method" in sql, sql
    assert params["method"] == INDEX_METHOD


def test_지수_조회_기능이_없는_리포지토리는_None_을_돌려준다():
    """옛 구현·테스트 더블에서도 추천은 죽지 않는다. 대신 '시도 안 함'이 남는다."""
    assert load_market_indexes(object(), [_candidate()]) is None


def test_조회가_실패해도_추천을_죽이지_않는다():
    class Boom:
        def market_index(self, region_code, scope):
            raise RuntimeError("db down")

    out = load_market_indexes(Boom(), [_candidate()])
    assert out == {}                                  # 실패는 '지수 없음'으로 흘러간다


# ---------------------------------------------------------------------------
# 6. 지역코드 → 지수 키
# ---------------------------------------------------------------------------

def test_법정동코드에서_시군구와_시도를_뽑는다():
    assert region_index_keys("1168010100") == ("11680", "11")
    assert region_index_keys("11680") == ("11680", "11")
    assert region_index_keys("11") == (None, "11")      # 시군구 키를 지어내지 않는다
    assert region_index_keys("") == (None, None)
    assert region_index_keys(None) == (None, None)


def test_시군구_지수가_얇으면_시도로_내려간다():
    """구멍 뚫린 정밀 지수보다 조금 거친 시도 지수가 낫다 — 무보정이 가장 나쁘다."""
    thin = _index({"2026-06": 1.06}, region="11680")          # 거래 시점을 못 덮는다
    wide = _index(SEOUL_RISING, region="11", scope=SCOPE_SIDO)
    chosen = candidate_index(_candidate(), {"11680": thin, "11": wide})
    assert chosen is wide
    assert chosen.scope == SCOPE_SIDO


# ---------------------------------------------------------------------------
# 7. 기준월이 낡은 시군구 지수 (운영 DB 실측: 79곳 중 28곳)
#
# ⚠️ **정책 자체는 도메인이 소유한다**(`timeadjust.select_index` · CR33-2).
#    여기서 보는 것은 배선이다 — 후보의 지역코드로 뽑은 두 지수가 그 정책에 실제로
#    들어가고, 그 결과가 밴드 문구(`as_of_label`)까지 나오는가.
# ---------------------------------------------------------------------------

def test_기준월이_뒤처진_시군구_지수는_시도로_바꾼다():
    """★ 운영 실측에서 나온 결함. 시군구 기준월이 1년 낡으면(11140 중구 2025-06)
    상승장에서 밴드가 **내려간다**(실측 −12.3%) — 고치려던 문제를 더 키운다.
    게다가 후보마다 시점이 달라져 한 예산으로 비교할 수 없게 된다.

    변이: `select_index` 를 '시군구 우선'으로 되돌리면 여기서도 잡힌다
    (도메인 쪽 고정은 `test_valuation_timeadjust.py`
    `test_시군구_기준월이_낡았으면_시도_지수를_쓴다`).
    """
    # ⚠️ stale 도 거래 시점을 **전부 덮는다**(값은 다 있고 최근 달만 미완결). 그래야
    #    커버리지가 아니라 **기준월**이 선택을 가르는 상황이 된다 — 덮지 못하게 만들면
    #    옛 정책('시군구 우선')으로 되돌려도 커버리지에서 걸러져 같은 답이 나온다.
    stale = _index(SEOUL_RISING, region="11140",
                   incomplete_from="2026-01")                   # 기준월 2025-12
    fresh = _index(SEOUL_RISING, region="11", scope=SCOPE_SIDO)  # 기준월 2026-06

    chosen = candidate_index(_candidate(region_code="1114010100"),
                             {"11140": stale, "11": fresh})
    assert chosen is fresh, "낡은 시군구 지수를 그대로 쓰면 값이 과거로 끌려간다"

    band = reference_band(_candidate(region_code="1114010100"), TODAY,
                          indexes={"11140": stale, "11": fresh})
    assert band.as_of_label == "2026-06"


def test_기준월이_같으면_더_정밀한_시군구를_쓴다():
    """시점이 같다면 지역 정밀도가 높은 쪽이 낫다(구별 편차를 볼 수 있다)."""
    sgg = _index(SEOUL_RISING, region="11680")
    sido = _index(SEOUL_RISING, region="11", scope=SCOPE_SIDO)
    chosen = candidate_index(_candidate(), {"11680": sgg, "11": sido})
    assert chosen is sgg
    assert chosen.scope == SCOPE_SIGUNGU
