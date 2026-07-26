"""사용자 조건 가중치(가격·입지·가치·리스크)가 **실제로 순위를 바꾸는가**.

배경 (회귀 방지 대상)
---------------------
`user_preference.weights` 는 슬라이더 → API → DB 로 저장만 되고 **점수 계산에 전혀
쓰이지 않았다.** 총점은 `sum(score×confidence)/sum(confidence)` 로 에이전트 신뢰도만
반영했고, 사용자가 슬라이더를 끝에서 끝까지 옮겨도 결과가 한 건도 바뀌지 않았다.

그래서 이 파일의 핵심 테스트는 "가중치 필드가 응답에 있다"가 아니라
**"가중치를 바꾸면 1위가 바뀐다"** 이다(자기충족 테스트 금지).
가중치 곱셈을 되돌리면(신뢰도 평균으로 회귀) `test_가격100과_가치100은_1위가_다르다` 가
즉시 깨진다 — 두 후보의 신뢰도 평균은 가중치와 무관하게 항상 같은 순서이기 때문이다.
"""
from __future__ import annotations

import datetime as dt

import pytest

from app.agents.base import Evidence, Finding
from app.agents.orchestrator import AnalysisContext, Candidate, run_mvp_pipeline
from app.agents.scoring import (
    AXIS_LOCATION,
    AXIS_PRICE,
    AXIS_RISK,
    AXIS_SPECS,
    AXIS_VALUE,
    BASIS_AGENT_SCORES,
    BASIS_USER_WEIGHTED,
    STATUS_APPLIED,
    STATUS_NO_SIGNAL,
    TURNOVER_FULL_SCORE_PCT,
    WEIGHT_AXES,
    AxisSignal,
    liquidity_score,
    normalize_weights,
    score_item,
)
from app.domain.affordability.engine import compute_affordability
from app.domain.affordability.models import Borrower, PropertyFacts
from app.domain.listings.dedup import group_duplicates
from app.domain.valuation.models import ListingRow, TradeRow

TODAY = dt.date(2026, 7, 24)
OKU = 100_000_000


# ---------------------------------------------------------------------------
# 매핑 자체 — 축이 어디서 오는지 한 곳에 있고, 프론트와 같은 키를 쓴다
# ---------------------------------------------------------------------------

def test_축_키가_프론트_슬라이더와_같다():
    """서버가 다른 키를 보면 슬라이더는 저장만 되고 영원히 무시된다(이번 버그의 형태)."""
    frontend = (
        __import__("pathlib").Path(__file__).resolve().parents[2]
        / "frontend" / "src" / "lib" / "preferences.ts"
    )
    if not frontend.exists():                      # 백엔드만 체크아웃한 경우
        pytest.skip("프론트 소스가 없는 환경")
    src = frontend.read_text(encoding="utf-8")
    for axis in WEIGHT_AXES:
        assert f"{axis}:" in src, f"프론트 DEFAULT_WEIGHTS 에 {axis} 가 없다"


def test_모든_축에_담당_에이전트와_신호_설명이_있다():
    """'가격 축이 뭘 보는 건데'에 답할 수 없으면 가중치는 그냥 숫자 장난이다."""
    assert set(WEIGHT_AXES) == {AXIS_PRICE, AXIS_LOCATION, AXIS_VALUE, AXIS_RISK}
    for axis, spec in AXIS_SPECS.items():
        assert spec.agent_ids, f"{axis}: 담당 에이전트가 없다"
        assert spec.signal, f"{axis}: 어떤 신호인지 설명이 없다"
        if spec.coverage == "partial":
            # 부분 커버면 **무엇이 빠졌는지** 반드시 적혀 있어야 한다.
            assert spec.coverage_gap, f"{axis}: partial 인데 빠진 범위 설명이 없다"


def test_리스크축은_미구현_범위를_숨기지_않는다():
    """risk-auditor(권리관계·깡통전세)는 2차 기능이다. 있는 척하면 안 된다."""
    gap = AXIS_SPECS[AXIS_RISK].coverage_gap
    assert "risk-auditor" in gap and "2차" in gap


