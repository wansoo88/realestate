"""화면마다 다른 가격 (CR34-3) — **무엇이 같아야 하고 무엇이 달라도 되는지**를 고정한다.

이 파일이 지키는 명제는 세 개다.

1. **지도와 추천은 다른 양이다. 다르게 나오는 게 맞다.**
   지도는 *실제로 체결된 최근 1건*, 추천은 *창 중위를 기준월로 환산한 추정가*다.
   운영 DB 실측(2026-07-28 · 226단지 · 같은 단지·같은 면적)으로 격차를 분해했다:
       A 정의 차이(최근 1건 vs 창 중위)  중위 −3.7% · p10 −18.8% · |중위| 5.8%
       B 시점 보정(창 중위 → 기준월)     중위 +1.7% · p10  −3.1% · |중위| 3.4%
       **67% 의 단지에서 |A| > |B|** — 지도를 보정해도 두 값은 A 만큼 여전히 다르다.
   그래서 값을 맞추는 대신 **각자 무엇인지 말하게** 한다(`price_basis`).

2. **자금계획은 추천과 같아야 한다. 그건 가능하다.**
   단지 1건·면적 1개라 밴드를 그대로 낼 수 있다. 그래서 `complex_reference_price`
   가 추천이 쓰는 `reference_band` 를 **그대로** 부른다. 두 값이 갈리면 실패한다.

3. **지도 가격은 사용자의 면적 조건 안에서 고른다.**
   실측: 서울에서 55~65㎡ 를 가진 단지 400곳에 그 필터를 걸었을 때 **176곳(44%)** 의
   표시가가 조건 밖 면적의 거래였고, 조건 안 최근 거래와 **평균 26.8%**(최대 168.6%)
   어긋났다. 이것이 이 라운드에서 가장 큰 격차였다 — 시점 보정(3.4%)보다 훨씬 크다.

각 테스트에 **변이**를 적는다. 그 줄을 되돌렸을 때 여기서 잡히는지 직접 확인했다.
"""
from __future__ import annotations

import datetime as dt

import pytest

from app.agents.orchestrator import (
    Candidate,
    reference_band,
    trade_basis_note,
)
from app.agents.recommend import (
    PRICE_BASIS_TIME_ADJUSTED,
    PRICE_BASIS_TRADE_BAND,
    complex_reference_price,
)
from app.domain.valuation.models import TradeRow
from app.domain.valuation.timeadjust import (
    MIN_REFERENCE_MONTH_SAMPLE,
    IndexPoint,
    MarketIndex,
)

TODAY = dt.date(2026, 7, 28)
OKU = 100_000_000
AREA = 84.97
REGION = "1168010100"

RISING = {
    "2025-08": 0.95, "2025-09": 0.96, "2025-10": 0.97, "2025-11": 0.98,
    "2025-12": 0.99, "2026-01": 1.00, "2026-02": 1.01, "2026-03": 1.02,
    "2026-04": 1.04, "2026-05": 1.05, "2026-06": 1.06, "2026-07": 1.07,
}


def _index(region: str = "11680", scope: str = "sigungu") -> MarketIndex:
    return MarketIndex(region_code=region, scope=scope, points={
        ym: IndexPoint(ym=ym, value=v, sample_size=MIN_REFERENCE_MONTH_SAMPLE,
                       is_complete=ym < "2026-07")
        for ym, v in RISING.items()
    })


def _trades(price_oku: float = 10.0, *, area: float = AREA,
            months: tuple[int, ...] = (1, 3, 5, 7, 9, 11)) -> list[TradeRow]:
    """명목가가 전부 같은 거래. 중위가 움직이면 원인은 시점 보정뿐이다."""
    return [
        TradeRow(contract_date=TODAY - dt.timedelta(days=30 * m),
                 price_krw=int(price_oku * OKU), area_m2=area, floor=10)
        for m in months
    ]


class _Repo:
    """자금계획 경로가 실제로 부르는 메서드만 가진 최소 리포지토리."""

    def __init__(self, trades, *, region_code=REGION, index=None,
                 with_index=True, raise_on_trades=False):
        self._trades = trades
        self._region = region_code
        self._index = index if index is not None else _index()
        self._raise = raise_on_trades
        if with_index:
            # 인스턴스 속성으로 붙인다 — `with_index=False` 면 `getattr(repo,
            # "market_index", None)` 이 None 을 돌려줘 '조회조차 못 함' 경로가 된다.
            self.market_index = self._market_index

    def trades_for_complex(self, complex_id: int):
        if self._raise:
            raise RuntimeError("DB 끊김")
        return list(self._trades)

    def complex_region_code(self, complex_id: int):
        return self._region

    def _market_index(self, region_code: str, scope: str):
        return self._index


