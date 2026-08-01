"""사용자 수동 입력 호가가 **추천 파이프라인까지 닿는 경로** (migrations/016 배선).

`test_user_listings.py` 는 CRUD·소유자 스코프·낡음 판정을 본다. 이 파일은 그 다음 —
**저장된 호가가 추천 결과를 어떻게 바꾸는가**를 본다. 지키는 것은 넷이다.

  ① 사용자 입력에 **가짜 신뢰도가 붙지 않는다.** 매물 신뢰도(허위·미끼·중복 등록)는
     제3자가 남긴 흔적을 세는 판정인데, 사람이 손으로 적은 한 건에는 그 흔적이 없다.
     점수를 만들면 **비싼 매물을 입력할수록 총점이 오른다**(아래 실측).
  ② 호가 하나가 **그 단지의 다른 면적대를 지우지 않는다.** 84㎡ 호가를 넣었다고
     59㎡ 실거래 후보가 사라지면, 사용자는 입력할수록 선택지를 잃는다.
  ③ 출처(`ListingRow.source`)가 리포지토리에서 분석 계층까지 **끊기지 않는다.**
  ④ 소유자(`user_id`)가 러너에서 리포지토리까지 **끊기지 않는다.** 리포지토리는
     fail-closed 라 배선을 잊으면 오류가 아니라 **조용한 0건**으로 실패한다.

⚠️ 단언은 전부 **최종 산출물**(`run_mvp_pipeline` 결과 · API 응답)에서 한다.
   함수 단위로만 확인하면 함수는 맞는데 파이프라인이 그 함수를 안 부르는 상태를
   놓친다(직전 라운드에 두 번 적발된 형태다).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.orchestrator import AnalysisContext, Candidate, run_mvp_pipeline
from app.agents.scoring import (
    AXIS_PRICE,
    AXIS_RISK,
    AXIS_SPECS,
    NO_ASK_REASON,
    STATUS_APPLIED,
    STATUS_NO_SIGNAL,
)
from app.domain.affordability.engine import compute_affordability
from app.domain.affordability.models import Borrower, PropertyFacts
from app.domain.listings.dedup import (
    USER_ENTERED_NO_TRUST_REASON,
    group_duplicates,
    trust_score,
)
from app.domain.rules.loader import load_rules
from app.domain.valuation.models import LISTING_SOURCE_USER, ListingRow, TradeRow
from app.repositories.base import ComplexSummary
from app.repositories.memory import InMemoryRepository

FIXTURES = Path(__file__).parent / "fixtures"
PASSWORD = "correct horse battery staple"
REGION = "1168010100"
OKU = 100_000_000
TODAY = dt.date.today()

#: 가격·입지·가치·리스크에 같은 비중. 리스크 축이 살았는지 죽었는지가 총점에 바로 보인다.
EVEN_WEIGHTS = {"price": 0.25, "location": 0.25, "value": 0.25, "risk": 0.25}


# ---------------------------------------------------------------------------
# 파이프라인 직접 호출 (차단 ①) — 출처 말고는 **모든 것이 같은 두 후보**
# ---------------------------------------------------------------------------

def _trades(n=10, price_oku=7.0, area=84.97):
    return [TradeRow(contract_date=TODAY - dt.timedelta(days=15 * i),
                     price_krw=int(price_oku * OKU), area_m2=area, floor=10)
            for i in range(n)]


def _candidate(*, source: str | None, ask_oku: float = 7.65):
    """호가 1건짜리 후보. `source` 만 다르고 나머지는 완전히 같다.

    호가 7.65억 vs 실거래 중위 7.0억 → **적정가보다 +9.3% 비싼 매물**이다.
    이런 매물에 리스크 축 100점이 붙는 것이 이번 결함의 본체다.
    """
    row = ListingRow(
        id=1, ask_price_krw=int(ask_oku * OKU), area_m2=84.97, floor=10,
        # 사용자 입력에는 포털 등록일이 없다(사용자가 모르는 값이다).
        listed_at=None, collected_at=TODAY, agency=None, status="active",
        source=source, as_of=TODAY if source == LISTING_SOURCE_USER else None)
    return Candidate(
        complex_id=1, complex_name="실측단지", unit_type_id=None, area_m2=84.97,
        region_code=REGION, group=group_duplicates([row])[0], trades=_trades(),
        total_households=500, listings=[row])


def _pipeline(source: str | None, weights=None, ask_oku: float = 7.65):
    rules = load_rules(FIXTURES / "tax_rules_test.yaml")
    afford = compute_affordability(
        Borrower(cash_krw=10 * OKU, annual_income_krw=3 * OKU), rules,
        prop=PropertyFacts(area_m2=84.97))
    ctx = AnalysisContext(
        affordability=afford, candidates=[_candidate(source=source, ask_oku=ask_oku)],
        weights=EVEN_WEIGHTS if weights is None else weights, as_of=TODAY,
        # 예산에서 떨어지지 않게 상한을 넉넉히 준다(이 테스트의 관심사가 아니다).
        budget_krw=20 * OKU)
    item = run_mvp_pipeline(ctx, llm=None)["items"][0]
    return item, {row["axis"]: row for row in item["score_axes"]}


def test_사용자_입력_호가에는_매물_신뢰도_점수가_붙지_않는다():
    """★ 차단 ①. **최종 산출물**에서 리스크 축이 미반영인지 본다.

    변이: `trust_score` 의 `user_entered_only` 분기나 `listing_finding` 의 `score is None`
    처리를 지우면 리스크 축이 `applied` 100.0 으로 되살아나 여기서 깨진다.
    """
    item, axes = _pipeline(LISTING_SOURCE_USER)

    assert item["ask_gap_pct"] == pytest.approx(9.29, abs=0.1)  # 적정가보다 비싸다
    risk = axes[AXIS_RISK]
    assert risk["status"] == STATUS_NO_SIGNAL, risk
    assert risk["score"] is None
    assert risk["applied_weight"] == 0.0
    # 왜 못 했는지가 사용자에게 그대로 나간다(조용히 빠지지 않는다).
    assert USER_ENTERED_NO_TRUST_REASON in risk["missing"]

    # listing-researcher 는 '판단 보류'로 남는다 — '정상 매물'이라고 단언하지 않는다.
    finding = next(f for f in item["findings"] if f["agent_id"] == "listing-researcher")
    assert finding["score"] is None and finding["verdict"] == "판단 보류"


def test_같은_호가라도_수집_출처면_신뢰도가_그대로_나온다():
    """★ 갈림길이 **출처 하나**임을 증명한다. 수집 데이터 회귀 방지.

    변이: 분기를 출처가 아닌 다른 것(예: as_of 유무)으로 바꾸면 이 쪽이 깨진다.
    """
    item, axes = _pipeline(None)          # source 미상 = 수집으로 취급
    risk = axes[AXIS_RISK]
    assert risk["status"] == STATUS_APPLIED, risk
    assert risk["score"] == 100.0
    assert risk["missing"] == []


def test_비싼_호가를_직접_입력해도_총점이_오르지_않는다():
    """★ 차단 ① 의 **피해 그 자체**를 숫자로 고정한다.

    실측(2026-07-29 · 호가가 적정가보다 +9.3% 비싼 같은 후보):
        가짜 신뢰도 붙음(옛 동작)  총점 64.5  리스크 축 100.0(실효 33.3%)
        붙지 않음(지금)            총점 46.8  리스크 축 미반영
    17.7점이 **측정이 아니라 가산점**이었다. 비쌀수록 점수가 오르는 방향이다.
    """
    user_item, _ = _pipeline(LISTING_SOURCE_USER)
    collected_item, _ = _pipeline(None)

    assert user_item["total_score"] < collected_item["total_score"], (
        "사용자 입력에 수집 데이터와 같은 점수가 붙었다 — 출처 분기가 죽었다")
    # 가격 축은 **양쪽 다 살아 있다.** 리스크 축만 갈린다(가격을 안 보는 게 아니다).
    assert user_item["score_axes"][0]["axis"] == AXIS_PRICE
    for it in (user_item, collected_item):
        price = {r["axis"]: r for r in it["score_axes"]}[AXIS_PRICE]
        assert price["status"] == STATUS_APPLIED and price["score"] is not None


def test_도메인이_점수_대신_사유를_준다():
    """`trust_score` 는 0.0(= 매우 의심스러움)이 아니라 **None**(= 모름)을 준다."""
    row = ListingRow(id=1, ask_price_krw=int(7.65 * OKU), area_m2=84.97, floor=10,
                     collected_at=TODAY, status="active",
                     source=LISTING_SOURCE_USER, as_of=TODAY)
    score, signals = trust_score(group_duplicates([row])[0],
                                 median_price_krw=int(7.0 * OKU), as_of=TODAY)
    assert score is None
    assert signals == [USER_ENTERED_NO_TRUST_REASON]


def test_사용자_입력이_섞여도_중개사_중복_등록_수를_부풀리지_않는다():
    """사용자가 자기 입력으로 '중개사 하나 더'를 만들 수 없다.

    같은 유닛·같은 가격이면 `group_duplicates` 가 한 덩어리로 묶는다. 그때 사용자
    입력을 세면 "N개 중개사 중복 등록"이라는 **미끼 신호**가 사용자 손으로 만들어진다.
    """
    common = dict(ask_price_krw=int(7.0 * OKU), area_m2=84.97, floor=10,
                  collected_at=TODAY, status="active")
    collected = [ListingRow(id=i, agency=f"중개{i}", **common) for i in range(1, 4)]
    mine = ListingRow(id=99, source=LISTING_SOURCE_USER, as_of=TODAY, **common)

    group = group_duplicates([*collected, mine])[0]
    assert group.duplicate_count == 4          # 그룹에는 4건이 들어 있고
    assert len(group.collected) == 3           # 신뢰도가 세는 것은 3건이다
    assert group.user_entered_only is False

    score, signals = trust_score(group, median_price_krw=int(7.0 * OKU), as_of=TODAY)
    assert score is not None                   # 수집 신호가 있으니 판정은 한다
    assert not any("중복 등록" in s for s in signals), signals   # 4건 문턱을 넘지 않았다


# ---------------------------------------------------------------------------
# API 전 구간 (차단 ② · 배선 ③④) — 러너가 실제로 소유자를 넘기는가
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "k" * 32)
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    monkeypatch.setenv("TAX_RULES_PATH", str(FIXTURES / "tax_rules_test.yaml"))

    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.main import create_app

    repo = InMemoryRepository()
    app = create_app(repo=repo)
    with TestClient(app) as c:
        c.repo = repo
        yield c
    get_settings.cache_clear()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _ready(client, email="a@b.co") -> str:
    """가입 → 승인 → 로그인 → 자산 입력. 추천이 돌 수 있는 최소 상태."""
    r = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    user = client.repo.get_user_by_email(email)
    client.repo.set_user_status(user.id, "approved", actor="cli")
    token = client.post("/api/v1/auth/login",
                        json={"email": email, "password": PASSWORD}
                        ).json()["access_token"]
    r = client.put("/api/v1/me/profile",
                   json={"cash_krw": 30 * OKU, "income_krw": 3 * OKU},
                   headers=_auth(token))
    assert r.status_code == 200, r.text
    return token


def _seed_two_areas(repo, *, complex_id=1, name="두면적단지"):
    """한 단지에 **59.94㎡ 와 84.97㎡** 실거래를 둘 다 심는다(호가는 없다).

    이게 운영 DB 의 모습이다 — `listing` 0행 · trade 만 있다.
    """
    repo.add_complex(ComplexSummary(
        id=complex_id, name=name, lon=127.05, lat=37.51, region_code=REGION,
        built_year=2015, total_households=800,
        recent_price_krw=int(7.0 * OKU), price_as_of=TODAY.isoformat(),
        active_listings=0))
    trades = []
    for area, price_oku in ((59.94, 5.0), (84.97, 7.0)):
        trades += [TradeRow(contract_date=TODAY - dt.timedelta(days=15 * i),
                            price_krw=int(price_oku * OKU), area_m2=area, floor=10)
                   for i in range(8)]
    repo.add_trades(complex_id, trades)


def _seed_areas(repo, pairs, *, complex_id=1, name="경계단지"):
    """단지 하나에 `(전용면적, 억원)` 실거래를 심는다(호가는 없다).

    `_seed_two_areas` 는 59.94·84.97 고정이라 **면적 조건 경계**를 찌를 수 없다.
    """
    repo.add_complex(ComplexSummary(
        id=complex_id, name=name, lon=127.05, lat=37.51, region_code=REGION,
        built_year=2015, total_households=800,
        recent_price_krw=int(7.0 * OKU), price_as_of=TODAY.isoformat(),
        active_listings=0))
    trades = []
    for area, price_oku in pairs:
        trades += [TradeRow(contract_date=TODAY - dt.timedelta(days=15 * i),
                            price_krw=int(price_oku * OKU), area_m2=area, floor=10)
                   for i in range(8)]
    repo.add_trades(complex_id, trades)


def _add_listing(client, token, *, area_m2, complex_id=1, ask_oku=7.3):
    r = client.post("/api/v1/me/listings",
                    json={"complex_id": complex_id, "ask_price_krw": int(ask_oku * OKU),
                          "area_m2": area_m2, "floor": 12,
                          "as_of": TODAY.isoformat()},
                    headers=_auth(token))
    assert r.status_code == 201, r.text
    return r.json()


def _recommend(client, token, body=None):
    body = {"region_codes": [REGION], "top_n": 10, **(body or {})}
    r = client.post("/api/v1/recommendations", json=body, headers=_auth(token))
    assert r.status_code == 202, r.text
    got = client.get(f"/api/v1/recommendations/{r.json()['job_id']}",
                     headers=_auth(token))
    assert got.status_code == 200, got.text
    return got.json()


def _areas(result) -> list[float]:
    return sorted(round(it["unit_type"]["area_m2"], 2) for it in result["items"])


def _by_area(result, area: float) -> dict:
    return next(it for it in result["items"]
                if abs(it["unit_type"]["area_m2"] - area) < 0.01)


def test_호가를_한_면적대에_넣어도_다른_면적대_후보가_살아있다(client):
    """★ 차단 ②. 84㎡ 호가를 넣으면 59㎡ 실거래 후보가 사라지던 결함.

    변이: `_assemble_candidates` 를 `if listings: … continue` 로 되돌리면
    호가 입력 후 목록이 [84.97] 로 줄어 여기서 깨진다.
    """
    token = _ready(client)
    _seed_two_areas(client.repo)

    before = _recommend(client, token)
    assert _areas(before) == [59.94, 84.97], "기준선부터 두 면적대가 나와야 한다"

    r = client.post("/api/v1/me/listings",
                    json={"complex_id": 1, "ask_price_krw": int(7.3 * OKU),
                          "area_m2": 84.97, "floor": 12,
                          "as_of": TODAY.isoformat()},
                    headers=_auth(token))
    assert r.status_code == 201, r.text

    after = _recommend(client, token)
    assert _areas(after) == [59.94, 84.97], (
        "호가를 넣었더니 다른 면적대가 사라졌다", _areas(after))
    # 59㎡ 는 여전히 실거래 기준이고, 84㎡ 만 호가 기준으로 바뀐다.
    assert _by_area(after, 59.94)["price_basis"] == "trade"
    assert _by_area(after, 84.97)["price_basis"] == "listing"


def test_같은_면적대에_호가가_있으면_실거래_후보를_또_세우지_않는다(client):
    """중복 노출 금지. 같은 유닛이 '호가 후보'와 '실거래 후보'로 두 번 나오면
    사용자는 같은 집을 두 선택지로 착각한다. 같은 면적대에서는 **호가가 이긴다.**
    """
    token = _ready(client)
    _seed_two_areas(client.repo)
    client.post("/api/v1/me/listings",
                json={"complex_id": 1, "ask_price_krw": int(7.3 * OKU),
                      "area_m2": 84.97, "floor": 12, "as_of": TODAY.isoformat()},
                headers=_auth(token))

    items = _recommend(client, token)["items"]
    areas = [round(it["unit_type"]["area_m2"], 2) for it in items]
    assert len(areas) == len(set(areas)) == 2, areas
    assert sum(1 for it in items if it["price_basis"] == "listing") == 1


def test_입력한_호가가_추천의_가격_근거로_실제로_쓰인다(client):
    """★ 배선 ④. 러너가 `user_id` 를 안 넘기면 리포지토리가 **0건**을 준다(fail-closed).

    그러면 이 후보는 조용히 '실거래 기준'으로 떨어지고 가격 축이 죽는다 —
    오류가 아니라 **아무 일도 안 일어난 것처럼** 보이는 실패다.
    변이: `_analyze` 의 `user_id=user_id` 나 `listings_of(..., user_id=...)` 를 지우면
    price_basis 가 trade 로 돌아가 여기서 깨진다.
    """
    token = _ready(client)
    _seed_two_areas(client.repo)
    ask = int(7.3 * OKU)
    client.post("/api/v1/me/listings",
                json={"complex_id": 1, "ask_price_krw": ask, "area_m2": 84.97,
                      "floor": 12, "as_of": TODAY.isoformat()},
                headers=_auth(token))

    item = _by_area(_recommend(client, token), 84.97)
    assert item["price_basis"] == "listing"
    assert item["ask_price_krw"] == ask
    assert item["est_price_krw"] == ask          # 예산 판정도 이 값으로 한다
    assert item["price_estimated"] is False
    assert item["ask_gap_pct"] is not None       # 가격 축이 살아났다


def test_남의_호가는_내_추천에_섞이지_않는다(client):
    """소유자 스코프가 추천 경로에서도 유지된다(IDOR)."""
    a = _ready(client, "a@b.co")
    b = _ready(client, "b@b.co")
    _seed_two_areas(client.repo)
    client.post("/api/v1/me/listings",
                json={"complex_id": 1, "ask_price_krw": int(7.3 * OKU),
                      "area_m2": 84.97, "floor": 12, "as_of": TODAY.isoformat()},
                headers=_auth(a))

    assert _by_area(_recommend(client, a), 84.97)["price_basis"] == "listing"
    assert _by_area(_recommend(client, b), 84.97)["price_basis"] == "trade"


def test_추천_결과에서도_사용자_입력에는_신뢰도가_안_붙는다(client):
    """★ 차단 ① 을 **API 응답**에서 한 번 더 못 박는다.

    파이프라인 단위 테스트는 Candidate 를 손으로 만든다. 여기서는 리포지토리가
    실제로 `source` 를 실어 보내는지까지 함께 걸린다(배선 ③).
    """
    token = _ready(client)
    _seed_two_areas(client.repo)
    uid = client.repo.get_user_by_email("a@b.co").id
    client.repo.set_preferences(uid, {"prefer": {}, "avoid": {},
                                      "weights": dict(EVEN_WEIGHTS)})
    client.post("/api/v1/me/listings",
                json={"complex_id": 1, "ask_price_krw": int(7.3 * OKU),
                      "area_m2": 84.97, "floor": 12, "as_of": TODAY.isoformat()},
                headers=_auth(token))

    item = _by_area(_recommend(client, token), 84.97)
    axes = {row["axis"]: row for row in item["score_axes"]}
    assert axes[AXIS_RISK]["status"] == STATUS_NO_SIGNAL
    assert USER_ENTERED_NO_TRUST_REASON in axes[AXIS_RISK]["missing"]
    # 가격 축은 살아 있다 — 입력의 값어치는 여기에 있다.
    assert axes[AXIS_PRICE]["status"] == STATUS_APPLIED


def test_리포지토리가_출처와_확인일을_분석계층까지_싣는다(client):
    """★ 배선 ③. `ListingRow.source` 가 비면 분석 계층에서 출처 구분이 끊긴다."""
    token = _ready(client)
    _seed_two_areas(client.repo)
    client.post("/api/v1/me/listings",
                json={"complex_id": 1, "ask_price_krw": int(7.3 * OKU),
                      "area_m2": 84.97, "floor": 12, "as_of": TODAY.isoformat()},
                headers=_auth(token))

    uid = client.repo.get_user_by_email("a@b.co").id
    row = client.repo.listings_for_complex(1, user_id=uid)[0]
    assert row.source == LISTING_SOURCE_USER
    assert row.is_user_entered is True
    assert row.as_of == TODAY
    # 포털 등록일은 여전히 비어 있다 — 사용자가 모르는 값을 지어내지 않는다.
    assert row.listed_at is None


# ---------------------------------------------------------------------------
# 면적 조건 **경계** (CR35-1) — 조건 밖 호가가 조건 안 실거래를 지우면 안 된다
# ---------------------------------------------------------------------------

def test_조건_밖_호가가_조건_안_실거래_후보를_지우지_않는다(client):
    """★ CR35-1(차단). **경계에서의 조용한 유실**을 고정한다.

    조건 80~85㎡ · 호가 85.3㎡(조건 **밖**) · 실거래 84.97㎡(조건 **안**).
    두 면적의 차는 0.33㎡ 로 `AREA_TOLERANCE_M2`(0.5) 안이다.

    실측(2026-07-29 · API 전 구간):
        고치기 전  호가 넣기 전 [84.97] → 넣은 뒤 **[] (0건)**  · excluded 0건
        고친 뒤    호가 넣기 전 [84.97] → 넣은 뒤 [84.97]      · 대조군과 같다

    사라진 사실이 `dropped`(=notes)에도 `excluded` 에도 안 남았다 — 사용자에게는
    "호가를 입력했더니 그 단지가 없어졌다"로만 보인다.

    변이: `listing_areas.append(area)` 를 `conditions.area_ok(area)` **앞으로**
    되돌리면 `after` 가 0건이 되어 여기서 깨진다.
    """
    token = _ready(client)
    _seed_areas(client.repo, [(84.97, 7.0)])
    cond = {"area_min_m2": 80.0, "area_max_m2": 85.0}

    before = _recommend(client, token, cond)
    assert _areas(before) == [84.97], "기준선부터 조건 안 실거래 후보가 나와야 한다"

    _add_listing(client, token, area_m2=85.3)      # 조건 밖 · 실거래와 0.33㎡ 차

    after = _recommend(client, token, cond)
    assert _areas(after) == [84.97], (
        "조건 밖 호가 한 건이 조건 안 실거래 후보를 지웠다", _areas(after))
    # 호가는 조건 밖이므로 가격 근거가 되지 않는다 — 실거래 기준 그대로다.
    assert _by_area(after, 84.97)["price_basis"] == "trade"


def test_조건_밖_호가는_제외_건수로_세어진다(client):
    """유실을 막되 **말하지 않고 넘어가지도 않는다.**

    같은 경계 입력에서 조건에 걸린 것은 호가 1건뿐이고, 그 사실이 notes 에 남는다.
    """
    token = _ready(client)
    _seed_areas(client.repo, [(84.97, 7.0)])
    _add_listing(client, token, area_m2=85.3)

    notes = _recommend(client, token,
                       {"area_min_m2": 80.0, "area_max_m2": 85.0})["notes"]
    assert any("면적 조건 밖 후보 1건" in n for n in notes), notes


def test_조건_밖_면적이_실거래로_되살아나지_않는다(client):
    """이 규칙이 원래 막으려던 것 — **뒤의 `kept` 가 실제로 막는지** 직접 본다.

    조건 55~65㎡ · 호가 84.97㎡(조건 밖) · 실거래 84.97㎡ + 59.9㎡.
    호가가 자리를 차지하지 않게 되면서 84.97 실거래 면적대가 (b)로 넘어오지만,
    `kept = [a for a in areas if conditions.area_ok(a)]` 가 같은 조건으로 다시
    거른다. 그래서 **사용자가 배제한 84㎡ 는 되살아나지 않는다.**

    덤으로 제외 건수가 옳아진다 — 실제로 면적 조건에 걸린 것은 둘(호가 84.97 ·
    실거래 84.97)인데 고치기 전에는 1건으로 셌다(실측).

    변이: `kept` 필터를 지우면 [59.9, 84.97] 이 되어 여기서 깨진다.
    """
    token = _ready(client)
    _seed_areas(client.repo, [(84.97, 7.0), (59.9, 5.0)])
    _add_listing(client, token, area_m2=84.97)
    cond = {"area_min_m2": 55.0, "area_max_m2": 65.0}

    result = _recommend(client, token, cond)
    assert _areas(result) == [59.9], (
        "조건 밖 면적이 실거래 후보로 되살아났다", _areas(result))
    assert _by_area(result, 59.9)["price_basis"] == "trade"
    assert any("면적 조건 밖 후보 2건" in n for n in result["notes"]), result["notes"]


def test_조건_안_호가는_여전히_같은_면적대_실거래를_대신한다(client):
    """조건이 걸린 채로도 (b)의 중복 방지가 살아 있어야 한다.

    변이: `listing_areas.append(area)` 를 통째로 지우면 같은 84.97 면적대가
    호가 후보 + 실거래 후보 **두 건**으로 나와 여기서 깨진다.
    """
    token = _ready(client)
    _seed_areas(client.repo, [(84.97, 7.0), (59.9, 5.0)])
    _add_listing(client, token, area_m2=84.97)

    items = _recommend(client, token,
                       {"area_min_m2": 80.0, "area_max_m2": 90.0})["items"]
    areas = [round(it["unit_type"]["area_m2"], 2) for it in items]
    assert areas == [84.97], areas
    assert items[0]["price_basis"] == "listing"


def test_내_호가만_있는_면적대가_빠진_이유를_말한다(client):
    """★ 이월 ⓑ. "호가를 넣었는데 그 단지가 안 나온다"에 답이 있어야 한다.

    실거래는 59㎡ 뿐인 단지에 내가 84㎡ 호가를 넣고 80~90㎡ 로 요청하면, 그 단지는
    **후보 조회 단계**에서 빠진다 — `recommendation_candidates`·`candidate_scope_stats`
    가 소유자 인자를 받지 않아 사용자 입력을 면적 근거로 세지 않기 때문이다.
    그 배제 자체는 의도된 것이다(세면 A 의 입력이 B 의 조건 통과를 바꾼다 — SR-031 §2-4).

    문제는 **그 상태에서 나가는 문장이 사용자에게 거짓으로 보인다**는 것이었다:
    "해당 면적대의 실거래·매물 근거가 없는 단지입니다" — 방금 매물을 넣었는데.

    변이: `_SCOPE_AREA_NOTE` 의 마지막 문장을 지우면 깨진다.
    """
    token = _ready(client)
    _seed_areas(client.repo, [(59.9, 5.0)], name="내호가만단지")
    _add_listing(client, token, area_m2=84.97, ask_oku=9.0)

    result = _recommend(client, token, {"area_min_m2": 80.0, "area_max_m2": 90.0})
    assert result["items"] == []      # 조회 단계에서 빠진다(현재의 의도된 동작)
    scope = [n for n in result["notes"] if "범위 내 단지" in n]
    assert scope, result["notes"]
    assert "직접 입력하신 호가를 세지 않습니다" in scope[0], scope[0]


# ---------------------------------------------------------------------------
# 문구 (배선 ⑤) — 호가가 들어오는 순간 거짓이 되는 문장을 남기지 않는다
# ---------------------------------------------------------------------------

def test_가격축_설명이_모든_후보에서_점수가_없다고_단언하지_않는다():
    """호가를 직접 입력하면 그 후보에는 실제로 가격 점수가 나온다(위 테스트가 증명).

    그때 "호가 데이터가 없어 **모든** 후보에서 점수가 나오지 않습니다"는 거짓말이다.
    """
    gap = AXIS_SPECS[AXIS_PRICE].coverage_gap
    assert "모든 후보에서 점수가 나오지 않습니다" not in gap
    assert "직접 입력" in gap                     # 남은 길을 알려준다


def test_호가없음_사유가_막다른_길로_끝나지_않는다():
    """사실만 말하고 끝내면 사용자가 할 수 있는 일이 없다. 남은 경로를 알려준다."""
    assert "직접 입력" in NO_ASK_REASON
    assert "약관" in NO_ASK_REASON                # 왜 자동수집을 안 하는지도 유지


# ---------------------------------------------------------------------------
# 자금계획 == 추천 카드 (★ CR36-2) — **API 전 구간에서** 같은 값인가
#
# CR-036 이 잡아낸 것: 이 명제(CR35-4)는 지금까지 **손수 만든 리포지토리 더블**
# (`test_price_consistency._Repo`) 위에서만 증명됐다. 인메모리 리포지토리에는
# `complex_region_code` 도 `market_index` 도 **없어서**, API 를 지나는 모든 테스트에서
# 자금계획은 언제나 시점 보정 없는 `trade_band` 로 떨어졌다.
# 실측 격차: 529,699,059(추천 카드) vs 500,000,000(자금계획) — 5.6%.
#
# 여기서는 아무것도 monkeypatch 하지 않는다. 지수·지역코드를 **리포지토리에 넣고**
# HTTP 두 번(추천 · 자금계획)으로만 확인한다.
# ---------------------------------------------------------------------------

def _rising_index(region: str = "11680", scope: str = "sigungu"):
    """오늘 기준 최근 13개월 상승 지수. **날짜에 안 흔들리게** 상대적으로 만든다."""
    from app.domain.valuation.timeadjust import (
        MIN_REFERENCE_MONTH_SAMPLE,
        IndexPoint,
        MarketIndex,
    )

    points = {}
    y, m = TODAY.year, TODAY.month
    for back in range(13):
        ym_y, ym_m = (y, m - back) if m - back > 0 else (y - 1, m - back + 12)
        ym = f"{ym_y:04d}-{ym_m:02d}"
        # 과거로 갈수록 낮다(= 상승장). 이번 달은 아직 **미완결**이라 기준월이 못 된다.
        points[ym] = IndexPoint(ym=ym, value=1.0 - 0.01 * back,
                                sample_size=MIN_REFERENCE_MONTH_SAMPLE,
                                is_complete=back > 0)
    return MarketIndex(region_code=region, scope=scope, points=points)


def _ym_back(d: dt.date, back: int) -> dt.date:
    """`d` 기준 `back` 개월 전의 **15일**.

    일자를 15로 고정하는 이유: `TODAY - 15*i일` 로 심으면 **오늘이 며칠이냐에 따라
    거래가 어느 달에 떨어지는지가 달라진다.** 월말에는 여러 건이 이번 달로 몰리고,
    월초에는 지난달로 밀린다. 보정 배율은 **거래의 달**로 정해지므로 그 순간
    검사가 재는 값이 날마다 달라진다 — 실제로 이 파일이 그렇게 깨졌다.
    """
    y, m = d.year, d.month - back
    while m <= 0:
        y, m = y - 1, m + 12
    return dt.date(y, m, 15)


def _seed_two_areas_monthly(repo, *, complex_id=1, name="월고정단지", months=range(2, 10)):
    """`_seed_two_areas` 의 **달 고정판**.

    거래를 전부 **기준월보다 오래된 달**(기본 2~9개월 전)에 심는다.
    `_rising_index` 의 기준월은 '지난달'이므로, 모든 거래가 기준월보다 과거라
    보정 배율이 **항상 1보다 크다** — 오늘이 며칠이든.
    공용 `_seed_two_areas` 를 안 고친 이유: 19곳이 쓰고 있고 밴드 창(6·12·24·36개월)
    구성이 달라져 다른 검사의 의미까지 바뀐다.
    """
    repo.add_complex(ComplexSummary(
        id=complex_id, name=name, lon=127.05, lat=37.51, region_code=REGION,
        built_year=2015, total_households=800,
        recent_price_krw=int(7.0 * OKU), price_as_of=TODAY.isoformat(),
        active_listings=0))
    trades = []
    for area, price_oku in ((59.94, 5.0), (84.97, 7.0)):
        trades += [TradeRow(contract_date=_ym_back(TODAY, b),
                            price_krw=int(price_oku * OKU), area_m2=area, floor=10)
                   for b in months]
    repo.add_trades(complex_id, trades)


def test_자금계획이_API_경로에서도_추천카드와_같은_금액을_쓴다(client):
    """★ CR36-2. 두 화면의 숫자가 **HTTP 응답 안에서** 같은지 본다.

    변이 ①: `InMemoryRepository.complex_region_code` 를 지우면 자금계획만
            `trade_band` 로 떨어져 금액이 갈리고 여기서 깨진다.
    변이 ②: `InMemoryRepository.market_index` 를 지우면 **양쪽 다** 보정을 잃는다 —
            그때는 금액이 같아지지만 `basis` 가 `time_adjusted_band` 가 아니라
            `trade_band` 라 아래 단언에서 깨진다(보정이 실제로 돌았음을 못박는다).
    """
    token = _ready(client)
    # ⚠️ 날짜 고정 시드를 쓴다. `_seed_two_areas` 는 `TODAY - 15*i일` 이라
    #    월말에는 거래 여러 건이 이번 달로 몰려 중위가 기준월 거래에 걸리고,
    #    그러면 보정 배율이 1.0 이 되어 아래 마지막 단언이 **제품과 무관하게** 깨진다.
    #    (2026-07-31 에 실제로 그렇게 깨졌고, 배포된 커밋에서도 같았다)
    _seed_two_areas_monthly(client.repo)
    client.repo.set_market_index(_rising_index())

    card = _by_area(_recommend(client, token), 84.97)
    assert card["price_basis"] == "trade", "호가가 없으면 추천 카드는 실거래 기준이다"

    plan = client.post("/api/v1/affordability",
                       json={"complex_id": 1, "area_m2": 84.97},
                       headers=_auth(token)).json()

    assert plan["target_price"]["krw"] == card["est_price_krw"], (
        "자금계획과 추천 카드가 다른 금액을 말하면 안 된다",
        plan["target_price"], card["est_price_krw"])
    # 그리고 그 값이 **시점 보정을 거친** 값인지 — 같은 값이어도 둘 다 보정을
    # 못 한 상태면 CR35-4 가 지키려던 것이 지켜진 게 아니다.
    assert plan["target_price"]["basis"] == "time_adjusted_band"
    assert plan["target_price"]["as_of_ym"], "환산 기준월이 있어야 한다"
    # 보정이 실제로 값을 움직였는가(상승장이라 명목 중위보다 높아야 한다).
    assert plan["target_price"]["krw"] > int(7.0 * OKU)


def test_지수가_없으면_두_화면_모두_보정하지_않는다고_말한다(client):
    """대조군. 지수를 안 넣으면 **양쪽 다** `trade_band` 이고 그 사실이 응답에 남는다.

    (지수가 없을 때 조용히 보정한 척하는 경로가 없다는 확인 — G2.)
    """
    token = _ready(client)
    _seed_two_areas(client.repo)

    card = _by_area(_recommend(client, token), 84.97)
    plan = client.post("/api/v1/affordability",
                       json={"complex_id": 1, "area_m2": 84.97},
                       headers=_auth(token)).json()

    assert plan["target_price"]["basis"] == "trade_band"
    assert plan["target_price"]["reason"], "왜 보정을 못 했는지 말해야 한다"
    assert plan["target_price"]["krw"] == card["est_price_krw"]


def test_호가없는_후보에는_그_사유가_그대로_붙는다(client):
    """문구 상수만 고치고 응답에 안 실리면 아무것도 고친 게 아니다."""
    token = _ready(client)
    _seed_two_areas(client.repo)
    uid = client.repo.get_user_by_email("a@b.co").id
    client.repo.set_preferences(uid, {"prefer": {}, "avoid": {},
                                      "weights": dict(EVEN_WEIGHTS)})

    item = _by_area(_recommend(client, token), 59.94)
    price = {row["axis"]: row for row in item["score_axes"]}[AXIS_PRICE]
    assert price["status"] == STATUS_NO_SIGNAL
    assert any("직접 입력" in m for m in price["missing"]), price["missing"]