# ---------------------------------------------------------------------------
# 가중치 정규화 — 클라이언트를 믿지 않는다
# ---------------------------------------------------------------------------

def test_가중치는_합1로_정규화된다():
    w, unknown = normalize_weights({"price": 3, "value": 1})
    assert unknown == []
    assert w == {"price": 0.75, "value": 0.25}
    assert sum(w.values()) == pytest.approx(1.0)


def test_음수_NaN_은_버린다():
    w, ignored = normalize_weights({"price": -5, "value": float("nan"), "risk": 2})
    assert w == {"risk": 1.0}
    # NaN 은 "안 본다"가 아니라 **못 쓴 값**이다 — 조용히 삼키지 않고 보고한다.
    assert ignored == ["value"]
    # 음수/0 은 "이 축은 안 본다"는 정상 입력이라 보고 대상이 아니다.
    assert "price" not in ignored


def test_전부_0이면_빈_가중치다():
    assert normalize_weights({"price": 0, "location": 0})[0] == {}
    assert normalize_weights({})[0] == {}
    assert normalize_weights(None)[0] == {}


def test_모르는_키는_버리되_조용히_버리지_않는다():
    """한글 키('가격') 등으로 저장돼 있으면 사용자는 반영된 줄 안다 — 목록으로 돌려준다."""
    w, ignored = normalize_weights({"가격": 0.5, "price": 0.5})
    assert w == {"price": 1.0}
    assert ignored == ["가격"]


# ---------------------------------------------------------------------------
# 가치 축 — 환금성 점수
# ---------------------------------------------------------------------------

def _liq_at(n: int, households: int):
    """거래 n 건 / 세대수 households 의 환금성. 경계를 실측으로 찾기 위한 도구."""
    from app.domain.valuation.stats import liquidity

    trades = [TradeRow(contract_date=TODAY - dt.timedelta(days=i % 300),
                       price_krw=7 * OKU, area_m2=84.0, floor=5) for i in range(n)]
    return liquidity(trades, [], households, as_of=TODAY)


def test_환금성_만점_기준이_좋음_등급_경계와_같다():
    """점수와 등급이 다른 경계를 쓰면 rationale('환금성 보통')과 순위가 서로 다른 말을 한다.

    ⚠️ 예전 판(SCORE-1)은 `TURNOVER_FULL_SCORE_PCT` 로 **데이터를 만들어** 그 지점을 검사했다.
    상수를 5→9 로 바꾸면 데이터도 9% 로 따라 움직여 **자기참조라 항상 통과**했다
    (그러면 회전율 5% 단지가 rationale 은 '좋음'인데 점수는 55.6 이 되는 불일치가 생긴다).
    이제 **도메인 쪽 등급 경계를 실측으로 찾아** 그 지점의 점수가 만점인지 본다 —
    어느 쪽 상수를 건드려도 걸린다.
    """
    households = 10_000

    # stats.liquidity() 가 '좋음' 을 주기 시작하는 최소 거래건수를 이분탐색으로 찾는다.
    lo, hi = 0, households
    assert _liq_at(hi, households).grade == "좋음", "상한에서도 '좋음' 이 아니다 — 전제 붕괴"
    while lo < hi:
        mid = (lo + hi) // 2
        if _liq_at(mid, households).grade == "좋음":
            hi = mid
        else:
            lo = mid + 1
    boundary = _liq_at(lo, households)

    assert boundary.grade == "좋음"
    assert liquidity_score(boundary) == 100.0, (
        f"등급 '좋음' 이 시작되는 회전율 {boundary.turnover_12m_pct}% 에서 점수가 만점이 아니다 "
        f"({liquidity_score(boundary)}) — TURNOVER_FULL_SCORE_PCT"
        f"({TURNOVER_FULL_SCORE_PCT})와 도메인 등급 경계가 어긋났다"
    )


def test_세대수를_모르면_환금성_점수를_만들지_않는다():
    from app.domain.valuation.stats import liquidity

    liq = liquidity([], [], None, as_of=TODAY)
    assert liquidity_score(liq) is None, "회전율을 모르는데 점수를 지어냈다"


