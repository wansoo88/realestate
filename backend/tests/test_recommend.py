"""추천 실행 경로(BackgroundTask) 테스트 — ORDER 2026-07-25-24-domain.

redis/큐 없이 API BackgroundTask 로 orchestrator 를 돌리는 경로를 인메모리 repo 로 검증한다.
TestClient 는 BackgroundTask 를 **동기로** 끝낸 뒤 응답을 돌려주므로, POST 직후 GET 하면
결과가 이미 준비돼 있다.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.domain.valuation.models import ListingRow, TradeRow
from app.repositories.base import ComplexSummary
from app.repositories.memory import InMemoryRepository

FIXTURES = Path(__file__).parent / "fixtures"
PASSWORD = "correct horse battery staple"
REGION = "1168000000"
OKU = 100_000_000
TODAY = dt.date.today()


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


def _login(client, email="a@b.co") -> str:
    client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    return client.post("/api/v1/auth/login",
                       json={"email": email, "password": PASSWORD}).json()["access_token"]


def _set_profile(client, token, cash=300_000_000, income=200_000_000):
    r = client.put("/api/v1/me/profile",
                   json={"cash_krw": cash, "income_krw": income},
                   headers=_auth(token))
    assert r.status_code == 200, r.text


def _seed_complex(repo, *, complex_id=1, ask_oku=7.0, area=84.97, households=500):
    repo.add_complex(ComplexSummary(
        id=complex_id, name="테스트단지", lon=127.05, lat=37.51, region_code=REGION,
        built_year=2015, total_households=households,
        recent_price_krw=int(ask_oku * OKU), price_as_of=TODAY.isoformat(),
        active_listings=2))
    listings = [
        ListingRow(id=complex_id * 10 + i, ask_price_krw=int(ask_oku * OKU),
                   area_m2=area, floor=10,
                   listed_at=TODAY - dt.timedelta(days=10), collected_at=TODAY,
                   agency=f"중개{i}", status="active")
        for i in range(2)
    ]
    repo.add_listings(complex_id, listings)
    trades = [
        TradeRow(contract_date=TODAY - dt.timedelta(days=15 * i),
                 price_krw=int(ask_oku * OKU), area_m2=area, floor=10)
        for i in range(8)
    ]
    repo.add_trades(complex_id, trades)


def _seed_trades_only(repo, *, complex_id=1, price_oku=7.0, area=84.97,
                      households=500, n=8, with_dong=False, name="호가없는단지"):
    """**호가 없이** 단지 + 실거래만 심는다.

    이게 운영 DB 의 실제 모습이다: 공공 오픈API 에는 호가가 없어 `listing` 이 0건이다
    (2026-07-26 서버 실측: complex 6,538 · trade 120,138 · **listing 0**).
    """
    repo.add_complex(ComplexSummary(
        id=complex_id, name=name, lon=127.05, lat=37.51, region_code=REGION,
        built_year=2015, total_households=households,
        recent_price_krw=int(price_oku * OKU), price_as_of=TODAY.isoformat(),
        active_listings=0))
    trades = []
    for i in range(n):
        dong = None
        if with_dong:
            # 101동(비쌈) / 105동(쌈) — F4 동별 실측이 성립하도록 각각 표본을 채운다.
            dong = "101" if i % 2 == 0 else "105"
        bump = 0.0
        if with_dong:
            bump = 0.6 if dong == "101" else -0.6
        trades.append(TradeRow(
            contract_date=TODAY - dt.timedelta(days=15 * i),
            price_krw=int((price_oku + bump) * OKU), area_m2=area, floor=10,
            apt_dong=dong))
    repo.add_trades(complex_id, trades)


def _run(client, token, body):
    """POST 로 큐잉 → (BackgroundTask 동기 실행) → GET 으로 결과."""
    r = client.post("/api/v1/recommendations", json=body, headers=_auth(token))
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    got = client.get(f"/api/v1/recommendations/{job_id}", headers=_auth(token))
    assert got.status_code == 200, got.text
    return got.json()


# ---------------------------------------------------------------------------
# 실제 추천이 나온다
# ---------------------------------------------------------------------------

def test_추천이_백그라운드에서_실행돼_결과가_나온다(client):
    token = _login(client)
    _set_profile(client, token)
    _seed_complex(client.repo, ask_oku=7.0)

    body = _run(client, token, {"region_codes": [REGION]})

    assert body["status"] == "done", body
    assert body["items"], "후보가 있는데 추천이 비었다"
    top = body["items"][0]
    assert top["complex"]["id"] == 1
    assert top["total_score"] is not None
    # 근거·반대근거가 함께 나온다(G2/F6).
    assert "why" in top and "why_not" in top
    assert top["findings"], "에이전트별 근거가 저장돼야 한다"


def test_예산초과_단지는_제외되고_사유가_남는다(client):
    token = _login(client)
    _set_profile(client, token, cash=100_000_000, income=50_000_000)   # 예산 작게
    _seed_complex(client.repo, ask_oku=50.0)                           # 50억 — 확실히 초과

    body = _run(client, token, {"region_codes": [REGION]})
    assert body["status"] == "done"
    assert body["items"] == []          # 못 사는 집은 추천이 아니다


# ---------------------------------------------------------------------------
# 호가 없는 단지 — 공공API 만으로도 추천이 나와야 한다 (CHARTER G4)
#
# 회귀 방지 대상: `_assemble_candidates` 가 `if not listings: continue` 로 호가 없는
# 단지를 건너뛰던 버그. 공공 오픈API 에는 호가가 없어 listing 테이블이 통째로 비므로
# 추천이 **구조적으로 항상 0건**이었다.
# ---------------------------------------------------------------------------

def test_호가가_없어도_실거래로_후보가_선다(client):
    """★핵심 회귀: listing 0건이어도 추천이 나온다."""
    token = _login(client)
    _set_profile(client, token)
    _seed_trades_only(client.repo, price_oku=7.0)      # 호가 0건, 실거래만

    body = _run(client, token, {"region_codes": [REGION]})

    assert body["status"] == "done"
    assert body["items"], "호가가 없다는 이유로 후보가 0건이 되면 G4 위반이다"
    assert body["items"][0]["complex"]["id"] == 1


def test_실거래기준_후보는_price_basis가_trade다(client):
    """가격 근거를 응답에 **명시적 필드**로 싣는다 — 호가처럼 위장하지 않는다(G2)."""
    token = _login(client)
    _set_profile(client, token)
    _seed_trades_only(client.repo, price_oku=7.0)

    top = _run(client, token, {"region_codes": [REGION]})["items"][0]

    assert top["price_basis"] == "trade"
    assert top["price_estimated"] is True
    assert top["est_price_krw"] > 0                    # 예산 비교에 실제로 쓴 값
    assert top["price_note"] and "실거래" in top["price_note"]
    # 적정가 밴드 자체가 근거로 실린다(갭 대신).
    assert top["price_band"] and top["price_band"]["median_krw"] > 0
    assert top["price_band"]["sample_size"] >= 5


def test_실거래기준_후보에는_호가와_호가갭이_없다(client):
    """비교 대상(호가)이 없으므로 갭을 만들어내면 안 된다 — None 이어야 한다."""
    token = _login(client)
    _set_profile(client, token)
    _seed_trades_only(client.repo, price_oku=7.0)

    top = _run(client, token, {"region_codes": [REGION]})["items"][0]

    assert top["ask_price_krw"] is None, "호가가 없는데 숫자가 실리면 하류가 호가로 믿는다"
    assert top["ask_gap_pct"] is None, "비교 대상이 없는데 갭을 지어냈다"
    assert top["building"] is None, "특정 물건이 없으므로 동 표기도 없다"

    val = next(f for f in top["findings"] if f["agent_id"] == "valuation-trader")
    assert "현재 매물 없음" in val["verdict"]
    assert "%" not in val["verdict"]
    # 매물 리서처는 평가할 매물이 없다 — '정상 매물'로 단정하지 않는다.
    listing_f = next(f for f in top["findings"] if f["agent_id"] == "listing-researcher")
    assert listing_f["verdict"] == "판단 보류"
    assert listing_f["missing"]


def test_호가가_생기면_호가_경로로_돌아간다(client):
    """수집이 살아나면 즉시 호가 기준(ask_gap 판정)으로 복귀해야 한다."""
    token = _login(client)
    _set_profile(client, token)
    _seed_complex(client.repo, ask_oku=7.5)            # 호가 7.5억 · 실거래 7.5억

    top = _run(client, token, {"region_codes": [REGION]})["items"][0]

    assert top["price_basis"] == "listing"
    assert top["price_estimated"] is False
    assert top["price_note"] is None
    assert top["ask_price_krw"] == int(7.5 * OKU)
    assert top["est_price_krw"] == top["ask_price_krw"]
    assert top["ask_gap_pct"] is not None, "호가가 있으면 갭을 계산해야 한다"
    assert top["total_score"] is not None and top["score_basis"] == "agent_scores"


def test_실거래기준_후보도_동별_실측이_살아있다(client):
    """★F4 회귀: dong_valuation 은 실거래 기반이라 **호가 유무와 무관**하다."""
    token = _login(client)
    _set_profile(client, token)
    _seed_trades_only(client.repo, price_oku=7.0, n=10, with_dong=True)

    top = _run(client, token, {"region_codes": [REGION]})["items"][0]

    assert top["price_basis"] == "trade"
    dv = top["dong_valuation"]
    assert dv is not None and dv["available"] is True, "호가가 없다고 F4 가 죽으면 안 된다"
    assert dv["basis"] == "trade_measured"
    dongs = {d["dong"]: d for d in dv["dongs"]}
    assert dongs["101"]["vs_complex_pct"] > 0 > dongs["105"]["vs_complex_pct"]


def test_실거래기준_예산초과는_추정치임을_사유에_남긴다(client):
    """예산 필터는 실거래 추정가로 비교하되 **추정임을 결과에 남긴다.**"""
    token = _login(client)
    _set_profile(client, token, cash=100_000_000, income=50_000_000)
    _seed_trades_only(client.repo, price_oku=50.0)     # 50억 — 확실히 초과

    body = _run(client, token, {"region_codes": [REGION]})
    assert body["items"] == []                        # 못 사는 집은 추천이 아니다


def test_실거래_표본이_부족하면_후보로_세우지_않는다(client):
    """가격 근거가 없으면(호가 없음 + 표본 부족) 지어내지 않고 후보에서 뺀다."""
    token = _login(client)
    _set_profile(client, token)
    _seed_trades_only(client.repo, price_oku=7.0, n=2)   # MIN_SAMPLE(5) 미만

    body = _run(client, token, {"region_codes": [REGION]})
    assert body["status"] == "done"
    assert body["items"] == []


def test_호가_단지와_실거래_단지가_섞여도_각각_제_근거를_쓴다(client):
    token = _login(client)
    _set_profile(client, token)
    _seed_complex(client.repo, complex_id=1, ask_oku=7.5)               # 호가 있음
    _seed_trades_only(client.repo, complex_id=2, price_oku=7.0)         # 호가 없음

    items = _run(client, token, {"region_codes": [REGION]})["items"]
    by_id = {it["complex"]["id"]: it for it in items}
    assert set(by_id) == {1, 2}
    assert by_id[1]["price_basis"] == "listing" and by_id[1]["ask_gap_pct"] is not None
    assert by_id[2]["price_basis"] == "trade" and by_id[2]["ask_price_krw"] is None
    # 점수가 있는 후보(호가 기준)가 점수 없는 후보보다 위에 온다.
    assert items[0]["complex"]["id"] == 1


# ---------------------------------------------------------------------------
# 데이터 없을 때 — 빈 결과가 정상(수집 전)
# ---------------------------------------------------------------------------

def test_매물데이터가_없으면_빈결과_done(client):
    token = _login(client)
    _set_profile(client, token)
    # 단지·매물 미시딩 → 후보 없음

    body = _run(client, token, {"region_codes": [REGION]})
    assert body["status"] == "done"
    assert body["items"] == []


def test_프로필이_없으면_크래시없이_빈결과(client):
    token = _login(client)
    # 프로필 미입력 → 예산 미상 → 빈 결과, 그러나 done(스택 안 남고 정상 종료)
    body = _run(client, token, {"region_codes": [REGION]})
    assert body["status"] == "done"
    assert body["items"] == []


# ---------------------------------------------------------------------------
# 실거래 면적대 선택 — 호가가 없을 때 "어떤 유닛을 후보로 세울지"
# ---------------------------------------------------------------------------

def _t(area, price_oku=7.0, days=10):
    return TradeRow(contract_date=TODAY - dt.timedelta(days=days),
                    price_krw=int(price_oku * OKU), area_m2=area, floor=10)


def test_면적대는_거래많은순으로_고르고_표본미달은_뺀다():
    from app.agents.recommend import _trade_area_groups

    trades = ([_t(59.9, days=5 * i) for i in range(6)]       # 6건
              + [_t(84.97, days=5 * i) for i in range(9)]    # 9건
              + [_t(114.5, days=5 * i) for i in range(2)])   # 2건 — MIN_SAMPLE 미달
    assert _trade_area_groups(trades) == [84.97, 59.9]


def test_오차안의_면적은_한_덩어리로_본다():
    """84.9 와 84.97 을 따로 세우면 같은 타입이 두 후보가 된다(밴드는 어차피 합산)."""
    from app.agents.recommend import _trade_area_groups

    trades = ([_t(84.97, days=5 * i) for i in range(6)]
              + [_t(84.9, days=5 * i + 2) for i in range(6)])
    assert _trade_area_groups(trades) == [84.9]     # 하나만


def test_오래된_거래만_있으면_면적대를_세우지_않는다():
    """밴드가 쓰지 않는 창(36개월 밖)의 거래를 '가격 근거 있음'으로 세면 안 된다."""
    from app.agents.recommend import _trade_area_groups

    old = [_t(84.97, days=40 * 30 + 30 * i) for i in range(8)]
    assert _trade_area_groups(old) == []


def test_해제거래는_면적대_표본에서_빠진다():
    from app.agents.recommend import _trade_area_groups

    trades = [TradeRow(contract_date=TODAY - dt.timedelta(days=5 * i),
                       price_krw=int(7.0 * OKU), area_m2=84.97, floor=10,
                       is_cancelled=True) for i in range(8)]
    assert _trade_area_groups(trades) == []


def test_한_단지가_후보를_독식하지_않는다():
    from app.agents.recommend import TRADE_AREA_GROUPS_PER_COMPLEX, _trade_area_groups

    trades = []
    for area in (49.5, 59.9, 74.2, 84.97, 114.5):
        trades += [_t(area, days=5 * i) for i in range(6)]
    assert len(_trade_area_groups(trades)) == TRADE_AREA_GROUPS_PER_COMPLEX


# ---------------------------------------------------------------------------
# IDOR — 남의 추천은 못 본다(백그라운드 저장도 소유권 검증)
# ---------------------------------------------------------------------------

def test_남의_추천결과는_못본다(client):
    t1 = _login(client, "a@b.co")
    t2 = _login(client, "b@b.co")
    _set_profile(client, t1, cash=300_000_000, income=200_000_000)
    _seed_complex(client.repo)

    r = client.post("/api/v1/recommendations", json={"region_codes": [REGION]},
                    headers=_auth(t1))
    job_id = r.json()["job_id"]

    assert client.get(f"/api/v1/recommendations/{job_id}",
                      headers=_auth(t1)).status_code == 200
    assert client.get(f"/api/v1/recommendations/{job_id}",
                      headers=_auth(t2)).status_code == 404