# ---------------------------------------------------------------------------
# 1. 자금계획 == 추천 (같아야 하는 쪽)
# ---------------------------------------------------------------------------

def test_자금계획_기준가가_추천_카드와_같은_값이다():
    """★ 핵심. 변이: `complex_reference_price` 가 `reference_band` 대신 밴드를 다시
    구현하거나(예: `fair_price_band(..., index=None)`) 지수를 안 넘기면 값이 갈려 잡힌다."""
    trades = _trades()
    ref = complex_reference_price(_Repo(trades), 1, AREA, as_of=TODAY)

    cand = Candidate(complex_id=1, complex_name="", unit_type_id=None,
                     area_m2=AREA, region_code=REGION, trades=trades)
    card = reference_band(cand, TODAY, indexes={"11680": _index()})

    assert card.available and card.median_krw is not None
    assert ref.krw == card.median_krw, "자금계획과 추천 카드가 다른 금액을 말하면 안 된다"
    assert ref.basis == PRICE_BASIS_TIME_ADJUSTED
    assert ref.as_of_ym == card.as_of_label == "2026-06"


def test_보정을_못하면_그_사실이_기준가에_남는다():
    """지수가 비면 값은 나오되 **어느 시점도 아니라는 사실**이 basis·reason 에 남는다.

    변이: basis 를 항상 `time_adjusted_band` 로 두면 잡힌다."""
    empty = MarketIndex(region_code="11680", scope="sigungu", points={})
    ref = complex_reference_price(_Repo(_trades(), index=empty), 1, AREA, as_of=TODAY)

    assert ref.krw is not None
    assert ref.basis == PRICE_BASIS_TRADE_BAND
    assert ref.as_of_ym is None
    assert ref.reason, "보정을 못 했으면 왜 못 했는지가 반드시 남아야 한다"


def test_실거래가_아예_없으면_금액을_지어내지_않는다():
    """자금계획은 이 값을 자산으로 나눈다 — 없으면 없다고 해야 한다."""
    ref = complex_reference_price(_Repo([]), 1, AREA, as_of=TODAY)
    assert ref.krw is None
    assert ref.basis is None
    assert ref.reason


def test_표본이_모자라_밴드를_못_만들면_금액이_없다():
    """★ 위 테스트와 **다른 분기**다. 거래는 있는데 그 면적 표본이 최소치(5건) 미만인
    경우 — `fair_price_band` 가 `available=False` 로 돌아오는 길이다.

    변이 검사에서 이 구멍이 드러났다: `krw=None` 을 `krw=0` 으로 바꿔도 위 테스트는
    초록이었다(거래 0건이라 그 줄에 닿지도 않는다). 그래서 분기를 직접 태운다.

    변이: 밴드 미가용 분기에서 `krw=0`(또는 최근 거래가)으로 채우면 잡힌다.
    """
    few = _trades(months=(1, 3, 5))          # 3건 — MIN_SAMPLE(5) 미만
    ref = complex_reference_price(_Repo(few), 1, AREA, as_of=TODAY)

    assert ref.krw is None, "표본이 모자란데 금액을 만들면 안 된다"
    assert ref.sample_size == 3              # 몇 건이었는지는 말한다
    assert ref.reason and "미달" in ref.reason


def test_조회_실패가_추천_전체를_죽이지_않고_사유로_남는다():
    """변이: `except` 를 지우면 500 이 되어 잡힌다(자금계획 화면 전체가 죽는다)."""
    ref = complex_reference_price(_Repo(_trades(), raise_on_trades=True), 1, AREA,
                                  as_of=TODAY)
    assert ref.krw is None
    assert ref.reason


def test_지수_조회_경로가_없으면_시도조차_안했다고_말한다():
    """`market_index` 가 없는 리포지토리 = 배선 미완. **보정 안 함**과 구분한다.

    변이: `load_market_indexes` 가 None 대신 {} 를 주면 사유 문구가 바뀌어 잡힌다."""
    ref = complex_reference_price(_Repo(_trades(), with_index=False), 1, AREA,
                                  as_of=TODAY)
    assert ref.basis == PRICE_BASIS_TRADE_BAND
    assert "시도하지 않았습니다" in (ref.reason or "")


def test_지역코드를_모르면_보정하지_않고_계속_간다():
    """변이: region_code 가 None 일 때 예외가 나거나 임의 지역 지수를 쓰면 잡힌다."""
    ref = complex_reference_price(_Repo(_trades(), region_code=None), 1, AREA,
                                  as_of=TODAY)
    assert ref.krw is not None
    assert ref.basis == PRICE_BASIS_TRADE_BAND