# ---------------------------------------------------------------------------
# 총점 계산 규칙
# ---------------------------------------------------------------------------

def _sig(axis, score, conf=0.8, missing=()):
    return AxisSignal(axis=axis, score=score, confidence=conf, missing=tuple(missing))


def _signals(price=None, location=None, value=None, risk=None):
    return {
        AXIS_PRICE: _sig(AXIS_PRICE, price, missing=() if price is not None else ("호가 없음",)),
        AXIS_LOCATION: _sig(AXIS_LOCATION, location,
                            missing=() if location is not None else ("입지 데이터 미수집",)),
        AXIS_VALUE: _sig(AXIS_VALUE, value, missing=() if value is not None else ("세대수 없음",)),
        AXIS_RISK: _sig(AXIS_RISK, risk, missing=() if risk is not None else ("호가 없음",)),
    }


def _finding(score, conf=0.8, agent="x"):
    return Finding(agent_id=agent, verdict="v", rationale="r",
                   evidence=[Evidence(claim="c", source="s")], score=score, confidence=conf)


def test_가중치대로_곱해진다():
    res = score_item(findings=[_finding(80)],
                     signals=_signals(price=100, value=0),
                     weights={AXIS_PRICE: 0.75, AXIS_VALUE: 0.25})
    assert res.basis == BASIS_USER_WEIGHTED
    assert res.total == 75.0                    # 100×0.75 + 0×0.25
    assert res.coverage_pct == 100.0


def test_근거없는_축은_빼고_재정규화한다():
    """입지 30%에 근거가 없으면 가격 70%가 100%가 된다 — 0점 처리(=나쁨)가 아니다."""
    res = score_item(findings=[_finding(10)],
                     signals=_signals(price=60, location=None),
                     weights={AXIS_PRICE: 0.7, AXIS_LOCATION: 0.3})
    assert res.total == 60.0                    # 0점 처리였다면 42.0 이 나온다
    assert res.coverage_pct == 70.0
    rows = {r["axis"]: r for r in res.axes}
    assert rows[AXIS_PRICE]["status"] == STATUS_APPLIED
    assert rows[AXIS_PRICE]["applied_weight"] == 1.0
    assert rows[AXIS_LOCATION]["status"] == STATUS_NO_SIGNAL
    assert rows[AXIS_LOCATION]["missing"] == ["입지 데이터 미수집"]


def test_빠진_가중치는_비율과_사유로_고지된다():
    res = score_item(findings=[_finding(10)],
                     signals=_signals(price=60, location=None),
                     weights={AXIS_PRICE: 0.7, AXIS_LOCATION: 0.3})
    joined = " ".join(res.notes)
    assert "입지 가중치 30%가 반영되지 않았습니다" in joined
    assert "입지 데이터 미수집" in joined


def test_가중치_축에_근거가_없으면_0이_아니라_None():
    """사용자가 0 을 준 축의 점수로 총점을 만들면 그건 사용자 질문에 대한 답이 아니다."""
    res = score_item(findings=[_finding(90)],           # 다른 축엔 점수가 있다
                     signals=_signals(location=None, price=90),
                     weights={AXIS_LOCATION: 1.0})
    assert res.total is None and res.basis is None
    assert any("점수를 매기지 않았습니다" in n for n in res.notes)


def test_가중치가_없으면_기존동작으로_폴백하고_그_사실을_남긴다():
    res = score_item(findings=[_finding(80, conf=0.5), _finding(40, conf=0.5)],
                     signals=_signals(price=80), weights={})
    assert res.basis == BASIS_AGENT_SCORES
    assert res.total == 60.0                    # 신뢰도 가중 평균(기존 동작)
    assert any("가중치가 없어" in n for n in res.notes)


def test_폴백에서도_근거가_없으면_None이다():
    res = score_item(findings=[_finding(None)], signals=_signals(), weights={})
    assert res.total is None and res.basis is None


# ---------------------------------------------------------------------------
# ★ 핵심: 파이프라인에서 **순위가 실제로 바뀐다**
# ---------------------------------------------------------------------------

