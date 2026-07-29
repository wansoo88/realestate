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


def test_검증_실패_응답에_사용자가_보낸_값이_되돌아오지_않는다(client):
    """★ FastAPI 기본 검증 핸들러는 `input`(원본 값)을 응답에 싣는다.

    비밀번호가 짧으면 **평문 비밀번호가 응답 본문에** 담겨 돌아왔다(실측).
    보낸 사람에게 돌려주는 것이라 유출은 아니지만, 그 값이 브라우저 콘솔·프론트
    오류 리포팅·프록시 캐시에 남을 자리가 너무 많다. 그리고 `Infinity`·`NaN` 이
    들어오면 그 `input` 때문에 JSON 직렬화가 깨져 **422 가 500 이 된다**(SR24-6).
    """
    secret = "short-pw-12"                       # 12자 미만이라 검증에서 떨어진다
    r = client.post("/api/v1/auth/register",
                    json={"email": "x@y.co", "password": secret})
    assert r.status_code == 422, r.text
    assert secret not in r.text, "검증 실패 응답에 비밀번호가 그대로 들어 있다"
    assert "input" not in r.text
    # 그래도 "어느 필드가 왜 틀렸는지"는 남아야 한다(진단 불가로 만들지 않는다).
    err = r.json()["detail"][0]
    assert err["loc"] == ["body", "password"] and err["msg"]


def test_커스텀_검증기_메시지에도_입력값이_실리지_않는다(client):
    """★ SR25-2 회귀 — `msg` 는 핸들러가 통과시키는 문자열이다.

    위 테스트가 지키는 것은 `input` 키를 지웠다는 사실뿐이다. 그런데 커스텀 검증기가
    `ValueError(f"... {값!r}")` 를 던지면 그 값이 **`msg` 를 타고 그대로** 돌아온다
    (실측: 3,000자 입력 → 응답 3,127바이트 전량 반사). 지금 필드는 법정동코드지만,
    같은 패턴이 자산·비밀번호 필드에 생기면 그날 조용히 사고가 된다.

    ★ 변이 대상: `_check_region_codes` 의 메시지에 `{code!r}` 를 되돌려 넣으면 실패한다.
    """
    token = _register_and_login(client, "reflect@y.co")
    marker = "MY-SECRET-VALUE-" + "A" * 3000
    r = client.post("/api/v1/recommendations",
                    json={"region_codes": [marker]}, headers=_auth(token))
    assert r.status_code == 422, r.text
    assert "MY-SECRET-VALUE" not in r.text, "검증 메시지로 입력값이 되돌아왔다"
    assert len(r.content) < 1000, f"응답이 입력 크기를 따라 커졌다({len(r.content)}바이트)"
    # 진단은 가능해야 한다 — 어느 필드의 몇 번째 항목이 틀렸는지는 남는다.
    err = r.json()["detail"][0]
    assert err["loc"][:2] == ["body", "region_codes"]
    assert "region_codes[0]" in err["msg"]


def test_검증_메시지는_길이_상한을_넘지_못한다(client):
    """★ SR25-2 두 번째 그물 — 검증기가 값을 넣더라도 **되비치는 양**은 묶인다.

    핸들러를 직접 호출한다. 위 테스트는 지금 검증기들이 값을 안 넣는다는 사실에
    의존하므로, 상한을 지워도 초록이다(실측). 상한이 하중을 받게 하려면
    "값을 넣은 검증기"를 흉내 내야 한다 — 그게 이 테스트다.
    """
    import asyncio
    import json as _json

    from fastapi.exceptions import RequestValidationError

    from app.main import MAX_VALIDATION_MSG_CHARS

    handler = client.app.exception_handlers[RequestValidationError]
    huge = "값-" + "A" * 5000
    exc = RequestValidationError([
        {"type": "value_error", "loc": ("body", "x"), "msg": huge, "input": huge}])
    resp = asyncio.run(handler(None, exc))

    body = _json.loads(resp.body)
    assert len(body["detail"][0]["msg"]) <= MAX_VALIDATION_MSG_CHARS
    assert len(resp.body) < 1000, len(resp.body)
    assert "input" not in resp.body.decode("utf-8")