# ---------------------------------------------------------------------------
# 2. 문구 — 이 금액이 언제 시점인지 말하는가 (CR34-5)
# ---------------------------------------------------------------------------

def test_실거래_기준_문구가_환산_시점을_말한다():
    """변이: `price_note` 를 `TRADE_BASIS_NOTE` 상수로 되돌리면 기준월이 사라져 잡힌다."""
    cand = Candidate(complex_id=1, complex_name="", unit_type_id=None,
                     area_m2=AREA, region_code=REGION, trades=_trades())
    band = reference_band(cand, TODAY, indexes={"11680": _index()})
    note = trade_basis_note(band)

    assert "2026-06" in note
    assert "환산" in note
    assert note.startswith("현재 등록된 매물이 없습니다")   # 기존 문구를 잃지 않는다


def test_추천_결과의_price_note_가_실제로_시점을_말한다():
    """★ **배선**을 고정한다. 위 테스트는 함수만 본다 — 함수가 옳아도 파이프라인이
    옛 상수를 쓰면 화면에는 아무것도 안 바뀐다.

    실제로 변이 검사에서 그 구멍이 드러났다: `price_note` 를 `TRADE_BASIS_NOTE` 로
    되돌려도 함수 테스트는 초록이었다. 그래서 파이프라인 산출물을 직접 본다.

    변이: `trade_basis_note(band)` → `TRADE_BASIS_NOTE` 로 되돌리면 여기서 잡힌다.
    """
    from pathlib import Path

    from app.agents.orchestrator import AnalysisContext, run_mvp_pipeline
    from app.domain.affordability.engine import compute_affordability
    from app.domain.affordability.models import Borrower, PropertyFacts
    from app.domain.rules.loader import load_rules

    rules = load_rules(Path(__file__).parent / "fixtures" / "tax_rules_test.yaml")
    afford = compute_affordability(
        Borrower(cash_krw=99 * OKU, annual_income_krw=100_000_000),
        rules, prop=PropertyFacts(area_m2=84.0))
    cand = Candidate(complex_id=1, complex_name="○○아파트", unit_type_id=None,
                     area_m2=AREA, region_code=REGION, group=None,
                     trades=_trades(), total_households=500, listings=[])
    ctx = AnalysisContext(affordability=afford, candidates=[cand], as_of=TODAY,
                          market_indexes={"11680": _index()},
                          budget_krw=99 * OKU)

    item = run_mvp_pipeline(ctx, llm=None)["items"][0]

    assert item["price_basis"] == "trade"          # 호가 없는 후보
    assert "2026-06" in item["price_note"], "카드 문구가 어느 시점 값인지 말하지 않는다"


def test_보정_못한_후보의_문구는_시점이_없다고_말한다():
    """★ 조용히 넘어가면 안 되는 쪽. 변이: 두 갈래를 한 문장으로 합치면 잡힌다."""
    raw = reference_band(
        Candidate(complex_id=1, complex_name="", unit_type_id=None, area_m2=AREA,
                  region_code=REGION, trades=_trades()), TODAY)
    note = trade_basis_note(raw)

    assert "특정 시점의 가격이 아닙니다" in note
    assert "환산" not in note


def test_보정된_밴드의_출처는_국토부라고만_부르지_않는다():
    """CR34-5 ①. 이 숫자는 국토부 발표값이 아니라 거기에 우리 지수를 곱한 값이다.

    변이: `source_label = source` 로 되돌리면 잡힌다."""
    cand = Candidate(complex_id=1, complex_name="", unit_type_id=None,
                     area_m2=AREA, region_code=REGION, trades=_trades())
    band = reference_band(cand, TODAY, indexes={"11680": _index()})
    ev = band.to_evidence(as_of=TODAY)[0]

    assert ev["source"] != "국토교통부 실거래가"
    assert "자체 시장지수" in ev["source"]
    assert "국토교통부 실거래가" in ev["source"]      # 원 출처도 지우지 않는다


def test_보정하지_않은_밴드의_출처는_원본_그대로다():
    """★ 반대 방향. 보정 안 한 값에 '자체 시장지수'를 붙이면 그게 거짓말이다."""
    raw = reference_band(
        Candidate(complex_id=1, complex_name="", unit_type_id=None, area_m2=AREA,
                  region_code=REGION, trades=_trades()), TODAY)
    ev = raw.to_evidence(as_of=TODAY)[0]
    assert ev["source"] == "국토교통부 실거래가"