def _trades(n, price_oku, area=84.97, days_step=15):
    return [TradeRow(contract_date=TODAY - dt.timedelta(days=days_step * i),
                     price_krw=int(price_oku * OKU), area_m2=area, floor=10)
            for i in range(n)]


def _cand(*, cid, name, ask_oku, median_oku, households, n_trades=8):
    listing = ListingRow(id=cid * 10, ask_price_krw=int(ask_oku * OKU), area_m2=84.97,
                         floor=10, listed_at=TODAY - dt.timedelta(days=10),
                         collected_at=TODAY, agency="A", status="active")
    return Candidate(
        complex_id=cid, complex_name=name, unit_type_id=None, area_m2=84.97,
        group=group_duplicates([listing])[0],
        trades=_trades(n_trades, median_oku),
        total_households=households, listings=[listing])


#: A: 호가가 적정가와 같다(가격 축 만점) · 대단지라 회전율이 낮다(가치 축 바닥)
#: B: 호가가 적정가보다 비싸다(가격 축 낮음) · 소단지라 회전율이 높다(가치 축 만점)
#: → 두 축은 **정확히 반대 순서**다. 가중치가 무시되면 두 시나리오의 1위가 같아진다.
def _two_candidates():
    a = _cand(cid=1, name="가격우위단지", ask_oku=7.0, median_oku=7.0, households=4000)
    b = _cand(cid=2, name="환금성우위단지", ask_oku=7.7, median_oku=7.0, households=100)
    return [a, b]


def _ctx(candidates, weights):
    from pathlib import Path

    from app.domain.rules.loader import load_rules
    rules = load_rules(Path(__file__).parent / "fixtures" / "tax_rules_test.yaml")
    afford = compute_affordability(
        Borrower(cash_krw=10 * OKU, annual_income_krw=3 * OKU), rules,
        prop=PropertyFacts(area_m2=84.0))
    return AnalysisContext(affordability=afford, candidates=candidates,
                           weights=weights, as_of=TODAY)


def _ranked(weights):
    out = run_mvp_pipeline(_ctx(_two_candidates(), weights), llm=None)
    return out, [it["complex"]["name"] for it in out["items"]]


def test_가격100과_가치100은_1위가_다르다():
    """★ 이 테스트가 '가중치가 실제로 순위를 바꾼다'의 증명이다.

    가중치 곱셈을 지우고 신뢰도 평균으로 되돌리면 두 목록이 같아져 여기서 깨진다.
    """
    _, price_first = _ranked({AXIS_PRICE: 1.0})
    _, value_first = _ranked({AXIS_VALUE: 1.0})

    assert price_first[0] == "가격우위단지", price_first
    assert value_first[0] == "환금성우위단지", value_first
    assert price_first != value_first, "가중치를 바꿨는데 순위가 같다 — 반영되지 않은 것이다"


def test_가중치를_섞으면_총점도_그_사이에_있다():
    """1위만 뒤집히는 게 아니라 **총점 자체가 가중치에 반응**해야 한다."""
    def total_of(weights, name):
        out, _ = _ranked(weights)
        return next(it["total_score"] for it in out["items"]
                    if it["complex"]["name"] == name)

    pure_price = total_of({AXIS_PRICE: 1.0}, "가격우위단지")
    pure_value = total_of({AXIS_VALUE: 1.0}, "가격우위단지")
    half = total_of({AXIS_PRICE: 0.5, AXIS_VALUE: 0.5}, "가격우위단지")

    assert pure_value < half < pure_price, (pure_value, half, pure_price)
    assert half == pytest.approx(round((pure_price + pure_value) / 2, 1), abs=0.1)


def test_입지_가중치는_데이터가_없어_반영되지_않는다고_말한다():
    """입지 100% → 근거가 없으니 점수를 만들지 않고, **왜 없는지**를 응답에 남긴다."""
    out, _ = _ranked({AXIS_LOCATION: 1.0})

    assert all(it["total_score"] is None for it in out["items"])
    notes = " ".join(out["notes"])
    assert "입지 가중치 100%가" in notes and "반영되지 않았습니다" in notes
    assert "미수집" in notes

    item_notes = " ".join(out["items"][0]["score_notes"])
    assert "입지 가중치 100%가 반영되지 않았습니다" in item_notes
    axes = {r["axis"]: r for r in out["items"][0]["score_axes"]}
    assert axes[AXIS_LOCATION]["status"] == STATUS_NO_SIGNAL
    assert axes[AXIS_LOCATION]["weight"] == 1.0


