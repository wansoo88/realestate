"""API 계약 테스트 — 인메모리 리포지토리로 DB 없이 검증.

중점: **IDOR 방지**와 **민감정보 취급**. 기능보다 이쪽이 더 중요하다.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.repositories.base import ComplexSummary
from app.repositories.memory import InMemoryRepository

FIXTURES = Path(__file__).parent / "fixtures"
PASSWORD = "correct horse battery staple"


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


def _register_and_login(client, email: str) -> str:
    r = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 인증
# ---------------------------------------------------------------------------

def test_health는_인증없이_열린다(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health가_비밀값을_노출하지_않는다(client):
    body = client.get("/api/v1/health").text
    assert "secret" not in body.lower()
    assert "password" not in body.lower()


def test_토큰없이_접근하면_401(client):
    assert client.get("/api/v1/me/profile").status_code == 401


def test_짧은_비밀번호는_거부(client):
    r = client.post("/api/v1/auth/register", json={"email": "a@b.co", "password": "short"})
    assert r.status_code == 422


def test_중복_이메일은_409(client):
    client.post("/api/v1/auth/register", json={"email": "a@b.co", "password": PASSWORD})
    r = client.post("/api/v1/auth/register", json={"email": "a@b.co", "password": PASSWORD})
    assert r.status_code == 409


def test_존재하지_않는_계정과_틀린_비밀번호가_같은_응답(client):
    """계정 열거 방지 — 응답으로 가입 여부를 알 수 없어야 한다."""
    client.post("/api/v1/auth/register", json={"email": "a@b.co", "password": PASSWORD})

    wrong_pw = client.post("/api/v1/auth/login",
                           json={"email": "a@b.co", "password": "wrong password!!"})
    no_user = client.post("/api/v1/auth/login",
                          json={"email": "nobody@b.co", "password": PASSWORD})

    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()


def test_refresh_토큰으로_API_호출_불가(client):
    client.post("/api/v1/auth/register", json={"email": "a@b.co", "password": PASSWORD})
    tokens = client.post("/api/v1/auth/login",
                         json={"email": "a@b.co", "password": PASSWORD}).json()

    r = client.get("/api/v1/me/profile", headers=_auth(tokens["refresh_token"]))
    assert r.status_code == 401


def test_refresh_로_새_access_발급(client):
    client.post("/api/v1/auth/register", json={"email": "a@b.co", "password": PASSWORD})
    tokens = client.post("/api/v1/auth/login",
                         json={"email": "a@b.co", "password": PASSWORD}).json()

    r = client.post("/api/v1/auth/refresh",
                    json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    assert client.get("/api/v1/me/profile",
                      headers=_auth(r.json()["access_token"])).status_code in (200, 404)


# ---------------------------------------------------------------------------
# 자산 프로필 — 암호화 저장 (G3)
# ---------------------------------------------------------------------------

def test_프로필_저장_후_조회(client):
    token = _register_and_login(client, "a@b.co")
    payload = {"cash_krw": 300_000_000, "income_krw": 90_000_000,
               "existing_loan_krw": 50_000_000, "owned_houses": 0, "household_size": 3}

    r = client.put("/api/v1/me/profile", json=payload, headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["cash_krw"] == 300_000_000

    r = client.get("/api/v1/me/profile", headers=_auth(token))
    assert r.json()["income_krw"] == 90_000_000


def test_저장소에_평문_금액이_남지_않는다(client):
    """G3 — DB 덤프가 유출돼도 금액이 보이면 안 된다."""
    token = _register_and_login(client, "a@b.co")
    client.put("/api/v1/me/profile",
               json={"cash_krw": 300_000_000, "income_krw": 90_000_000},
               headers=_auth(token))

    stored = client.repo.get_profile(1)
    assert isinstance(stored.cash_krw_enc, bytes)
    assert b"300000000" not in stored.cash_krw_enc
    assert b"90000000" not in stored.income_krw_enc
    # 평문 컬럼이 실수로 추가되지 않았는지
    assert not hasattr(stored, "cash_krw")


def test_남의_프로필은_보이지_않는다(client):
    """서로 다른 사용자가 자기 것만 본다."""
    t1 = _register_and_login(client, "a@b.co")
    t2 = _register_and_login(client, "b@b.co")

    client.put("/api/v1/me/profile", json={"cash_krw": 111_000_000, "income_krw": 1},
               headers=_auth(t1))
    client.put("/api/v1/me/profile", json={"cash_krw": 222_000_000, "income_krw": 2},
               headers=_auth(t2))

    assert client.get("/api/v1/me/profile", headers=_auth(t1)).json()["cash_krw"] == 111_000_000
    assert client.get("/api/v1/me/profile", headers=_auth(t2)).json()["cash_krw"] == 222_000_000


def test_음수_자산은_거부(client):
    token = _register_and_login(client, "a@b.co")
    r = client.put("/api/v1/me/profile", json={"cash_krw": -1, "income_krw": 0},
                   headers=_auth(token))
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 실구매 가능 금액
# ---------------------------------------------------------------------------

def test_프로필_없이_계산하면_422(client):
    token = _register_and_login(client, "a@b.co")
    r = client.post("/api/v1/affordability", json={}, headers=_auth(token))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "INSUFFICIENT_DATA"


def test_실구매가능금액_계산(client):
    token = _register_and_login(client, "a@b.co")
    client.put("/api/v1/me/profile",
               json={"cash_krw": 300_000_000, "income_krw": 200_000_000},
               headers=_auth(token))

    r = client.post("/api/v1/affordability", json={"area_m2": 84.0}, headers=_auth(token))
    assert r.status_code == 200
    body = r.json()

    assert body["max_purchase_krw"] > 0
    assert body["breakdown"]["binding_constraint"] in {"LTV", "DSR", "DTI", "CASH"}
    assert body["evidence"], "출처 없는 금액은 내보내면 안 된다"
    assert "투자 권유가 아니" in body["disclaimer"]


def test_세율설정이_검증되지_않으면_503(client, monkeypatch, tmp_path):
    """추정해서 보여주느니 거부한다.

    운영 config/tax_rules.yaml 은 이제 검증본(ORDER 2026-07-25-04-data)이므로,
    가드레일은 **미검증 파일**을 가리켜 검증한다.
    """
    token = _register_and_login(client, "a@b.co")
    client.put("/api/v1/me/profile", json={"cash_krw": 1, "income_krw": 1},
               headers=_auth(token))

    unverified = tmp_path / "unverified.yaml"
    unverified.write_text("version: 'x'\nstatus: unverified\n", encoding="utf-8")

    from app.core.config import get_settings
    monkeypatch.setenv("TAX_RULES_PATH", str(unverified))
    get_settings.cache_clear()

    r = client.post("/api/v1/affordability", json={}, headers=_auth(token))
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "TAX_RULES_UNAVAILABLE"
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 지도
# ---------------------------------------------------------------------------

def _seed_complexes(repo):
    for i, (lon, lat, region) in enumerate([
        (127.05, 37.51, "1168000000"),
        (127.06, 37.52, "1168000000"),
        (126.95, 37.55, "1114000000"),
    ], start=1):
        repo.add_complex(ComplexSummary(
            id=i, name=f"단지{i}", lon=lon, lat=lat, region_code=region,
            built_year=2010 + i, total_households=500 + i,
            recent_price_krw=1_000_000_000 + i * 100_000_000,
            price_as_of="2026-06-30", active_listings=i,
        ))


def test_지도_단지조회(client):
    token = _register_and_login(client, "a@b.co")
    _seed_complexes(client.repo)

    r = client.get("/api/v1/map/complexes",
                   params={"bbox": "126.9,37.4,127.1,37.6", "zoom": 15},
                   headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["level"] == "complex"
    assert len(body["items"]) == 3


def test_시세에는_기준일과_신뢰도가_붙는다(client):
    """실거래 신고 지연 때문에 '현재가'라고 말하면 안 된다."""
    token = _register_and_login(client, "a@b.co")
    _seed_complexes(client.repo)

    body = client.get("/api/v1/map/complexes",
                      params={"bbox": "126.9,37.4,127.1,37.6", "zoom": 15},
                      headers=_auth(token)).json()

    item = body["items"][0]
    assert item["price_as_of"] == "2026-06-30"
    assert item["price_confidence"] == "estimated"
    assert "30일" in body["note"]


def test_줌아웃하면_군집으로_반환(client):
    token = _register_and_login(client, "a@b.co")
    _seed_complexes(client.repo)

    body = client.get("/api/v1/map/complexes",
                      params={"bbox": "126.9,37.4,127.1,37.6", "zoom": 10},
                      headers=_auth(token)).json()

    assert body["level"] == "cluster"
    counts = {c["region_code"]: c["count"] for c in body["items"]}
    assert counts == {"1168000000": 2, "1114000000": 1}


def test_예산초과_단지는_지우지_않고_표시만(client):
    """왜 후보에 없는지 보이게 한다 (ux/README.md §4)."""
    token = _register_and_login(client, "a@b.co")
    _seed_complexes(client.repo)

    body = client.get("/api/v1/map/complexes",
                      params={"bbox": "126.9,37.4,127.1,37.6", "zoom": 15,
                              "max_price_krw": 1_150_000_000},
                      headers=_auth(token)).json()

    assert len(body["items"]) == 3, "예산 초과라고 목록에서 지우면 안 된다"
    assert sum(1 for i in body["items"] if i["over_budget"]) == 2


def test_잘못된_bbox는_400(client):
    token = _register_and_login(client, "a@b.co")
    r = client.get("/api/v1/map/complexes", params={"bbox": "bad", "zoom": 15},
                   headers=_auth(token))
    assert r.status_code == 400


def test_지나치게_넓은_범위는_400(client):
    token = _register_and_login(client, "a@b.co")
    r = client.get("/api/v1/map/complexes",
                   params={"bbox": "120.0,30.0,130.0,40.0", "zoom": 15},
                   headers=_auth(token))
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 추천 — IDOR 방지 (T6)
# ---------------------------------------------------------------------------

def test_추천요청은_202와_job_id(client):
    token = _register_and_login(client, "a@b.co")
    r = client.post("/api/v1/recommendations",
                    json={"region_codes": ["1168000000"]}, headers=_auth(token))

    assert r.status_code == 202
    assert r.json()["job_id"].startswith("rec_")
    assert r.headers["Location"].endswith(r.json()["job_id"])


def test_남의_추천결과는_조회할_수_없다(client):
    """T6 — job_id 를 알아도 남의 것은 못 본다."""
    t1 = _register_and_login(client, "a@b.co")
    t2 = _register_and_login(client, "b@b.co")

    job_id = client.post("/api/v1/recommendations", json={},
                         headers=_auth(t1)).json()["job_id"]

    assert client.get(f"/api/v1/recommendations/{job_id}",
                      headers=_auth(t1)).status_code == 200
    r = client.get(f"/api/v1/recommendations/{job_id}", headers=_auth(t2))
    assert r.status_code == 404, "남의 작업 존재 여부조차 알려주면 안 된다"


def test_추천_응답에_면책고지(client):
    token = _register_and_login(client, "a@b.co")
    job_id = client.post("/api/v1/recommendations", json={},
                         headers=_auth(token)).json()["job_id"]

    body = client.get(f"/api/v1/recommendations/{job_id}", headers=_auth(token)).json()
    assert "투자 권유가 아니" in body["disclaimer"]
    assert body["criteria_snapshot"], "재현성을 위해 조건이 동결돼야 한다"


# ---------------------------------------------------------------------------
# 보안 헤더
# ---------------------------------------------------------------------------

def test_보안헤더가_붙는다(client):
    h = client.get("/api/v1/health").headers
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "DENY"
    assert "max-age" in h["Strict-Transport-Security"]


def test_운영모드에서_스키마가_공개되지_않는다(client):
    assert client.get("/api/docs").status_code == 404
    assert client.get("/api/openapi.json").status_code == 404


# ---------------------------------------------------------------------------
# 접근 로그에 민감정보가 남지 않는가 (G3)
# ---------------------------------------------------------------------------

def test_민감경로는_쿼리스트링을_로그에_남기지_않는다(client, caplog):
    import logging
    token = _register_and_login(client, "a@b.co")
    caplog.set_level(logging.INFO, logger="app")

    client.put("/api/v1/me/profile",
               json={"cash_krw": 300_000_000, "income_krw": 90_000_000},
               headers=_auth(token))

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "/api/v1/me/profile" in logged
    assert "300000000" not in logged, "금액이 로그에 남으면 안 된다"
    assert "90000000" not in logged


def test_일반경로는_쿼리스트링이_남는다(client, caplog):
    import logging
    token = _register_and_login(client, "a@b.co")
    caplog.set_level(logging.INFO, logger="app")

    client.get("/api/v1/map/complexes",
               params={"bbox": "126.9,37.4,127.1,37.6", "zoom": 15},
               headers=_auth(token))

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "zoom=15" in logged, "일반 경로는 디버깅을 위해 쿼리가 필요하다"