# ---------------------------------------------------------------------------
# 3. 30일은 신고기한이지 공개 지연이 아니다 (CR34-4)
# ---------------------------------------------------------------------------

def test_신고지연_문구가_30일을_상한처럼_말하지_않는다():
    """변이: "신고까지 최대 30일이 걸려" 로 되돌리면 잡힌다.

    30일은 **신고기한**이고, 그 뒤에 공개까지 시간이 더 걸린다. 30일을 지연의
    상한처럼 말하면 사용자는 31일 전 거래는 다 들어와 있다고 읽는다."""
    from app.agents.orchestrator import DELAY_RISK

    text = DELAY_RISK.detail
    assert "최대 30일" not in text
    assert "30일 이내에 신고" in text
    assert "공개까지는 시간이 더" in text


# ---------------------------------------------------------------------------
# 4. API 계약 — 화면이 두 값을 구분할 수 있는가
# ---------------------------------------------------------------------------

def _client(monkeypatch):
    """`test_api.py` 와 같은 방식의 인메모리 클라이언트."""
    from pathlib import Path

    from fastapi.testclient import TestClient

    fixtures = Path(__file__).parent / "fixtures"
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "k" * 32)
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    monkeypatch.setenv("TAX_RULES_PATH", str(fixtures / "tax_rules_test.yaml"))

    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.main import create_app
    from app.repositories.memory import InMemoryRepository

    repo = InMemoryRepository()
    client = TestClient(create_app(repo=repo))
    client.repo = repo
    return client


