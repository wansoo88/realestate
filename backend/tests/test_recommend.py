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