def test_무한대_입력도_500이_아니라_422로_돌아온다(client):
    """검증 실패 응답 자체가 직렬화로 깨지면, 막았다는 사실이 사용자에게 500 으로 보인다."""
    token = _register_and_login(client, "inf@y.co")
    r = client.post("/api/v1/recommendations",
                    content='{"area_min_m2": Infinity}',
                    headers={**_auth(token), "Content-Type": "application/json"})
    assert r.status_code == 422, r.text


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
    """지도 단지 3건.

    ⚠️ `price_area_m2` 를 **반드시 함께** 넣는다. PostGIS 조회는 가격·기준일·면적을
       한 거래 행(LATERAL 1건)에서 가져오므로 **금액이 있으면 면적도 있다** — 인메모리
       픽스처가 면적만 비워 두면 운영에 없는 상태를 테스트가 표준으로 삼게 된다.
       면적을 세 값으로 나눠 둔 것도 의도적이다: 예산 상한은 면적의 함수라
       (취득세 농특세 85㎡ 경계) 한 면적만 쓰면 그 사실을 밟지 못한다(CR37-1).
    """
    for i, (lon, lat, region, area) in enumerate([
        (127.05, 37.51, "1168000000", 59.94),
        (127.06, 37.52, "1168000000", 84.97),
        (126.95, 37.55, "1114000000", 114.50),
    ], start=1):
        repo.add_complex(ComplexSummary(
            id=i, name=f"단지{i}", lon=lon, lat=lat, region_code=region,
            built_year=2010 + i, total_households=500 + i,
            recent_price_krw=1_000_000_000 + i * 100_000_000,
            price_as_of="2026-06-30", price_area_m2=area, active_listings=i,
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
    """왜 후보에 없는지 보이게 한다 (ux/README.md §4).

    ★ SR32-1 이후 **예산 금액은 요청에 실리지 않는다.** 클라이언트는 기준만 말하고
    (`budget=profile`) 서버가 저장된 희망 매매가로 상한을 정한다.
    """
    token = _register_and_login(client, "a@b.co")
    _seed_complexes(client.repo)
    # 저장된 "내 조건"의 희망 매매가 = 지도의 상한. 값은 **본문**으로만 오간다.
    client.put("/api/v1/me/preferences",
               json={"prefer": {"target_price_krw": 1_150_000_000}},
               headers=_auth(token))

    body = client.get("/api/v1/map/complexes",
                      params={"bbox": "126.9,37.4,127.1,37.6", "zoom": 15,
                              "budget": "mine"},
                      headers=_auth(token)).json()

    assert len(body["items"]) == 3, "예산 초과라고 목록에서 지우면 안 된다"
    assert sum(1 for i in body["items"] if i["over_budget"]) == 2
    assert body["budget"] == {"applied": True, "basis": "target_price", "reason": None}
    assert "krw" not in body["budget"], "금액은 응답에도 싣지 않는다(최소 노출)"


def test_예산_기준을_안_걸면_초과판정은_null(client):
    """**모름을 아님으로 접지 않는다.** 예전에는 예산을 몰라도 `false`(= 예산 안)였다."""
    token = _register_and_login(client, "a@b.co")
    _seed_complexes(client.repo)

    body = client.get("/api/v1/map/complexes",
                      params={"bbox": "126.9,37.4,127.1,37.6", "zoom": 15},
                      headers=_auth(token)).json()

    assert all(i["over_budget"] is None for i in body["items"])
    assert body["budget"]["applied"] is False


def test_지도_예산은_자산으로_서버가_계산한다(client):
    """희망가가 없으면 **저장된 자산**으로 한도를 산출한다 — 클라이언트는 금액을 모른다.

    변이: `_resolve_map_budget` 이 프로필 분기를 안 타면(항상 None) 초과 판정이
    전부 null 이 되어 여기서 깨진다.
    """
    token = _register_and_login(client, "a@b.co")
    _seed_complexes(client.repo)
    client.put("/api/v1/me/profile",
               json={"cash_krw": 200_000_000, "income_krw": 60_000_000},
               headers=_auth(token))

    body = client.get("/api/v1/map/complexes",
                      params={"bbox": "126.9,37.4,127.1,37.6", "zoom": 15,
                              "budget": "mine"},
                      headers=_auth(token)).json()

    assert body["budget"] == {"applied": True, "basis": "max_purchase", "reason": None}
    # 자산 2억·소득 6천만으로 11~13억 단지를 다 살 수는 없다 — 판정이 실제로 돈다.
    assert any(i["over_budget"] for i in body["items"])
    # 그 금액이 `/affordability` 와 **같은 값**인지 — 두 화면이 다른 상한을 말하면 안 된다.
    #
    # ⚠️ **이 루프는 CR37-1(면적별 판정)을 지키지 못한다. 여기서 지킬 수 없다.**
    #    이 파일은 픽스처 세율(`fixtures/tax_rules_test.yaml`)로 도는데, 거기서는
    #    `t_first_small`(85㎡ 이하)과 `t_first_other` 의 합계 세율이 **둘 다 1.1%** 라
    #    한도가 면적과 무관하다(실측: 59.94·84.97·114.5㎡ 전부 568,250,000).
    #    그래서 서버를 고정 84㎡ 판정으로 되돌려도 이 루프는 **그대로 통과한다**
    #    (전 스위트 변이 실측 2026-07-29: 이 테스트는 안 죽는다).
    #    면적별 정확성은 **운영 세율로 도는 `test_map_budget_parity.py`** 가 지킨다 —
    #    그 파일만 이 변이에 죽는다. 여기서 지키는 것은 그보다 약한 명제다:
    #    *지도 판정이 `/affordability` 가 준 상한과 같은 부등호를 쓴다*
    #    (`price_area_m2` 배선과 가격 비교 방향).
    for item in body["items"]:
        afford = client.post("/api/v1/affordability",
                             json={"area_m2": item["price_area_m2"]},
                             headers=_auth(token)).json()
        limit = afford["max_purchase_krw"]
        assert item["over_budget"] == (item["recent_price_krw"] > limit), item


def test_자산도_희망가도_없으면_예산기준을_세우지_못했다고_말한다(client):
    token = _register_and_login(client, "a@b.co")
    _seed_complexes(client.repo)

    body = client.get("/api/v1/map/complexes",
                      params={"bbox": "126.9,37.4,127.1,37.6", "zoom": 15,
                              "budget": "mine"},
                      headers=_auth(token)).json()

    assert body["budget"]["applied"] is False
    assert "자산 정보가 없어" in body["budget"]["reason"], "왜 못 세웠는지 말해야 한다"
    assert all(i["over_budget"] is None for i in body["items"])


def test_옛_클라이언트가_금액을_보내면_거절한다(client):
    """★ SR32-1. **조용히 무시하지 않는다** — 무시하면 예산 조건이 소리 없이 풀린다.

    그리고 거절 문장에 **보낸 금액을 되비치지 않는다**(SR25-2 규약).
    """
    token = _register_and_login(client, "a@b.co")
    _seed_complexes(client.repo)

    r = client.get("/api/v1/map/complexes",
                   params={"bbox": "126.9,37.4,127.1,37.6", "zoom": 15,
                           "max_price_krw": 1_314_310_000},
                   headers=_auth(token))

    assert r.status_code == 400
    detail = r.json()["detail"]
    assert detail["code"] == "PARAM_REMOVED"
    assert "budget=mine" in detail["message"]
    assert "1314310000" not in r.text, "거절 응답이 금액을 되돌려주면 안 된다"


def test_예산_파라미터에_금액을_넣으면_422(client):
    """`budget` 은 열거값이다 — 숫자를 넣어 옛 방식으로 되돌아갈 수 없다."""
    token = _register_and_login(client, "a@b.co")
    r = client.get("/api/v1/map/complexes",
                   params={"bbox": "126.9,37.4,127.1,37.6", "zoom": 15,
                           "budget": "1314310000"},
                   headers=_auth(token))
    assert r.status_code == 422


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


def test_관심_단지가_접근_로그에_남지_않는다(client, caplog):
    """★ SR31-4. `?complex_id=1234` 는 값이 아니라 **어디를 사려는지**를 남긴다.

    이 저장소는 그 정보를 이미 민감하다고 분류했다(`UserListingRepository` docstring —
    SQL 안에 소유자 스코프를 넣은 근거가 바로 그 문장이다). 응답에서 막고 로그로
    흘리면 방어가 반쪽이다.

    변이: `main.log_target` 이 값을 다시 붙이면(`f"{path}?{query}"`) 여기서 깨진다.
    """
    import logging
    token = _register_and_login(client, "a@b.co")
    caplog.set_level(logging.INFO, logger="app")

    client.get("/api/v1/me/listings", params={"complex_id": 1234},
               headers=_auth(token))

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "/api/v1/me/listings" in logged, "경로 자체는 남아야 한다(운영 관측)"
    assert "1234" not in logged, "관심 단지 식별자가 접근 로그에 남았다"


def test_어떤_경로도_쿼리_값을_로그에_남기지_않는다(client, caplog):
    """★ SR32-1. **이 테스트는 예전에 정반대였다** — `test_일반경로는_쿼리스트링이_남는다`.

    그 테스트가 잠가 둔 동작이 곧 사고였다. `/map/complexes` 는 '일반 경로'로 분류돼
    쿼리가 통째로 로그에 남았고, 그 쿼리에는 `max_price_krw=1314310000`
    (= 암호화해 보관하던 자산·소득·대출을 복호화해 계산한 최대 구매가능 금액)이
    실려 있었다. 그래서 규칙을 뒤집는다: **값은 어디서도 남기지 않고, 이름만 남긴다.**
    """
    import logging
    token = _register_and_login(client, "a@b.co")
    caplog.set_level(logging.INFO, logger="app")

    client.get("/api/v1/map/complexes",
               params={"bbox": "126.9,37.4,127.1,37.6", "zoom": 15,
                       "built_after": 2011},
               headers=_auth(token))

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "/api/v1/map/complexes" in logged, "경로·파라미터 이름은 운영에 필요하다"
    assert "[q: bbox,built_after,zoom]" in logged
    for value in ("126.9", "37.4", "15", "2011"):
        assert value not in logged, f"쿼리 값 {value} 이 로그에 남았다"


def test_모든_GET_쿼리_값은_로그에_남지_않는다(client, caplog):
    """전수 그물 — **라우터에서 쿼리 파라미터를 뽑아** 카나리를 심고 로그를 검사한다.

    SR32-1 이 오래 안 보였던 이유는 새 엔드포인트가 생길 때마다 사람이 민감목록을
    갱신해야 했기 때문이다. 이 테스트는 목록을 읽지 않고 **앱에 실제로 등록된 GET
    경로**를 순회하므로, 내일 누가 `?annual_income=…` 을 추가해도 그날 깨진다.
    """
    import logging
    from fastapi.routing import APIRoute

    token = _register_and_login(client, "a@b.co")
    canary = "918273645"
    checked = 0

    caplog.set_level(logging.INFO, logger="app")
    for route in client.app.routes:
        if not isinstance(route, APIRoute) or "GET" not in route.methods:
            continue
        names = [p.name for p in route.dependant.query_params]
        if not names:
            continue
        # 경로 파라미터도 카나리로 채운다(`/recommendations/{job_id}` 등).
        path = route.path
        for param in route.dependant.path_params:
            path = path.replace("{%s}" % param.name, canary)
        client.get(path, params={n: canary for n in names}, headers=_auth(token))
        checked += 1

    assert checked >= 3, "쿼리 파라미터를 가진 GET 경로를 찾지 못했다 — 검사가 비었다"
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert canary not in logged, "쿼리·경로 값이 접근 로그에 남았다"


def test_500_이_나도_쿼리_값은_로그에_남지_않는다(monkeypatch, caplog):
    """★ SR33-1. **500 핸들러가 이 규칙의 예외였다.**

    위 전수 그물(`test_모든_GET_쿼리_값은…`)은 **500 을 한 번도 만들지 않는다.** 그래서
    `unhandled` 가 `mask_sensitive(str(request.url))` 로 쿼리를 통째로 남기는 것을
    한 건도 잡지 못했다 — `mask_sensitive` 는 dict 키로 찾는 구조 마스커라 문자열에
    아무 일도 안 한다(이름만 마스킹을 암시했다).

    이 줄이 특히 나쁜 이유: 앱 로거에서 **운영에 실제로 나가는 유일한 줄**이다.
    root 핸들러가 없어 미들웨어의 INFO 는 버려지고 ERROR 만 `lastResort` 로
    stderr(=`docker logs`)에 나간다. 값을 지우는 계층은 침묵하고 값을 담는 계층만
    말하던 상태다.

    변이: `log_target(...)` 을 `str(request.url)`(또는 옛 `mask_sensitive(...)`)로
    되돌리면 여기서 깨진다.
    """
    import logging

    class _BoomRepo(InMemoryRepository):
        def complexes_in_bbox(self, **kwargs):
            raise RuntimeError("리포지토리가 터졌다")

    _set_test_env(monkeypatch)
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.main import create_app

    repo = _BoomRepo()
    app = create_app(repo=repo)
    # ⚠️ `raise_server_exceptions=False` — 켜 두면 TestClient 가 예외를 다시 던져
    #    **500 응답 경로가 실행되지 않는다**(핸들러를 지나기는 하지만 응답을 못 본다).
    client = TestClient(app, raise_server_exceptions=False)
    client.repo = repo

    token = _register_and_login(client, "a@b.co")
    caplog.set_level(logging.INFO, logger="app")

    r = client.get("/api/v1/map/complexes",
                   params={"bbox": "126.9,37.4,127.1,37.6", "zoom": 15,
                           "built_after": 2011, "area_min_m2": 84.5},
                   headers=_auth(token))
    assert r.status_code == 500, r.text

    errors = [rec for rec in caplog.records if rec.levelno >= logging.ERROR]
    assert errors, "500 이 났는데 ERROR 로그가 없다 — 이 테스트가 경로를 안 밟았다"
    logged = "\n".join(rec.getMessage() for rec in errors)
    assert "/api/v1/map/complexes" in logged, "어느 경로에서 터졌는지는 남아야 한다"
    assert "[q: area_min_m2,bbox,built_after,zoom]" in logged, (
        "쿼리 **이름**은 남긴다 — 어떤 조건의 요청이 터졌는지는 운영 정보다")
    for value in ("126.9", "37.4", "2011", "84.5"):
        assert value not in logged, f"500 로그에 쿼리 값 {value} 이 남았다"

    get_settings.cache_clear()


def test_이름_자리에_들어온_값도_로그에_남지_않는다(client, caplog):
    """`?1314310000=x` 처럼 **파라미터 이름 자리에 값**을 넣는 경로까지 막는다.

    이름만 남기기로 한 결정의 뒷문이다 — 이름은 값이 아니라는 전제가 깨지는 자리.
    """
    import logging
    token = _register_and_login(client, "a@b.co")
    caplog.set_level(logging.INFO, logger="app")

    client.get("/api/v1/map/complexes?bbox=126.9,37.4,127.1,37.6&zoom=15"
               "&1314310000=x&a@b.co=y", headers=_auth(token))

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "1314310000" not in logged and "a@b.co" not in logged
    assert "+2" in logged, "버린 파라미터가 있었다는 사실 자체는 남긴다"