def _login(client, email="p@q.co") -> dict[str, str]:
    pw = "correct horse battery staple"
    assert client.post("/api/v1/auth/register",
                       json={"email": email, "password": pw}).status_code == 201
    user = client.repo.get_user_by_email(email)
    client.repo.set_user_status(user.id, "approved", actor="cli")
    token = client.post("/api/v1/auth/login",
                        json={"email": email, "password": pw}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def api(monkeypatch):
    from app.core.config import get_settings

    with _client(monkeypatch) as c:
        yield c
    get_settings.cache_clear()


def test_지도_응답이_자기_금액이_무엇인지_말한다(api):
    """★ CR34-3 의 최소 계약. 화면이 두 값을 구분하려면 서버가 이름을 줘야 한다.

    변이: `price_basis`·`price_area_m2`·`price_basis_note` 중 하나라도 빼면 잡힌다.
    """
    from app.repositories.base import ComplexSummary

    auth = _login(api)
    api.repo.add_complex(ComplexSummary(
        id=1, name="단지", lon=127.05, lat=37.51, region_code="1168000000",
        recent_price_krw=1_940_000_000, price_as_of="2026-07-04",
        price_area_m2=84.97))

    body = api.get("/api/v1/map/complexes",
                   params={"bbox": "126.9,37.4,127.1,37.6", "zoom": 15},
                   headers=auth).json()

    item = body["items"][0]
    assert item["price_basis"] == "latest_trade"
    assert item["price_area_m2"] == pytest.approx(84.97)
    # 추천 카드와 다른 값이라는 사실을 **서버가** 말한다(프론트가 문구를 만들지 않는다).
    assert "추천 카드" in body["price_basis_note"]
    assert "실제로 체결된 최근 1건" in body["price_basis_note"]


def test_금액이_없으면_근거도_없다(api):
    """변이: `price_basis` 를 무조건 상수로 두면 금액 없는 항목에도 근거가 붙어 잡힌다."""
    from app.repositories.base import ComplexSummary

    auth = _login(api)
    api.repo.add_complex(ComplexSummary(
        id=1, name="거래없음", lon=127.05, lat=37.51, region_code="1168000000",
        recent_price_krw=None, price_as_of=None, price_area_m2=None))

    item = api.get("/api/v1/map/complexes",
                   params={"bbox": "126.9,37.4,127.1,37.6", "zoom": 15},
                   headers=auth).json()["items"][0]
    assert item["price_basis"] is None
    assert item["price_confidence"] == "unknown"


def test_군집_응답에도_같은_근거_이름이_붙는다(api):
    """변이: 군집만 빠뜨리면 줌아웃 화면에서 근거가 사라져 잡힌다."""
    from app.repositories.base import ComplexSummary

    auth = _login(api)
    for i in (1, 2):
        api.repo.add_complex(ComplexSummary(
            id=i, name=f"단지{i}", lon=127.05, lat=37.51, region_code="1168000000",
            recent_price_krw=1_000_000_000 * i, price_as_of="2026-07-04"))

    body = api.get("/api/v1/map/complexes",
                   params={"bbox": "126.9,37.4,127.1,37.6", "zoom": 10},
                   headers=auth).json()
    assert body["level"] == "cluster"
    assert body["items"][0]["price_basis"] == "latest_trade"
    assert "price_basis_note" in body


def _put_profile(api, auth) -> None:
    r = api.put("/api/v1/me/profile", headers=auth,
                json={"cash_krw": 500_000_000, "income_krw": 100_000_000})
    assert r.status_code == 200, r.text


def test_자금계획이_클라이언트_금액의_근거를_모른다고_말한다(api):
    """★ 사용자 자산으로 나눗셈하는 값이다. 서버가 모르면 **모른다고** 해야 한다.

    변이: `target_price` 블록을 빼면 화면은 그 20.7억이 어디서 온 값인지 알 수 없다.
    """
    auth = _login(api)
    _put_profile(api, auth)

    body = api.post("/api/v1/affordability", headers=auth,
                    json={"target_price_krw": 2_070_000_000}).json()

    assert body["target_price"]["krw"] == 2_070_000_000
    assert body["target_price"]["basis"] == "client_supplied"
    assert any("근거를 확인하지 않았습니다" in a for a in body["assumptions"])
    assert "plan" in body                       # 계획 자체는 예전대로 나온다


def test_자금계획이_단지id로_추천과_같은_기준가를_만든다(api):
    """★ CR34-3 의 본론. 화면이 단지를 주면 서버가 **추천과 같은 값**을 쓴다.

    변이: `complex_reference_price` 대신 최근 체결가를 쓰면 basis 가 달라져 잡힌다.
    """
    auth = _login(api)
    _put_profile(api, auth)

    trades = _trades(price_oku=10.0)
    api.repo.trades_for_complex = lambda cid: list(trades)
    api.repo.complex_region_code = lambda cid: REGION
    api.repo.market_index = lambda code, scope: _index()

    body = api.post("/api/v1/affordability", headers=auth,
                    json={"complex_id": 1, "area_m2": AREA}).json()

    cand = Candidate(complex_id=1, complex_name="", unit_type_id=None,
                     area_m2=AREA, region_code=REGION, trades=trades)
    expected = reference_band(cand, dt.date.today(),
                              indexes={"11680": _index()}).median_krw

    assert body["target_price"]["krw"] == expected
    assert body["target_price"]["basis"] == PRICE_BASIS_TIME_ADJUSTED
    assert body["target_price"]["as_of_ym"] == "2026-06"
    assert body["plan"]["target_price_krw"] == expected
    assert any("시점으로 환산한 추정가" in a for a in body["assumptions"])


def test_기준가를_못만들면_계획을_만들지_않고_이유를_말한다(api):
    """★ 조용한 실패 금지. 변이: reason 을 안 실으면 "왜 계획이 없지"에 답이 없다."""
    auth = _login(api)
    _put_profile(api, auth)
    api.repo.trades_for_complex = lambda cid: []
    api.repo.complex_region_code = lambda cid: REGION

    body = api.post("/api/v1/affordability", headers=auth,
                    json={"complex_id": 999, "area_m2": AREA}).json()

    assert body["target_price"]["krw"] is None
    assert body["target_price"]["reason"]
    assert "plan" not in body, "가격이 없으면 계획도 없다(0 으로 만들지 않는다)"
    assert any("자금계획" in a and "만들지 않았습니다" in a for a in body["assumptions"])


def test_희망가를_직접_주면_서버가_덮어쓰지_않는다(api):
    """슬라이더가 말을 듣지 않는 화면을 만들지 않는다.

    변이: complex_id 를 우선하게 바꾸면 사용자가 넣은 30억이 사라져 잡힌다."""
    auth = _login(api)
    _put_profile(api, auth)
    api.repo.trades_for_complex = lambda cid: list(_trades(price_oku=10.0))
    api.repo.complex_region_code = lambda cid: REGION
    api.repo.market_index = lambda code, scope: _index()

    body = api.post("/api/v1/affordability", headers=auth,
                    json={"complex_id": 1, "area_m2": AREA,
                          "target_price_krw": 3_000_000_000}).json()

    assert body["target_price"]["krw"] == 3_000_000_000
    assert body["target_price"]["basis"] == "client_supplied"


def test_아무것도_안주면_예전_응답_그대로다(api):
    """기존 클라이언트가 깨지지 않는다. 변이: `target_price` 를 항상 실으면 잡힌다."""
    auth = _login(api)
    _put_profile(api, auth)

    body = api.post("/api/v1/affordability", headers=auth, json={}).json()
    assert "target_price" not in body
    assert "plan" not in body
    assert body["max_purchase_krw"] > 0