def test_리스크_가중치를_주면_안_보는_범위를_반영여부와_무관하게_말한다():
    """"호가가 없어 반영 못 했다"로만 끝나면 사용자는 '호가만 오면 리스크가 다 반영된다'고
    읽는다. risk-auditor(권리관계·깡통전세)가 **애초에 없다**는 사실이 가려진다."""
    out, _ = _ranked({AXIS_RISK: 1.0})
    joined = " ".join(out["notes"]) + " ".join(out["items"][0]["score_notes"])
    assert "risk-auditor" in joined and "2차" in joined

    # 반영된 경우(호가가 있어 매물 신뢰도가 살아 있는 경우)에도 같은 고지가 나온다.
    axes = {r["axis"]: r for r in out["items"][0]["score_axes"]}
    assert axes[AXIS_RISK]["status"] == STATUS_APPLIED
    assert axes[AXIS_RISK]["coverage"] == "partial"
    assert axes[AXIS_RISK]["coverage_gap"]


def test_반영조차_못한_축도_안_보는_범위를_말한다():
    """호가가 0건이면 리스크 축은 아예 반영되지 않는다. 그때도 "권리관계는 애초에 안 본다"를
    말해야 한다 — 그러지 않으면 '데이터만 모이면 다 된다'는 잘못된 기대가 남는다."""
    trade_only = Candidate(
        complex_id=9, complex_name="호가없는단지", unit_type_id=None, area_m2=84.97,
        group=None, trades=_trades(8, 7.0), total_households=500, listings=[])
    out = run_mvp_pipeline(_ctx([trade_only], {AXIS_RISK: 1.0}), llm=None)

    top = out["items"][0]
    axes = {r["axis"]: r for r in top["score_axes"]}
    assert axes[AXIS_RISK]["status"] == STATUS_NO_SIGNAL      # 반영 안 됨

    # 목록 전체 고지와 후보별 고지 **양쪽**에 있어야 한다. 한쪽에만 있으면
    # 화면 구성에 따라 사용자가 영영 못 보는 경로가 생긴다.
    assert any("risk-auditor" in n for n in out["notes"]), out["notes"]
    assert any("risk-auditor" in n for n in top["score_notes"]), top["score_notes"]


def test_기본_가중치는_근거있는_축만_반영하고_비율을_고지한다():
    """프론트 기본값(가격 30·입지 30·가치 25·리스크 15)으로 돌렸을 때."""
    out, _ = _ranked({AXIS_PRICE: 0.3, AXIS_LOCATION: 0.3,
                      AXIS_VALUE: 0.25, AXIS_RISK: 0.15})
    top = out["items"][0]

    assert top["score_basis"] == BASIS_USER_WEIGHTED
    # 입지만 근거가 없다 → 70% 반영
    assert top["score_coverage_pct"] == 70.0
    notes = " ".join(out["notes"])
    assert "조건 가중치를 순위에 반영했습니다" in notes
    assert "입지 30%" in notes


def test_가중치가_없으면_기존_순위규칙_그대로다():
    """가중치를 안 준 사용자에게 동작이 바뀌면 안 된다(회귀 방지)."""
    out, names = _ranked({})
    assert out["items"][0]["score_basis"] == BASIS_AGENT_SCORES
    assert names[0] == "가격우위단지"          # 신뢰도 가중 평균 기준
    assert any("가중치가 없어" in n for n in out["notes"])


def test_알수없는_가중치키는_notes에_남는다():
    out, _ = _ranked({"가격": 1.0})
    assert any("가격" in n and "무시했습니다" in n for n in out["notes"]), out["notes"]
    # 쓸 수 있는 가중치가 하나도 없으므로 기존 동작으로 폴백한다.
    assert out["items"][0]["score_basis"] == BASIS_AGENT_SCORES
