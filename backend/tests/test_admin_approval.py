"""회원가입 관리자 승인제 — 계약·인가·계정 열거 방지 테스트 (migrations/009).

이 파일이 지키는 것 세 가지
---------------------------
1. **가입은 pending 으로만 된다.** 어떤 경로로도 스스로 approved 가 되지 않는다.
2. **계정 열거가 되지 않는다.** 틀린 비밀번호로는 pending 계정·거부 계정·없는 계정이
   전부 같은 401 이다. 상태는 **비밀번호를 아는 사람에게만** 보인다(SR10-1).
3. **관리자 권한은 서버 DB 가 판정한다.** 토큰이 주장하는 admin 은 무시되고,
   관리자가 아닌 쪽에서는 관리자 엔드포인트가 **없는 경로와 구분되지 않는다.**

⚠️ 승인은 테스트가 **명시적으로** 한다. "테스트가 번거로우니 기본값을 approved 로"는
   승인제를 무력화하는 가장 흔한 경로다 — 그 순간 이 파일 전체가 거짓말이 된다.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from app.repositories import base
from app.repositories.memory import InMemoryRepository

FIXTURES = Path(__file__).parent / "fixtures"
PASSWORD = "correct horse battery staple"
WRONG_PASSWORD = "wrong horse battery staple"
JWT_SECRET = "x" * 40
AJAX = {"X-Requested-With": "XMLHttpRequest"}
REFRESH_COOKIE = "refresh_token"

#: 존재하지 않는 경로. 관리자 엔드포인트가 이것과 **구분되지 않아야** 한다.
UNKNOWN_PATH = "/api/v1/definitely-not-a-route"


def _make_client(monkeypatch, base_url: str = "http://testserver"):
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "k" * 32)
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    monkeypatch.setenv("TAX_RULES_PATH", str(FIXTURES / "tax_rules_test.yaml"))

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
    with _make_client(monkeypatch) as c:
        yield c
    from app.core.config import get_settings
    get_settings.cache_clear()


@pytest.fixture()
def https_client(monkeypatch):
    """Secure 쿠키 왕복 검증용 (test_api.py 와 같은 이유)."""
    with _make_client(monkeypatch, "https://testserver") as c:
        yield c
    from app.core.config import get_settings
    get_settings.cache_clear()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register(client, email: str) -> int:
    r = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()["user_id"]


def _approve(client, email: str) -> int:
    """관리자가 하는 일을 테스트가 대신한다(리포지토리 경유 — 라우터를 우회하지 않는다)."""
    user = client.repo.get_user_by_email(email)
    client.repo.set_user_status(user.id, base.STATUS_APPROVED, actor="cli")
    return user.id


def _make_admin(client, email: str) -> int:
    uid = _approve(client, email)
    client.repo.set_user_admin(uid, True, actor="cli")
    return uid


def _login(client, email: str, password: str = PASSWORD) -> httpx.Response:
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _token(client, email: str) -> str:
    r = _login(client, email)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _same_response(a: httpx.Response, b: httpx.Response) -> bool:
    """두 응답이 **구분 불가능한가.** 상태·본문·컨텐츠타입을 모두 본다."""
    return (a.status_code == b.status_code
            and a.text == b.text
            and a.headers.get("content-type") == b.headers.get("content-type"))


# ---------------------------------------------------------------------------
# 1. 가입은 승인 대기로만 된다
# ---------------------------------------------------------------------------

def test_가입은_승인대기로_접수된다(client):
    r = client.post("/api/v1/auth/register",
                    json={"email": "new@b.co", "password": PASSWORD})

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == base.STATUS_PENDING
    assert "승인" in body["message"], "승인 대기라는 사실이 응답에 없으면 사용자는 로그인부터 시도한다"
    assert client.repo.get_user_by_email("new@b.co").status == base.STATUS_PENDING


def test_가입만으로는_관리자가_되지_않는다(client):
    """**첫 가입자 자동 관리자 금지.** 공개된 사이트에서는 선점당한다."""
    for email in ("first@b.co", "second@b.co"):
        _register(client, email)
        assert client.repo.get_user_by_email(email).is_admin is False
    assert client.repo.count_active_admins() == 0


def test_pending_계정은_비밀번호가_맞아도_로그인할_수_없다(client):
    _register(client, "a@b.co")

    r = _login(client, "a@b.co")

    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "PENDING_APPROVAL"
    assert "access_token" not in r.text
    assert r.cookies.get(REFRESH_COOKIE) is None, "승인 전에는 세션이 만들어지면 안 된다"


def test_승인되면_로그인된다(client):
    _register(client, "a@b.co")
    _approve(client, "a@b.co")

    r = _login(client, "a@b.co")

    assert r.status_code == 200, r.text
    assert r.json()["access_token"]


def test_거부된_계정은_거부됐다고_알려준다(client):
    _register(client, "a@b.co")
    uid = client.repo.get_user_by_email("a@b.co").id
    client.repo.set_user_status(uid, base.STATUS_REJECTED, actor="cli", reason="본인확인 불가")

    r = _login(client, "a@b.co")

    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "ACCOUNT_REJECTED"
    # 거부 사유는 감사 기록이지 사용자에게 보낼 문구가 아니다.
    assert "본인확인 불가" not in r.text


# ---------------------------------------------------------------------------
# 2. 계정 열거 방지 — 이 절이 이 파일의 핵심이다 (SR10-1)
#
# 승인제를 잘못 붙이면 "pending 이면 403" 을 비밀번호 검증 **앞에** 두게 되고,
# 그 순간 아무 비밀번호나 넣어 보는 것만으로 가입된 이메일 목록이 만들어진다.
# 아래 테스트들은 그 실수를 못 하게 못질한다.
# ---------------------------------------------------------------------------

def test_틀린_비밀번호로는_pending계정과_없는계정을_구분할_수_없다(client):
    _register(client, "pending@b.co")          # 가입돼 있지만 승인 대기

    on_pending = _login(client, "pending@b.co", WRONG_PASSWORD)
    on_missing = _login(client, "nobody@b.co", WRONG_PASSWORD)

    assert on_pending.status_code == 401
    assert _same_response(on_pending, on_missing), (
        "틀린 비밀번호 응답이 계정 상태에 따라 달라지면 그게 계정 열거 오라클이다")


def test_틀린_비밀번호_응답은_상태와_무관하게_전부_같다(client):
    """pending · approved · rejected · 없음 — 네 경우가 모두 같은 401 이어야 한다."""
    _register(client, "pending@b.co")
    _register(client, "approved@b.co")
    _approve(client, "approved@b.co")
    _register(client, "rejected@b.co")
    client.repo.set_user_status(client.repo.get_user_by_email("rejected@b.co").id,
                                base.STATUS_REJECTED, actor="cli")

    responses = [_login(client, e, WRONG_PASSWORD) for e in
                 ("pending@b.co", "approved@b.co", "rejected@b.co", "nobody@b.co")]

    assert all(r.status_code == 401 for r in responses)
    first = responses[0]
    assert all(_same_response(first, r) for r in responses[1:])


def test_상태는_비밀번호가_맞아야만_드러난다(client):
    """403(상태 노출)에 도달하는 유일한 길이 '비밀번호를 안다'여야 한다.

    이 성질이 있으면 상태를 알아낸 사람은 이미 그 계정으로 로그인할 수 있는 사람이므로,
    403 이 알려주는 정보에 추가 가치가 없다 — 열거 오라클이 아니다.
    """
    _register(client, "a@b.co")

    assert _login(client, "a@b.co", WRONG_PASSWORD).status_code == 401   # 모른다 → 아무것도 안 알려줌
    assert _login(client, "a@b.co", PASSWORD).status_code == 403         # 안다 → 상태 안내


def test_없는_계정에도_같은_비용의_비밀번호_검증이_돈다(client, monkeypatch):
    """타이밍 오라클 차단.

    응답 본문이 같아도 **없는 계정만 argon2 를 건너뛰면** 수십 ms 차이가 그대로
    "가입 여부"를 알려준다. 벽시계 시간은 CI 에서 흔들리므로, 검증이 **실제로
    호출됐는지**를 구조로 못박는다.
    """
    import app.api.routes as routes

    calls: list[str] = []
    real = routes.verify_password

    def counting(password: str, hashed: str) -> bool:
        calls.append(hashed)
        return real(password, hashed)

    monkeypatch.setattr(routes, "verify_password", counting)

    _register(client, "exists@b.co")
    _approve(client, "exists@b.co")

    assert _login(client, "exists@b.co", WRONG_PASSWORD).status_code == 401
    assert _login(client, "nobody@b.co", WRONG_PASSWORD).status_code == 401

    assert len(calls) == 2, "없는 계정에서 해시 검증을 건너뛰면 응답 시간이 가입 여부를 알려준다"
    assert calls[0] != calls[1]
    assert all(h.startswith("$argon2") for h in calls), (
        "버림용 해시가 진짜 argon2 해시가 아니면 비용이 같지 않다")


def test_버림용_해시에는_어떤_비밀번호도_맞지_않는다():
    from app.core.security import dummy_password_hash, verify_password

    h = dummy_password_hash()
    assert not verify_password(PASSWORD, h)
    assert not verify_password("", h)
    # 프로세스 안에서는 같은 값을 재사용한다(매 로그인마다 새로 해시하면 두 배로 느려진다).
    assert dummy_password_hash() is h


# ---------------------------------------------------------------------------
# 3. 승인 회수가 실제로 회수된다 (토큰이 살아 있는 동안에도)
# ---------------------------------------------------------------------------

def test_거부되면_이미_발급된_access토큰이_즉시_막힌다(client):
    """서버측 토큰 폐기가 없으므로(SR15-3) **매 요청 상태 재확인**이 유일한 회수 수단이다."""
    _register(client, "a@b.co")
    uid = _approve(client, "a@b.co")
    token = _token(client, "a@b.co")
    assert client.get("/api/v1/me/preferences", headers=_auth(token)).status_code == 200

    client.repo.set_user_status(uid, base.STATUS_REJECTED, actor="cli")

    r = client.get("/api/v1/me/preferences", headers=_auth(token))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "ACCOUNT_REJECTED"


def test_거부되면_refresh도_거절되고_쿠키가_지워진다(https_client):
    _register(https_client, "a@b.co")
    uid = _approve(https_client, "a@b.co")
    assert _login(https_client, "a@b.co").status_code == 200
    assert https_client.cookies.get(REFRESH_COOKIE)

    https_client.repo.set_user_status(uid, base.STATUS_REJECTED, actor="cli")

    r = https_client.post("/api/v1/auth/refresh", headers=AJAX)
    assert r.status_code == 401
    assert "max-age=0" in r.headers["set-cookie"].lower()
    assert https_client.cookies.get(REFRESH_COOKIE) is None


# ---------------------------------------------------------------------------
# 4. 관리자 엔드포인트 — 존재 자체를 숨긴다
# ---------------------------------------------------------------------------

def test_비관리자에게_관리자경로는_없는_경로와_구분되지_않는다(client):
    _register(client, "user@b.co")
    _approve(client, "user@b.co")
    token = _token(client, "user@b.co")
    unknown = client.get(UNKNOWN_PATH)

    cases = {
        "토큰 없음": client.get("/api/v1/admin/users"),
        "일반 사용자": client.get("/api/v1/admin/users", headers=_auth(token)),
        "깨진 토큰": client.get("/api/v1/admin/users", headers=_auth("not-a-jwt")),
        "승인 처리 시도": client.post("/api/v1/admin/users/1/approve", headers=_auth(token)),
    }

    assert unknown.status_code == 404
    for label, r in cases.items():
        assert _same_response(r, unknown), f"{label}: 응답이 달라 관리자 경로의 존재가 드러난다 — {r.text}"


def test_메서드가_달라도_405가_아니라_404다(client):
    """`PUT /admin/users` → 405 면 "여기 라우트가 있다"를 알려주는 것과 같다."""
    unknown = client.put(UNKNOWN_PATH)

    for r in (client.put("/api/v1/admin/users"),
              client.delete("/api/v1/admin/users"),
              client.get("/api/v1/admin/users/1/approve"),
              client.get("/api/v1/admin/anything/else")):
        assert _same_response(r, unknown), f"메서드/경로 탐색으로 존재가 드러난다 — {r.status_code}"


def test_잘못된_사용자id로_탐색해도_422가_새지_않는다(client):
    """검증 오류(422)는 "여기 라우트가 있고 파라미터를 파싱했다"는 신호다.

    관리자 관문이 **경로 파라미터 검증보다 먼저** 돌아야 이 신호가 안 샌다.
    """
    _register(client, "user@b.co")
    _approve(client, "user@b.co")
    token = _token(client, "user@b.co")

    for path in ("/api/v1/admin/users/abc/approve", "/api/v1/admin/users/-1/reject"):
        assert _same_response(client.post(path, json={}, headers=_auth(token)),
                              client.post(UNKNOWN_PATH, json={}))


def test_승인되지_않은_관리자는_관리자가_아니다(client):
    """거부된 계정에 남아 있던 is_admin 이 되살아나는 경로를 막는다."""
    _register(client, "admin@b.co")
    uid = _make_admin(client, "admin@b.co")
    token = _token(client, "admin@b.co")
    assert client.get("/api/v1/admin/users", headers=_auth(token)).status_code == 200

    # 다른 관리자를 세워 두고(마지막 관리자 보호에 걸리지 않게) 이 계정을 거부한다.
    _register(client, "admin2@b.co")
    _make_admin(client, "admin2@b.co")
    client.repo.set_user_status(uid, base.STATUS_REJECTED, actor="cli")

    assert _same_response(client.get("/api/v1/admin/users", headers=_auth(token)),
                          client.get(UNKNOWN_PATH))


def test_강등되면_기존_토큰으로도_관리자API를_잃는다(client):
    """권한의 진실 소스가 **토큰이 아니라 DB** 임을 못박는다."""
    _register(client, "admin@b.co")
    admin_id = _make_admin(client, "admin@b.co")
    _register(client, "admin2@b.co")
    _make_admin(client, "admin2@b.co")
    token = _token(client, "admin@b.co")
    assert client.get("/api/v1/admin/users", headers=_auth(token)).status_code == 200

    client.repo.set_user_admin(admin_id, False, actor="cli")

    assert _same_response(client.get("/api/v1/admin/users", headers=_auth(token)),
                          client.get(UNKNOWN_PATH))


def _forge(user_id: int, **claims) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {"sub": str(user_id), "typ": "access",
               "iat": int(now.timestamp()),
               "exp": int((now + dt.timedelta(minutes=30)).timestamp()), **claims}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def test_토큰이_관리자라고_주장해도_통하지_않는다(client):
    """서명이 유효한 토큰에 admin 클레임을 실어도 소용없어야 한다.

    (서명 키가 새는 상황이 아니라도, admin 을 토큰에 담는 설계 자체가 **강등이
    반영되지 않는** 창을 만든다. 그래서 넣지 않는다.)
    """
    _register(client, "user@b.co")
    uid = _approve(client, "user@b.co")

    forged = _forge(uid, admin=True, is_admin=True, role="admin",
                    status=base.STATUS_APPROVED)

    assert _same_response(client.get("/api/v1/admin/users", headers=_auth(forged)),
                          client.get(UNKNOWN_PATH))


def test_발급되는_access토큰에_권한_클레임이_없다(client):
    _register(client, "admin@b.co")
    _make_admin(client, "admin@b.co")

    payload = jwt.decode(_token(client, "admin@b.co"), JWT_SECRET, algorithms=["HS256"])

    assert set(payload) == {"sub", "typ", "iat", "exp", "jti"}, (
        "권한·상태를 토큰에 실으면 클라이언트의 주장이 되고, 강등이 반영되지 않는다")


# ---------------------------------------------------------------------------
# 5. 관리자 기능
# ---------------------------------------------------------------------------

@pytest.fixture()
def admin_client(client):
    """관리자 1명 + 대기자 1명이 있는 상태."""
    _register(client, "admin@b.co")
    client.admin_id = _make_admin(client, "admin@b.co")
    client.admin_token = _token(client, "admin@b.co")
    client.waiting_id = _register(client, "waiting@b.co")
    return client


def test_관리자는_대기목록을_조회한다(admin_client):
    r = admin_client.get("/api/v1/admin/users?status=pending",
                         headers=_auth(admin_client.admin_token))

    assert r.status_code == 200, r.text
    body = r.json()
    assert [u["email"] for u in body["items"]] == ["waiting@b.co"]
    assert body["active_admins"] == 1


def test_대기목록은_비밀번호_해시를_노출하지_않는다(admin_client):
    r = admin_client.get("/api/v1/admin/users", headers=_auth(admin_client.admin_token))

    assert r.status_code == 200
    assert "password" not in r.text.lower()
    assert "argon2" not in r.text.lower()
    assert "$" not in r.text, "해시 조각이라도 나가면 오프라인 크래킹 재료다"


def test_승인하면_그_사용자가_로그인할_수_있다(admin_client):
    r = admin_client.post(f"/api/v1/admin/users/{admin_client.waiting_id}/approve",
                          headers=_auth(admin_client.admin_token))

    assert r.status_code == 200, r.text
    assert r.json()["status"] == base.STATUS_APPROVED
    assert _login(admin_client, "waiting@b.co").status_code == 200


def test_승인은_누가_언제_했는지_남는다(admin_client):
    admin_client.post(f"/api/v1/admin/users/{admin_client.waiting_id}/approve",
                      headers=_auth(admin_client.admin_token))

    user = admin_client.repo.get_user_by_email("waiting@b.co")
    assert user.status_changed_by == admin_client.admin_id
    assert user.status_changed_at is not None

    events = admin_client.repo.status_events(admin_client.waiting_id)
    assert [e["event"] for e in events] == ["registered", base.STATUS_APPROVED]
    assert events[-1]["actor"] == "admin_api"
    assert events[-1]["actor_user_id"] == admin_client.admin_id


def test_거부는_사유를_감사기록에_남긴다(admin_client):
    r = admin_client.post(f"/api/v1/admin/users/{admin_client.waiting_id}/reject",
                          json={"reason": "본인 확인 불가"},
                          headers=_auth(admin_client.admin_token))

    assert r.status_code == 200, r.text
    assert r.json()["status"] == base.STATUS_REJECTED
    assert admin_client.repo.get_user_by_email("waiting@b.co").status_reason == "본인 확인 불가"
    assert _login(admin_client, "waiting@b.co").status_code == 403


def test_없는_사용자를_승인해도_존재를_알려주지_않는다(admin_client):
    r = admin_client.post("/api/v1/admin/users/999999/approve",
                          headers=_auth(admin_client.admin_token))

    assert _same_response(r, admin_client.get(UNKNOWN_PATH))


def test_마지막_관리자는_자기를_거부할_수_없다(admin_client):
    r = admin_client.post(f"/api/v1/admin/users/{admin_client.admin_id}/reject",
                          json={}, headers=_auth(admin_client.admin_token))

    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "LAST_ADMIN"
    # 상태가 실제로 그대로여야 한다(응답만 막고 DB 는 바뀌는 일이 없게).
    assert admin_client.repo.get_user_by_email("admin@b.co").status == base.STATUS_APPROVED
    assert admin_client.repo.count_active_admins() == 1


def test_관리자가_둘이면_한_명은_물러날_수_있다(admin_client):
    _register(admin_client, "admin2@b.co")
    second = _make_admin(admin_client, "admin2@b.co")

    r = admin_client.post(f"/api/v1/admin/users/{admin_client.admin_id}/reject",
                          json={}, headers=_auth(admin_client.admin_token))

    assert r.status_code == 200, r.text
    assert admin_client.repo.count_active_admins() == 1
    assert admin_client.repo.get_user(second).can_administer


def test_승인_취소도_마지막_관리자_보호를_받는다(client):
    """`set_user_status` 로 관리자를 pending 으로 되돌려도 관리자 0명이 되면 안 된다."""
    _register(client, "admin@b.co")
    uid = _make_admin(client, "admin@b.co")

    with pytest.raises(base.LastAdminError):
        client.repo.set_user_status(uid, base.STATUS_PENDING, actor="cli")
    with pytest.raises(base.LastAdminError):
        client.repo.set_user_admin(uid, False, actor="cli")

    assert client.repo.count_active_admins() == 1


# ---------------------------------------------------------------------------
# 6. 리포지토리 계약 — 두 구현이 같은 Protocol 을 만족한다
# ---------------------------------------------------------------------------

def test_두_리포지토리_구현이_UserAdminRepository를_만족한다():
    """PostGIS 구현에 메서드가 없으면 운영에서 처음 알게 된다(인메모리로만 테스트하므로)."""
    from app.repositories.postgis import PostgisRepository

    assert isinstance(InMemoryRepository(), base.UserAdminRepository)
    assert isinstance(PostgisRepository(engine=None), base.UserAdminRepository)


# ---------------------------------------------------------------------------
# 7. 부트스트랩 CLI — 첫 관리자는 서버에서만 만들어진다
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cli():
    """`scripts/manage_users.py` 를 모듈로 불러온다(서버 실행과 같은 코드)."""
    import importlib.util
    import sys

    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "_test_manage_users", scripts_dir / "manage_users.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_cli(cli, repo, argv: list[str]) -> int:
    return cli.run(repo, cli.build_parser().parse_args(argv))


@pytest.fixture()
def repo_with_waiting():
    repo = InMemoryRepository()
    repo.create_user("waiting@b.co", "hash-not-a-password")
    return repo


def test_CLI_목록은_아무것도_바꾸지_않는다(cli, repo_with_waiting, capsys):
    """조회가 승격을 겸하면(예: "첫 가입자를 관리자로") 공개 사이트에서 선점당한다."""
    assert _run_cli(cli, repo_with_waiting, ["--list"]) == 0

    out = capsys.readouterr().out
    assert "waiting@b.co" in out
    assert repo_with_waiting.get_user_by_email("waiting@b.co").status == base.STATUS_PENDING
    assert repo_with_waiting.count_active_admins() == 0


def test_CLI_부트스트랩_순서_승인후_관리자부여(cli, repo_with_waiting, capsys):
    assert _run_cli(cli, repo_with_waiting, ["--approve", "waiting@b.co"]) == 0
    assert _run_cli(cli, repo_with_waiting, ["--grant-admin", "waiting@b.co"]) == 0

    user = repo_with_waiting.get_user_by_email("waiting@b.co")
    assert user.can_administer
    assert repo_with_waiting.count_active_admins() == 1
    # CLI 로 한 변경임이 이력에 남는다(관리자 API 와 구분된다).
    events = repo_with_waiting.status_events(user.id)
    assert [e["event"] for e in events] == ["registered", "approved", "admin_granted"]
    assert {e["actor"] for e in events[1:]} == {"cli"}


def test_CLI는_승인되지_않은_계정에_관리자를_주지_않는다(cli, repo_with_waiting, capsys):
    """'관리자 부여'가 승인 절차를 건너뛰는 뒷문이 되면 안 된다."""
    rc = _run_cli(cli, repo_with_waiting, ["--grant-admin", "waiting@b.co"])

    assert rc == 1
    assert "--approve" in capsys.readouterr().out
    assert repo_with_waiting.get_user_by_email("waiting@b.co").is_admin is False


def test_CLI는_없는_계정에_성공을_반환하지_않는다(cli, repo_with_waiting, capsys):
    """오타를 '승인했다'로 착각하면 대기자는 영원히 기다린다."""
    rc = _run_cli(cli, repo_with_waiting, ["--approve", "typo@b.co"])

    assert rc == 1
    assert "FAIL" in capsys.readouterr().out


def test_CLI는_마지막_관리자를_해제하지_않는다(cli, repo_with_waiting, capsys):
    _run_cli(cli, repo_with_waiting, ["--approve", "waiting@b.co"])
    _run_cli(cli, repo_with_waiting, ["--grant-admin", "waiting@b.co"])
    capsys.readouterr()

    assert _run_cli(cli, repo_with_waiting, ["--revoke-admin", "waiting@b.co"]) == 1
    assert _run_cli(cli, repo_with_waiting, ["--reject", "waiting@b.co"]) == 1

    assert "FAIL" in capsys.readouterr().out
    assert repo_with_waiting.count_active_admins() == 1


def test_CLI는_비밀번호를_다루지_않는다(cli):
    """운영자가 남의 비밀번호를 알게 되는 경로를 만들지 않는다(승인만 한다)."""
    source = Path(cli.__file__).read_text(encoding="utf-8")

    for banned in ("hash_password", "--password", "create_user", "getpass"):
        assert banned not in source, f"CLI 가 비밀번호/계정 생성에 손대고 있다: {banned}"


def test_CLI는_공통_진입경로를_탄다(cli):
    """`_common` 을 거쳐야 로깅 억제·비밀 마스킹이 걸린다(SR17-3)."""
    source = Path(cli.__file__).read_text(encoding="utf-8")
    assert "from _common import" in source
    assert "basicConfig" not in source


def test_리포지토리는_승인상태를_인자로_받지_않는다():
    """`create_user(..., status='approved')` 같은 지름길이 생기면 승인제가 무력화된다."""
    import inspect

    from app.repositories.postgis import PostgisRepository

    for impl in (InMemoryRepository, PostgisRepository):
        params = set(inspect.signature(impl.create_user).parameters)
        assert params == {"self", "email", "password_hash"}, (
            f"{impl.__name__}.create_user 가 상태를 받는다 — 가입 경로로 승인이 새어 나간다")
