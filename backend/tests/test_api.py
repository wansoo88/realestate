"""API 계약 테스트 — 인메모리 리포지토리로 DB 없이 검증.

중점: **IDOR 방지**와 **민감정보 취급**. 기능보다 이쪽이 더 중요하다.
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.repositories.base import ComplexSummary
from app.repositories.memory import InMemoryRepository

FIXTURES = Path(__file__).parent / "fixtures"
PASSWORD = "correct horse battery staple"
JWT_SECRET = "x" * 40

#: CSRF 2차 방어 헤더 (security.md §2.1 / SR15-1). 쿠키 인증 엔드포인트는 이걸 요구한다.
AJAX = {"X-Requested-With": "XMLHttpRequest"}

REFRESH_COOKIE = "refresh_token"
REFRESH_PATH = "/api/v1/auth"


def _set_test_env(monkeypatch) -> None:
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "k" * 32)
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    monkeypatch.setenv("TAX_RULES_PATH", str(FIXTURES / "tax_rules_test.yaml"))


def _make_client(monkeypatch, base_url: str):
    _set_test_env(monkeypatch)

    from app.core.config import get_settings
    get_settings.cache_clear()

    from app.main import create_app
    repo = InMemoryRepository()
    app = create_app(repo=repo)
    client = TestClient(app, base_url=base_url)
    client.repo = repo
    return client


@pytest.fixture()
def client(monkeypatch):
    with _make_client(monkeypatch, "http://testserver") as c:
        yield c
    from app.core.config import get_settings
    get_settings.cache_clear()


@pytest.fixture()
def https_client(monkeypatch):
    """https 로 말하는 클라이언트 — refresh 쿠키 왕복 검증용.

    httpx 쿠키 저장소는 **`Secure` 쿠키를 http 응답에서 저장하지 않는다**(브라우저와 같은 규칙).
    그래서 평문 http 클라이언트로는 "쿠키가 실제로 오가는가"를 검증할 수 없다.
    설정을 느슨하게(`COOKIE_SECURE=false`) 바꿔 우회하지 않고, **운영과 동일한
    Secure=on 조건 그대로** https 로 왕복시킨다.
    """
    with _make_client(monkeypatch, "https://testserver") as c:
        yield c
    from app.core.config import get_settings
    get_settings.cache_clear()


def _approve(client, email: str) -> int:
    """가입 대기 계정을 승인한다 (관리자 승인제 · migrations/009).

    가입 직후 상태는 `pending` 이고 로그인은 403 이다. 테스트가 **명시적으로** 승인한다 —
    편의를 위해 프로덕션 기본값을 approved 로 되돌리면 승인제 자체가 사라지고,
    그걸 잡아 줄 테스트도 함께 사라진다.
    """
    user = client.repo.get_user_by_email(email)
    assert user is not None and user.status == "pending", "가입 기본값은 승인 대기여야 한다"
    client.repo.set_user_status(user.id, "approved", actor="cli")
    return user.id


def _register_and_login(client, email: str) -> str:
    r = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    _approve(client, email)
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
    """수명이 긴 refresh 로 API 를 계속 호출하는 것을 막는다(`typ` 클레임 검증)."""
    from app.core.security import create_token

    refresh = create_token(1, secret=JWT_SECRET, kind="refresh")
    assert client.get("/api/v1/me/profile", headers=_auth(refresh)).status_code == 401


# ---------------------------------------------------------------------------
# refresh 토큰 = httpOnly 쿠키 (security.md §2.1 · SR15-1)
#
# 이 절의 테스트는 "설계가 금지한 저장 위치를 코드가 다시 쓰지 못하게" 고정하는 장치다.
# 하나라도 깨지면 XSS 한 번에 자산·소득 계정의 자격증명이 통째로 넘어가는 상태로 돌아간다.
# ---------------------------------------------------------------------------

def _login(client, email: str = "a@b.co") -> httpx.Response:
    r = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    _approve(client, email)
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r


def test_login_응답_본문에_refresh_token이_없다(https_client):
    body = _login(https_client).json()

    assert set(body) == {"access_token", "token_type", "expires_in"}
    assert "refresh_token" not in body
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 1800


def test_login이_httpOnly_Secure_SameSite_Path_쿠키를_설정한다(https_client):
    raw = _login(https_client).headers["set-cookie"]
    lowered = raw.lower()

    assert raw.startswith(f"{REFRESH_COOKIE}=")
    assert "httponly" in lowered            # JS 가 읽지 못한다
    assert "secure" in lowered              # 평문 http 로 나가지 않는다
    assert "samesite=strict" in lowered     # CSRF 1차 방어
    assert f"path={REFRESH_PATH}" in lowered
    assert f"max-age={7 * 24 * 3600}" in lowered   # REFRESH_TTL 7일 (SR15-1)
    # 실제로 저장돼 이후 요청에 실린다
    assert https_client.cookies.get(REFRESH_COOKIE)


def test_refresh_쿠키는_auth_경로_밖으로_나가지_않는다(https_client):
    """`Path` 를 좁혀 지도·추천 등 모든 요청에 refresh 가 따라다니지 않게 한다."""
    _login(https_client)

    outside = httpx.Request("GET", "https://testserver/api/v1/me/profile")
    https_client.cookies.set_cookie_header(outside)
    assert REFRESH_COOKIE not in outside.headers.get("cookie", "")

    inside = httpx.Request("POST", "https://testserver/api/v1/auth/refresh")
    https_client.cookies.set_cookie_header(inside)
    assert REFRESH_COOKIE in inside.headers.get("cookie", "")


def test_refresh는_쿠키로_동작하고_쿠키를_회전한다(https_client):
    _login(https_client)
    before = https_client.cookies.get(REFRESH_COOKIE)

    # 본문 없이 — 쿠키만으로 인증된다
    r = https_client.post("/api/v1/auth/refresh", headers=AJAX)
    assert r.status_code == 200, r.text
    assert "refresh_token" not in r.json()

    after = https_client.cookies.get(REFRESH_COOKIE)
    assert after and after != before, "회전하지 않으면 같은 값을 계속 재사용하게 된다"

    # 새 access 는 실제로 쓸 수 있고, 회전된 쿠키로 또 갱신된다
    assert https_client.get("/api/v1/me/profile",
                            headers=_auth(r.json()["access_token"])).status_code in (200, 404)
    assert https_client.post("/api/v1/auth/refresh", headers=AJAX).status_code == 200


def test_쿠키_없이_refresh하면_401(https_client):
    r = https_client.post("/api/v1/auth/refresh", headers=AJAX)
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "UNAUTHORIZED"


def _forged_cookie(value: str) -> dict[str, str]:
    """공격자가 임의의 값을 refresh 쿠키로 보내는 상황.

    쿠키 저장소에 넣지 않고 헤더로 직접 싣는다 — 저장소를 거치면 로그인이 심어 둔
    정상 쿠키와 **둘 다** 전송되어 무엇이 검증됐는지 알 수 없게 된다.
    (`Cookie` 헤더가 이미 있으면 httpx 는 저장소 값을 덧붙이지 않는다.)
    """
    return {**AJAX, "Cookie": f"{REFRESH_COOKIE}={value}"}


def test_무효한_refresh_쿠키는_401이면서_즉시_삭제된다(https_client):
    """못 쓰는 쿠키를 남겨두면 사용자가 실패를 무한 반복한다."""
    _login(https_client)

    r = https_client.post("/api/v1/auth/refresh", headers=_forged_cookie("not-a-jwt"))
    assert r.status_code == 401
    assert "max-age=0" in r.headers["set-cookie"].lower()
    # 삭제 헤더가 실제로 저장소의 쿠키를 지운다(= 속성이 발급 때와 일치한다)
    assert https_client.cookies.get(REFRESH_COOKIE) is None


def test_access_토큰을_refresh_쿠키에_넣으면_거부(https_client):
    """토큰 종류 위조 차단 — access 를 쿠키에 심어 갱신 루프를 돌릴 수 없다."""
    access = _login(https_client).json()["access_token"]

    r = https_client.post("/api/v1/auth/refresh", headers=_forged_cookie(access))
    assert r.status_code == 401


def test_커스텀_헤더_없는_refresh는_거부(https_client):
    """CSRF 2차 방어 — HTML 폼은 커스텀 헤더를 붙일 수 없다."""
    _login(https_client)

    r = https_client.post("/api/v1/auth/refresh")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "CSRF_HEADER_REQUIRED"
    # 거절이 로그아웃으로 이어지면 안 된다(로그아웃 CSRF 가 된다)
    assert "set-cookie" not in r.headers
    assert https_client.cookies.get(REFRESH_COOKIE)


def test_커스텀_헤더_없는_logout도_거부(https_client):
    _login(https_client)

    assert https_client.post("/api/v1/auth/logout").status_code == 403
    assert https_client.cookies.get(REFRESH_COOKIE)


def test_logout이_쿠키를_만료시킨다(https_client):
    _login(https_client)
    assert https_client.cookies.get(REFRESH_COOKIE)

    r = https_client.post("/api/v1/auth/logout", headers=AJAX)
    assert r.status_code == 204
    lowered = r.headers["set-cookie"].lower()
    assert "max-age=0" in lowered
    assert f"path={REFRESH_PATH}" in lowered
    assert "httponly" in lowered and "secure" in lowered and "samesite=strict" in lowered

    # 저장소에서 사라졌고, 더는 갱신되지 않는다
    assert https_client.cookies.get(REFRESH_COOKIE) is None
    assert https_client.post("/api/v1/auth/refresh", headers=AJAX).status_code == 401


def test_refresh는_본문을_받지_않는다(https_client):
    """본문 경로를 남겨두면 쿠키로 옮긴 의미가 없다 — 공격자는 편한 쪽을 고른다."""
    _login(https_client)
    stolen = https_client.cookies.get(REFRESH_COOKIE)
    https_client.cookies.clear()

    r = https_client.post("/api/v1/auth/refresh", headers=AJAX,
                          json={"refresh_token": stolen})
    assert r.status_code == 401, "본문에 실은 refresh 가 받아들여지면 안 된다"


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


# ---------------------------------------------------------------------------
# 희망 매매가 자금계획 (ORDER 2026-07-26)
#
# 계약: `target_price_krw` 를 주면 응답에 `plan` 이 붙는다. 안 주면 예전과 동일.
# ---------------------------------------------------------------------------

def _profile_and_plan(client, target_price_krw, **extra):
    token = _register_and_login(client, "a@b.co")
    client.put("/api/v1/me/profile",
               json={"cash_krw": 300_000_000, "income_krw": 100_000_000},
               headers=_auth(token))
    body = {"area_m2": 84.0, **extra}
    if target_price_krw is not None:
        body["target_price_krw"] = target_price_krw
    return client.post("/api/v1/affordability", json=body, headers=_auth(token))


def test_희망가를_주면_자금계획이_붙는다(client):
    r = _profile_and_plan(client, 600_000_000)
    assert r.status_code == 200, r.text
    body = r.json()

    plan = body["plan"]
    assert plan["target_price_krw"] == 600_000_000
    # 계약 필드가 전부 있어야 한다 — 하나만 빠져도 프론트가 화면을 못 그린다.
    for key in ("total_needed_krw", "cost_breakdown", "own_cash_krw", "shortfall_krw",
                "required_loan_krw", "loan_feasible", "loan_limit_krw",
                "over_limit_krw", "binding_constraint", "monthly_payment_krw",
                "total_interest_krw", "terms"):
        assert key in plan, f"plan.{key} 누락"
    assert set(plan["cost_breakdown"]) >= {"tax", "brokerage", "etc"}

    # 부족액 = 총필요자금 − 내 현금, 필요대출 = 부족액. 화면 숫자가 서로 안 맞으면 안 된다.
    assert plan["total_needed_krw"] == 600_000_000 + plan["cost_breakdown"]["total"]
    assert plan["shortfall_krw"] == plan["total_needed_krw"] - plan["own_cash_krw"]
    assert plan["required_loan_krw"] == plan["shortfall_krw"]
    assert plan["monthly_payment_krw"] > 0
    # '내 돈'은 기존 breakdown 과 같은 값이어야 한다(두 개가 뜨면 사용자가 혼란스럽다).
    assert plan["own_cash_krw"] == body["breakdown"]["own_cash_krw"]


def test_희망가를_조건에_저장하면_그대로_돌아온다(client):
    """프론트는 슬라이더 값을 `prefer.target_price_krw` 로 저장한다(재방문 시 복원).

    `prefer` 는 자유 형식 jsonb 라 스키마 변경은 필요 없지만, **왕복이 실제로 되는지**는
    확인해 둔다 — 여기서 값이 사라지면 슬라이더가 매번 초기화되는데, 그건 화면 버그로만
    보이고 원인이 서버에 있다는 걸 아무도 짐작하지 못한다.
    """
    token = _register_and_login(client, "a@b.co")
    r = client.put("/api/v1/me/preferences",
                   json={"prefer": {"target_price_krw": 900_000_000}},
                   headers=_auth(token))
    assert r.status_code == 200, r.text
    got = client.get("/api/v1/me/preferences", headers=_auth(token)).json()
    assert got["prefer"]["target_price_krw"] == 900_000_000


def test_희망가를_안_주면_plan_키가_없다(client):
    """기존 클라이언트 회귀 금지 — 응답 모양이 바뀌면 안 된다."""
    r = _profile_and_plan(client, None)
    assert r.status_code == 200, r.text
    assert "plan" not in r.json()


def test_희망가가_한도를_넘어도_200이고_이유를_준다(client):
    """'불가능합니다'로 끝내지 않는다 — 얼마가 모자란지·무엇이 막는지를 준다."""
    r = _profile_and_plan(client, 30_000_000_000)     # 300억
    assert r.status_code == 200, r.text
    plan = r.json()["plan"]

    assert plan["loan_feasible"] is False
    assert plan["over_limit_krw"] > 0
    assert plan["binding_constraint"] in {"LTV", "DSR", "DTI", "CAP"}
    assert plan["over_limit_krw"] == plan["required_loan_krw"] - plan["loan_limit_krw"]
    assert any("초과" in w for w in r.json()["warnings"])


@pytest.mark.parametrize("bad", [0, -1, 100_000_000_001])
def test_잘못된_희망가는_422(client, bad):
    """0·음수·상한초과(1000억)는 조용히 계산하지 않고 되돌린다."""
    assert _profile_and_plan(client, bad).status_code == 422


def test_금리를_바꾸면_월상환액이_바뀌고_terms에_드러난다(client):
    """금리 4%는 **가정**이다 — 사용자가 덮을 수 있고, 어떤 값을 썼는지 응답이 밝힌다."""
    base = _profile_and_plan(client, 600_000_000).json()["plan"]

    token = _register_and_login(client, "b@b.co")
    client.put("/api/v1/me/profile",
               json={"cash_krw": 300_000_000, "income_krw": 100_000_000},
               headers=_auth(token))
    higher = client.post("/api/v1/affordability",
                         json={"area_m2": 84.0, "target_price_krw": 600_000_000,
                               "annual_rate": 0.055},
                         headers=_auth(token)).json()["plan"]

    assert base["terms"]["annual_rate_pct"] == 4.0
    assert higher["terms"]["annual_rate_pct"] == 5.5
    assert higher["monthly_payment_krw"] > base["monthly_payment_krw"]
    assert higher["total_interest_krw"] > base["total_interest_krw"]


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


def test_요청스키마에_권역필드가_없다():
    """CR10-1: 권역은 서버 판정값 — 클라이언트가 보낼 수 없다."""
    from app.api.schemas import AffordabilityIn
    assert "target_region_code" not in AffordabilityIn.model_fields
    assert "region_group" not in AffordabilityIn.model_fields
    # 보내도 모델이 싣지 않는다(extra 무시) → 라우터가 실수로 읽을 수도 없다
    m = AffordabilityIn(target_region_code="26110", region_group="비수도권", area_m2=84.0)
    assert not hasattr(m, "target_region_code")
    assert not hasattr(m, "region_group")


def test_클라이언트는_권역으로_6억캡을_끌_수_없다(client, monkeypatch):
    """CR10-1 회귀: 비수도권 코드를 보내도 캡이 꺼지지 않는다(우회 원천 차단)."""
    token = _register_and_login(client, "a@b.co")
    client.put("/api/v1/me/profile",
               json={"cash_krw": 1_000_000_000, "income_krw": 300_000_000},
               headers=_auth(token))

    from app.core.config import get_settings
    monkeypatch.setenv("TAX_RULES_PATH", str(FIXTURES / "tax_rules_capital_test.yaml"))
    get_settings.cache_clear()

    # 비수도권 코드로 캡 우회 시도
    attack = client.post("/api/v1/affordability",
                         json={"area_m2": 84.0, "target_region_code": "26110",
                               "region_group": "비수도권"},
                         headers=_auth(token))
    assert attack.status_code == 200, attack.text
    bd = attack.json()["breakdown"]
    assert bd["absolute_cap_krw"] == 600_000_000    # 캡 그대로 적용
    assert bd["binding_constraint"] == "CAP"

    # 아무 것도 안 보낸 정상 요청과 결과가 동일 — 클라이언트가 바꿀 수 없다
    normal = client.post("/api/v1/affordability",
                         json={"area_m2": 84.0}, headers=_auth(token))
    assert normal.json()["max_purchase_krw"] == attack.json()["max_purchase_krw"]
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
