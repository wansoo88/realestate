"""보안 코어 테스트 — security-review 게이트(G3)의 실증.

여기서 실패하면 개인 금융정보가 새는 것이므로, 다른 어떤 테스트보다 우선한다.
"""
from __future__ import annotations

import datetime as dt
import threading
import time

import argon2
import jwt
import pytest

from app.core.security import (
    OWASP_MIN_MEMORY_KIB,
    OWASP_MIN_PARALLELISM,
    OWASP_MIN_TIME_COST,
    DecryptionError,
    HashCapacityError,
    argon2_parameter_problems,
    decode_token,
    decrypt_amount,
    encrypt_amount,
    generate_key,
    get_hasher,
    hash_password,
    load_key,
    mask_sensitive,
    verify_password,
)

SECRET = "test-secret-do-not-use-in-production"


@pytest.fixture()
def key():
    return generate_key()


# ---------------------------------------------------------------------------
# 필드 암호화
# ---------------------------------------------------------------------------

def test_암복호화_왕복(key):
    blob = encrypt_amount(300_000_000, user_id=7, field="cash_krw", key=key)
    assert decrypt_amount(blob, user_id=7, field="cash_krw", key=key) == 300_000_000


def test_암호문에_평문이_보이지_않는다(key):
    blob = encrypt_amount(300_000_000, user_id=7, field="cash_krw", key=key)
    assert b"300000000" not in blob
    assert b"3" * 3 not in blob[:4]


def test_같은_값도_매번_다른_암호문(key):
    """nonce 가 매번 달라야 한다. 같으면 값이 같다는 사실이 새어나간다."""
    a = encrypt_amount(300_000_000, user_id=7, field="cash_krw", key=key)
    b = encrypt_amount(300_000_000, user_id=7, field="cash_krw", key=key)
    assert a != b


def test_다른_사용자로는_복호화되지_않는다(key):
    """AAD 바인딩 — A 의 암호문을 B 행에 복사해도 못 읽는다."""
    blob = encrypt_amount(300_000_000, user_id=7, field="cash_krw", key=key)
    with pytest.raises(DecryptionError):
        decrypt_amount(blob, user_id=8, field="cash_krw", key=key)


def test_다른_필드로는_복호화되지_않는다(key):
    """연소득 암호문을 보유현금 칸으로 옮기는 것도 막는다."""
    blob = encrypt_amount(90_000_000, user_id=7, field="income_krw", key=key)
    with pytest.raises(DecryptionError):
        decrypt_amount(blob, user_id=7, field="cash_krw", key=key)


def test_다른_키로는_복호화되지_않는다(key):
    blob = encrypt_amount(300_000_000, user_id=7, field="cash_krw", key=key)
    with pytest.raises(DecryptionError):
        decrypt_amount(blob, user_id=7, field="cash_krw", key=generate_key())


def test_변조된_암호문은_거부된다(key):
    blob = bytearray(encrypt_amount(300_000_000, user_id=7, field="cash_krw", key=key))
    blob[-1] ^= 0xFF
    with pytest.raises(DecryptionError):
        decrypt_amount(bytes(blob), user_id=7, field="cash_krw", key=key)


def test_없는_값은_None(key):
    assert decrypt_amount(None, user_id=7, field="cash_krw", key=key) is None


def test_짧은_키는_시작부터_막는다():
    with pytest.raises(ValueError, match="32바이트"):
        load_key("too-short")


def test_정상_키는_통과():
    assert len(load_key("0" * 32)) == 32


# ---------------------------------------------------------------------------
# 비밀번호
# ---------------------------------------------------------------------------

def test_비밀번호_해시_검증():
    h = hash_password("correct horse battery")
    assert h != "correct horse battery"
    assert verify_password("correct horse battery", h)
    assert not verify_password("wrong password!!", h)


def test_argon2id_사용():
    assert hash_password("correct horse battery").startswith("$argon2id$")


def test_짧은_비밀번호는_거부():
    with pytest.raises(ValueError):
        hash_password("short")


def test_잘못된_해시로_검증하면_False():
    assert not verify_password("anything", "not-a-hash")


# ---------------------------------------------------------------------------
# Argon2 파라미터 · 동시성 (SR8-1)
#   64MiB × 동시 5건 = 320MiB 로 동거 실서비스를 OOM 위협하던 문제.
#   **보안을 낮춘 게 아니라** OWASP 하한으로 맞추고 동시성을 제한했다.
# ---------------------------------------------------------------------------

def test_해시_파라미터가_OWASP_하한을_만족한다():
    """기본 64MiB·t3·p4 → 19MiB·t2·p1. 하한 밑으로는 내려가지 않는다."""
    h = get_hasher()
    assert h.memory_cost >= OWASP_MIN_MEMORY_KIB
    assert h.time_cost >= OWASP_MIN_TIME_COST
    assert h.parallelism >= OWASP_MIN_PARALLELISM
    assert h.type == argon2.low_level.Type.ID

    # argon2-cffi 기본값(64MiB)을 그대로 쓰고 있지 않다는 것 자체가 이 수정의 핵심
    assert h.memory_cost < 65536, "기본값 64MiB 로 돌아갔습니다 (SR8-1 회귀)"


def test_해시_문자열에_파라미터가_기록된다():
    """검증이 설정이 아니라 **해시에 적힌 값**을 쓴다는 근거."""
    params = argon2.extract_parameters(hash_password("correct horse battery"))
    assert params.memory_cost == get_hasher().memory_cost
    assert params.time_cost == get_hasher().time_cost
    assert params.parallelism == get_hasher().parallelism


def test_다른_파라미터로_만든_기존_해시도_검증된다():
    """파라미터를 바꿔도 **재해시·마이그레이션이 필요 없다**.

    운영 DB 에 이미 64MiB 로 저장된 해시가 있어도 로그인이 깨지지 않는다.
    (여기서는 64MiB 를 실제로 할당하지 않으려고 다른 값으로 검증한다 —
     검증하는 성질은 '설정과 다른 파라미터'라는 점이라 값 자체는 무관하다.)
    """
    legacy = argon2.PasswordHasher(memory_cost=16384, time_cost=1, parallelism=2)
    old_hash = legacy.hash("correct horse battery")

    p = argon2.extract_parameters(old_hash)
    assert (p.memory_cost, p.time_cost, p.parallelism) != (
        get_hasher().memory_cost, get_hasher().time_cost, get_hasher().parallelism)

    assert verify_password("correct horse battery", old_hash)
    assert not verify_password("wrong password!!", old_hash)


def test_64MiB_해시_문자열도_파라미터가_읽힌다():
    """실제 운영에 남아 있을 옛 해시 형식(64MiB·t3·p4) 파싱 확인.

    문자열 파싱만 한다 — 검증까지 하면 이 테스트가 64MiB 를 잡아
    지금 고치려는 그 문제를 테스트가 스스로 일으킨다.
    """
    legacy = ("$argon2id$v=19$m=65536,t=3,p=4$"
              "c29tZXNhbHRzb21lc2FsdA$RdescudvJCsgt3ub+b+dWRWJTmaaJObG")
    p = argon2.extract_parameters(legacy)
    assert (p.memory_cost, p.time_cost, p.parallelism) == (65536, 3, 4)


@pytest.mark.parametrize("field, value, expect", [
    ("argon2_memory_kib", OWASP_MIN_MEMORY_KIB - 1, "OWASP 하한"),
    ("argon2_time_cost", OWASP_MIN_TIME_COST - 1, "OWASP 하한"),
    ("argon2_parallelism", 0, "이상이어야"),
    ("argon2_concurrency", 0, "1 이상이어야"),
])
def test_하한_미만_설정은_기동_점검에서_걸린다(field, value, expect):
    """메모리가 부족하다고 파라미터를 깎는 '해결'을 막는다."""
    from app.core.config import Settings

    s = Settings(jwt_secret="x" * 40, field_encryption_key="k" * 32,
                 postgres_password="pw", **{field: value})
    problems = argon2_parameter_problems(s)
    assert any(expect in p for p in problems), problems
    # validate_runtime 에도 그대로 올라온다
    assert any(expect in p for p in s.validate_runtime())


def test_하한_미만이면_해셔를_만들_수_없다():
    """기동 점검을 건너뛰어도 해시 경로에서 막힌다."""
    from app.core.security import _build_hasher

    with pytest.raises(ValueError, match="OWASP 하한"):
        _build_hasher(8192, 2, 1)


def test_동시_해시가_설정값을_넘지_않는다(monkeypatch):
    """스레드풀 40개가 전부 해시에 들어가 760MiB 를 잡는 걸 막는다."""
    from app.core.config import get_settings

    monkeypatch.setenv("ARGON2_CONCURRENCY", "2")
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "k" * 32)
    get_settings.cache_clear()
    try:
        inside = 0
        peak = 0
        lock = threading.Lock()
        start = threading.Event()

        def work():
            nonlocal inside, peak
            start.wait()
            from app.core.security import _Slot, _current
            _, gate, timeout = _current()
            with _Slot(gate, timeout):
                with lock:
                    inside += 1
                    peak = max(peak, inside)
                time.sleep(0.05)
                with lock:
                    inside -= 1

        threads = [threading.Thread(target=work) for _ in range(8)]
        for t in threads:
            t.start()
        start.set()
        for t in threads:
            t.join()

        assert peak <= 2, f"동시 {peak}건이 해시에 들어갔습니다(한도 2)"
    finally:
        get_settings.cache_clear()


def test_슬롯을_못_얻으면_HashCapacityError(monkeypatch):
    """무한정 기다리다 스레드풀이 다 막히는 대신 인증만 거절한다."""
    from app.core.config import get_settings

    monkeypatch.setenv("ARGON2_CONCURRENCY", "1")
    monkeypatch.setenv("ARGON2_WAIT_TIMEOUT_SEC", "0.05")
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "k" * 32)
    get_settings.cache_clear()
    try:
        from app.core.security import _Slot, _current

        _, gate, timeout = _current()
        with _Slot(gate, timeout):                 # 하나뿐인 슬롯을 점유
            with pytest.raises(HashCapacityError):
                with _Slot(gate, timeout):
                    pass
        # 빠져나온 뒤에는 다시 얻을 수 있다(슬롯 누수 없음)
        with _Slot(gate, timeout):
            pass
    finally:
        get_settings.cache_clear()


def test_해시_반복_실행에_실패가_없다():
    """SR8-1 의 원 증상(HashingError)이 재발하지 않는지 반복 근거.

    64MiB 였다면 이 반복이 훨씬 무겁고, 실제로 8회 중 1회 실패가 관측됐다.
    """
    for _ in range(20):
        h = hash_password("correct horse battery staple")
        assert verify_password("correct horse battery staple", h)


# ---------------------------------------------------------------------------
# argon2 자원 부족 → 503 (SR8-2)
#   SR8-1 로 세마포어 거절은 503 이 됐지만, argon2 가 **실제로 메모리를 못 잡아**
#   HashingError 를 던지는 경우는 여전히 500 이었다.
#   500 은 "서버 버그, 재시도 말라"는 뜻이라 자원 부족에 붙이면 틀리다.
# ---------------------------------------------------------------------------

class _FailingHasher:
    """argon2 가 메모리 확보에 실패하는 상황을 흉내 낸다.

    실제 argon2 와 같은 예외를 던진다 — `hash()` 는 `HashingError`,
    `verify()` 는 `VerificationError`. (둘을 뒤섞으면 테스트가 현실과 달라져
    통과해도 아무것도 보장하지 못한다.)

    `PasswordHasher` 는 속성이 read-only 라 인스턴스를 갈아끼우는 대신
    `_current()` 를 통째로 대체한다.
    """

    memory_cost, time_cost, parallelism = 19456, 2, 1

    def __init__(self, hash_exc: Exception | None = None,
                 verify_exc: Exception | None = None) -> None:
        self._hash_exc = hash_exc or argon2.exceptions.HashingError("no memory")
        self._verify_exc = verify_exc or argon2.exceptions.VerificationError("no memory")

    def hash(self, password: str) -> str:
        raise self._hash_exc

    def verify(self, hashed: str, password: str) -> bool:
        raise self._verify_exc


def _patch_hasher(monkeypatch, *, hash_exc=None, verify_exc=None) -> None:
    import threading as _t

    from app.core import security as sec

    gate = _t.BoundedSemaphore(4)
    hasher = _FailingHasher(hash_exc, verify_exc)
    monkeypatch.setattr(sec, "_current", lambda: (hasher, gate, 1.0))


def test_해시_메모리부족은_HashCapacityError(monkeypatch):
    """500(버그) 이 아니라 재시도 가능한 자원 부족으로 다룬다."""
    _patch_hasher(monkeypatch)
    with pytest.raises(HashCapacityError):
        hash_password("correct horse battery staple")


def test_검증_메모리부족은_False가_아니라_예외(monkeypatch):
    """확인을 못 한 걸 '비밀번호 틀림'으로 돌려주면 사용자에게 거짓말이 된다."""
    _patch_hasher(monkeypatch)
    with pytest.raises(HashCapacityError):
        verify_password("correct horse battery staple", "$argon2id$dummy")


def test_비밀번호_불일치는_그대로_False(monkeypatch):
    """VerifyMismatchError 는 Argon2Error 의 하위 타입이라 잡는 순서가 중요하다.

    순서가 뒤바뀌면 **틀린 비밀번호가 503** 이 되고, 정상 로그인(200)과 구분되는
    그 차이가 계정 존재 여부를 알려주는 통로가 된다.
    """
    _patch_hasher(monkeypatch,
                  verify_exc=argon2.exceptions.VerifyMismatchError("mismatch"))
    assert verify_password("wrong password!!", "$argon2id$dummy") is False


def test_깨진_해시는_재시도_대상이_아니다(monkeypatch):
    """저장된 해시가 손상된 경우는 몇 번 다시 해도 같다 — 503 이 아니라 로그인 실패."""
    _patch_hasher(monkeypatch, verify_exc=argon2.exceptions.InvalidHashError("broken"))
    assert verify_password("correct horse battery staple", "garbage") is False


def test_API가_500이_아니라_503을_돌려준다(monkeypatch):
    """SR8-2 회귀 방지의 핵심 — 실제 응답 코드로 확인한다.

    가입(hash)·로그인(verify) 두 경로를 모두 태운다. `Retry-After` 가 있어야
    클라이언트가 '재시도해도 되는 상황'임을 안다.
    """
    from fastapi.testclient import TestClient

    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "k" * 32)
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")

    from app.core.config import get_settings
    get_settings.cache_clear()
    try:
        from app.main import create_app
        from app.repositories.memory import InMemoryRepository

        email, password = "sr82@example.com", "correct horse battery"
        repo = InMemoryRepository()
        with TestClient(create_app(repo=repo), raise_server_exceptions=False) as client:
            # 해셔를 망가뜨리기 전에 계정을 만들어 둔다. 없는 계정으로 로그인하면
            # 라우터가 verify_password 를 부르기도 전에 401 로 끝나 검증이 안 된다.
            body = {"email": email, "password": password}
            assert client.post("/api/v1/auth/register", json=body).status_code == 201

            _patch_hasher(monkeypatch)      # 이후 hash·verify 둘 다 자원 부족

            cases = [
                ("/api/v1/auth/register", {"email": "new@example.com",
                                           "password": password}),   # hash 경로
                ("/api/v1/auth/login", body),                         # verify 경로
            ]
            for path, payload in cases:
                r = client.post(path, json=payload)
                assert r.status_code == 503, \
                    f"{path} → {r.status_code} (500 이면 SR8-2 회귀)"
                assert r.json()["error"]["code"] == "BUSY"
                assert r.headers.get("Retry-After") == "1"
                # 자원 문제 응답에 비밀번호·계정 단서를 싣지 않는다
                assert password not in r.text
                assert email not in r.text
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def test_토큰_왕복():
    from app.core.security import create_token
    token = create_token(42, secret=SECRET)
    assert decode_token(token, secret=SECRET) == 42


def test_refresh_토큰으로_API를_못_쓴다():
    """토큰 종류를 구분하지 않으면 수명이 긴 refresh 로 API 를 계속 호출할 수 있다."""
    from app.core.security import create_token
    refresh = create_token(42, secret=SECRET, kind="refresh")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(refresh, secret=SECRET, expect="access")


def test_만료된_토큰은_거부():
    from app.core.security import create_token
    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)
    token = create_token(42, secret=SECRET, now=past)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(token, secret=SECRET)


def test_다른_비밀키로_서명된_토큰은_거부():
    from app.core.security import create_token
    token = create_token(42, secret="attacker-secret-attacker-secret!")
    with pytest.raises(jwt.InvalidSignatureError):
        decode_token(token, secret=SECRET)


def test_알고리즘_none_공격_차단():
    """alg=none 토큰을 받아주면 누구나 아무 사용자로 로그인된다."""
    forged = jwt.encode({"sub": "1", "typ": "access"}, key="", algorithm="none")
    with pytest.raises(jwt.PyJWTError):
        decode_token(forged, secret=SECRET)


def test_access_토큰을_refresh_자리에_쓸_수_없다():
    """반대 방향도 막는다 — access 를 refresh 쿠키에 심어 갱신 루프를 돌리지 못하게."""
    from app.core.security import create_token
    access = create_token(42, secret=SECRET, kind="access")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(access, secret=SECRET, expect="refresh")


def test_같은_초에_발급해도_토큰이_다르다():
    """쿠키 회전이 실제 회전이 되려면 값이 달라져야 한다(jti)."""
    from app.core.security import create_token
    now = dt.datetime.now(dt.timezone.utc)
    a = create_token(42, secret=SECRET, kind="refresh", now=now)
    b = create_token(42, secret=SECRET, kind="refresh", now=now)
    assert a != b
    assert decode_token(a, secret=SECRET, expect="refresh") == 42


def test_refresh_수명은_7일이다():
    """SR15-1 — 서버측 폐기 수단이 생기기 전까지 노출 창을 줄여 둔다.

    이 값을 늘리려면 `jti` denylist(SR15-3)를 먼저 붙여야 한다.
    """
    from app.core.security import REFRESH_TTL, REFRESH_TTL_SECONDS
    assert REFRESH_TTL == dt.timedelta(days=7)
    assert REFRESH_TTL_SECONDS == 7 * 24 * 3600


# ---------------------------------------------------------------------------
# 기동 점검이 **실제로 돈다** (SR29-1)
#
# 이 절이 지키는 것은 계산이 아니라 **호출**이다. `validate_runtime()` 은 오랫동안
# 정확한 목록을 돌려줬고 아무도 부르지 않았다 — 그래서 `JWT_SECRET=""` 로도 앱이 뜨고
# 빈 문자열로 서명된 토큰이 발급·검증됐다(승인제 우회 = 임의 user_id 위조).
# 원장(SR-015)은 그동안 이 함수를 방어 근거로 인용했다. 함수만 있고 안 불리는 상태가
# 재발하지 않도록, 여기서는 **앱이 뜨는지 안 뜨는지**로 판정한다.
# ---------------------------------------------------------------------------

def _app_with_env(monkeypatch, **env):
    """주어진 환경으로 앱을 만든다. 설정 캐시는 반드시 비우고 들어간다."""
    from app.core.config import get_settings

    base = {"JWT_SECRET": "x" * 40, "FIELD_ENCRYPTION_KEY": "k" * 32,
            "POSTGRES_PASSWORD": "pw", "DEBUG": "false"}
    base.update(env)
    for name, value in base.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    try:
        from app.main import create_app
        from app.repositories.memory import InMemoryRepository
        return create_app(repo=InMemoryRepository())
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("env,expect", [
    ({"JWT_SECRET": ""}, "JWT_SECRET"),
    ({"JWT_SECRET": "short"}, "JWT_SECRET"),
    ({"JWT_SECRET": "x" * 31}, "JWT_SECRET"),          # 경계: 32자 미만
    ({"FIELD_ENCRYPTION_KEY": "k" * 31}, "FIELD_ENCRYPTION_KEY"),
    ({"ARGON2_MEMORY_KIB": "8192"}, "ARGON2_MEMORY_KIB"),
])
def test_치명적_설정이면_앱이_아예_뜨지_않는다(monkeypatch, env, expect):
    """★ 변이: `create_app` 에서 `enforce_runtime_settings` 호출을 지우거나 경고
    로그로 바꾸면 앱이 정상적으로 떠 버려 여기서 잡힌다.

    특히 `JWT_SECRET=""` 는 **아무 오류도 내지 않는다** — 토큰 발급·검증이 그대로
    성공한다. 그래서 '뜨지 않는 것'만이 관측 가능한 방어다.
    """
    from app.core.config import RuntimeConfigError

    with pytest.raises(RuntimeConfigError) as exc:
        _app_with_env(monkeypatch, **env)
    assert expect in str(exc.value)
    # 값은 어디에도 싣지 않는다 — 항목 이름만 나간다.
    assert "x" * 31 not in str(exc.value)
    assert "k" * 31 not in str(exc.value)


@pytest.mark.parametrize("key,byte_len", [
    ("가" * 32, 96),         # 32자인데 96바이트 — 예전 게이트를 그대로 통과했다
    ("x" * 31 + "가", 34),   # 32자인데 34바이트
    ("가" * 10, 30),         # 10자 30바이트 — 자 수로 재면 여기서 걸리고, 바이트로도 걸린다
])
def test_FEK_게이트는_문자가_아니라_바이트를_잰다(monkeypatch, key, byte_len):
    """★ SR30-1. **재는 것과 말하는 것을 일치시킨다.**

    예전에는 `len(str)`(문자 수)를 재면서 메시지는 "32바이트"라고 말했다. 그래서
    비ASCII 32자 키는 기동을 통과한 뒤 `security.load_key`(바이트를 잰다)에서 걸려
    **사용자가 자산을 저장하는 순간 503** 이 됐다 — 이 게이트가 막겠다고 내건
    바로 그 상황이다.

    변이: `self.field_encryption_key.encode()` 에서 `.encode()` 를 지우면 앞의 두
    케이스가 기동을 통과해 여기서 잡힌다.
    """
    from app.core.config import RuntimeConfigError

    assert len(key.encode()) == byte_len
    with pytest.raises(RuntimeConfigError) as exc:
        _app_with_env(monkeypatch, FIELD_ENCRYPTION_KEY=key)
    assert "FIELD_ENCRYPTION_KEY" in str(exc.value)
    # 길이는 말하되 **값은 말하지 않는다.**
    assert f"{byte_len}바이트" in str(exc.value)
    assert key not in str(exc.value)


def test_FEK_게이트와_사용지점이_같은_기준으로_판정한다(monkeypatch):
    """★ 두 방어선이 어긋나면 한쪽만 통과하는 값이 생긴다 — 그게 SR30-1 이었다.

    변이: 어느 한쪽의 측정 단위를 바꾸면 여기서 불일치가 드러난다.
    """
    from app.core.config import Settings
    from app.core.security import load_key

    for key in ("k" * 32, "가" * 32, "x" * 31 + "가", "k" * 31, "가" * 10):
        gate_ok = not any("FIELD_ENCRYPTION_KEY" in p for p in
                          Settings(jwt_secret="x" * 40, field_encryption_key=key,
                                   postgres_password="pw").fatal_runtime_problems())
        try:
            load_key(key)
            use_ok = True
        except ValueError:
            use_ok = False
        assert gate_ok == use_ok, f"기동 게이트와 load_key 의 판정이 다르다: {key!r}"


def test_기동을_막는_문제와_경고만_하는_문제를_구분한다(monkeypatch):
    """⚠️ 기동 차단은 **서비스를 죽이는 조치**다. 운영에서 효력조차 없는 설정으로
    앱을 못 뜨게 하면 안 된다.

    `COOKIE_SECURE=false` 는 운영에서 `refresh_cookie_secure` 가 구조적으로 True 로
    되돌리므로(위 테스트) 아무 효력이 없다 → 경고만. 반면 `JWT_SECRET` 은 잘못돼도
    앱이 **정상처럼 동작한다** → 차단.
    """
    app = _app_with_env(monkeypatch, COOKIE_SECURE="false")
    assert app is not None, "효력 없는 설정으로 서비스를 죽이지 않는다"

    from app.core.config import Settings

    weak = Settings(jwt_secret="", field_encryption_key="k" * 32, postgres_password="")
    fatal = weak.fatal_runtime_problems()
    assert any("JWT_SECRET" in p for p in fatal)
    # DB 비밀번호는 없으면 첫 접속에서 큰 소리로 죽는다(조용한 약화가 아니다) → 경고.
    assert any("POSTGRES_PASSWORD" in p for p in weak.validate_runtime())
    assert not any("POSTGRES_PASSWORD" in p for p in fatal)


def test_개발환경에서는_경고만_하고_뜬다(monkeypatch, caplog):
    """로컬에서 설정이 덜 채워졌다고 개발자가 앱을 못 띄우게 만들지는 않는다.
    대신 **조용히 넘어가지도 않는다** — 로그에 항목 이름이 남는다."""
    import logging

    with caplog.at_level(logging.WARNING, logger="app"):
        app = _app_with_env(monkeypatch, DEBUG="true", JWT_SECRET="short")
    assert app is not None
    assert any("JWT_SECRET" in r.message for r in caplog.records), caplog.text


def test_약한_서명키로는_토큰_발급_자체가_거부된다():
    """2차 방어 — `create_app()` 을 안 타는 경로(스크립트·배치)가 생겨도 막힌다.

    PyJWT 는 빈 키로도 **서명에 성공한다**(경고만 낸다). 그래서 라이브러리에 기대지 않고
    사용 지점에서 막는다. 메시지에 값은 담지 않는다.
    """
    from app.core.security import MIN_JWT_SECRET_CHARS, create_token

    for weak in ("", "short", "x" * (MIN_JWT_SECRET_CHARS - 1)):
        with pytest.raises(ValueError, match="서명키"):
            create_token(1, secret=weak)
        assert create_token(1, secret="y" * MIN_JWT_SECRET_CHARS)   # 경계는 통과


def test_서명키_하한은_바이트가_아니라_문자를_잰다():
    """이름과 측정이 어긋나지 않는지 못 박는다(이월 SR30-1 계열).

    UTF-8 에서 문자 수 ≤ 바이트 수라, **문자를 재는 쪽이 더 엄격하다**. 바이트로
    바꾸면 `'가'*11`(11자 · 33바이트)이 통과해 오히려 느슨해진다 — 이름을 바이트로
    되돌리거나 측정을 바이트로 바꾸면 여기서 깨진다.
    """
    from app.core import security
    from app.core.security import MIN_JWT_SECRET_CHARS, create_token

    assert not hasattr(security, "MIN_JWT_SECRET_BYTES"), (
        "이름을 되돌렸다 — 재는 것은 문자 수다")

    loose = "가" * 11                      # 11자 / 33바이트
    assert len(loose.encode()) >= MIN_JWT_SECRET_CHARS      # 바이트로는 통과할 값이고
    with pytest.raises(ValueError, match="서명키"):          # 문자로는 막힌다
        create_token(1, secret=loose)

    # 비ASCII 라도 문자 수만 채우면 통과한다(하한이지 정확한 길이가 아니다).
    assert create_token(1, secret="가" * MIN_JWT_SECRET_CHARS)


def test_정상_설정이면_기동_점검이_아무것도_남기지_않는다(monkeypatch, caplog):
    """오탐이 있으면 사람이 로그를 안 보게 된다."""
    import logging

    with caplog.at_level(logging.WARNING, logger="app"):
        assert _app_with_env(monkeypatch) is not None
    assert not [r for r in caplog.records if "기동 점검" in r.message], caplog.text


# ---------------------------------------------------------------------------
# refresh 쿠키 설정 (SR15-1)
# ---------------------------------------------------------------------------

def test_운영에서는_COOKIE_SECURE를_끌_수_없다():
    """설정 실수 하나로 refresh 가 평문 HTTP 로 흐르는 사고를 구조적으로 막는다."""
    from app.core.config import Settings

    prod = Settings(jwt_secret="x" * 40, field_encryption_key="k" * 32,
                    postgres_password="pw", debug=False, cookie_secure=False)
    assert prod.refresh_cookie_secure is True
    assert any("COOKIE_SECURE" in p for p in prod.validate_runtime())


def test_개발모드에서만_Secure를_끌_수_있다():
    """http://localhost 개발에서 쿠키가 아예 저장되지 않아 로그인이 막히는 것을 푼다."""
    from app.core.config import Settings

    dev = Settings(jwt_secret="x" * 40, field_encryption_key="k" * 32,
                   postgres_password="pw", debug=True, cookie_secure=False)
    assert dev.refresh_cookie_secure is False
    # 기본값은 켜짐 — 명시적으로 꺼야만 꺼진다
    assert Settings(jwt_secret="x" * 40, field_encryption_key="k" * 32,
                    postgres_password="pw", debug=True).refresh_cookie_secure is True


def test_개발_설정에서만_Secure가_빠진다():
    """http://localhost 는 `Secure` 쿠키를 저장하지 않는다 — 개발이 막히지 않게 푸는 유일한 경로."""
    from fastapi import Response

    from app.api.cookies import set_refresh_cookie
    from app.core.config import Settings

    base = dict(jwt_secret="x" * 40, field_encryption_key="k" * 32, postgres_password="pw")

    dev = Response()
    set_refresh_cookie(dev, "jwt", Settings(**base, debug=True, cookie_secure=False))
    assert "secure" not in dev.headers["set-cookie"].lower()
    # 풀어주는 것은 Secure 뿐 — 나머지 방어는 개발에서도 그대로다
    assert "httponly" in dev.headers["set-cookie"].lower()
    assert "samesite=strict" in dev.headers["set-cookie"].lower()

    prod = Response()
    set_refresh_cookie(prod, "jwt", Settings(**base, debug=False, cookie_secure=False))
    assert "secure" in prod.headers["set-cookie"].lower()


def test_쿠키_삭제_속성이_발급과_동일하다():
    """이름·Path·속성이 하나라도 다르면 브라우저는 원본 쿠키를 남긴다 = 로그아웃 실패."""
    from fastapi import Response

    from app.api.cookies import (
        REFRESH_COOKIE_PATH,
        delete_refresh_cookie,
        set_refresh_cookie,
    )
    from app.core.config import Settings

    settings = Settings(jwt_secret="x" * 40, field_encryption_key="k" * 32,
                        postgres_password="pw")

    issued = Response()
    set_refresh_cookie(issued, "some.jwt.value", settings)
    removed = Response()
    delete_refresh_cookie(removed, settings)

    def _attrs(header: str) -> set[str]:
        # 값(Max-Age·Expires·쿠키 값)을 뺀 속성 집합만 비교한다
        return {p.strip().lower() for p in header.split(";")
                if not p.strip().lower().startswith(("refresh_token=", "max-age", "expires"))}

    assert _attrs(issued.headers["set-cookie"]) == _attrs(removed.headers["set-cookie"])
    assert f"path={REFRESH_COOKIE_PATH}" in removed.headers["set-cookie"].lower()
    assert "max-age=0" in removed.headers["set-cookie"].lower()


# ---------------------------------------------------------------------------
# 로그 마스킹 (G3)
# ---------------------------------------------------------------------------

def test_민감필드가_마스킹된다():
    payload = {"email": "a@b.c", "cash_krw": 300_000_000, "income_krw": 90_000_000}
    masked = mask_sensitive(payload)

    assert masked["email"] == "a@b.c"
    assert masked["cash_krw"] == "***"
    assert masked["income_krw"] == "***"


def test_중첩_구조도_마스킹된다():
    payload = {"user": {"profile": {"cash_krw": 1, "owned_houses": 2}},
               "items": [{"password": "x"}]}
    masked = mask_sensitive(payload)

    assert masked["user"]["profile"]["cash_krw"] == "***"
    assert masked["user"]["profile"]["owned_houses"] == 2
    assert masked["items"][0]["password"] == "***"


def test_토큰도_마스킹된다():
    masked = mask_sensitive({"access_token": "abc", "refresh_token": "def"})
    assert masked["access_token"] == "***"
    assert masked["refresh_token"] == "***"


def test_대소문자_무관하게_마스킹():
    assert mask_sensitive({"Authorization": "Bearer x"})["Authorization"] == "***"


def test_순환_깊이에서_멈춘다():
    d: dict = {}
    cur = d
    for _ in range(30):
        cur["next"] = {}
        cur = cur["next"]
    mask_sensitive(d)   # 예외 없이 끝나야 한다


def test_문자열을_통째로_넘기면_전부_가린다():
    """★ SR33-1. **이름이 하는 일과 맞아야 한다.**

    이 함수는 dict 의 **키 이름**으로 민감 필드를 찾는 구조 마스커다. 문자열 하나에는
    볼 키가 없어 가릴 수 없는데, 예전에는 **그대로 돌려줬다.** 그래서 호출부
    (`main.unhandled` 의 500 로거)가 마스킹이 걸린 줄 알고 URL 을 통째로 넘겼고,
    쿼리스트링이 `docker logs` 로 나갔다(SR33-1).

    "아무 일도 안 함"과 "가림"이 겉보기에 같으면 다음 사람도 같은 실수를 한다.
    가리지 못하는 입력은 **전부 가린다** — 로그에 `***` 가 찍히면 잘못 쓴 게 보인다.

    변이: `mask_sensitive` 의 문자열 분기를 지우면(= 옛 동작) 여기서 깨진다.
    """
    url = "http://x/api/v1/map/complexes?complex_id=1234&max_price_krw=1314310000"
    assert mask_sensitive(url) == "***"
    assert mask_sensitive(b"secret-bytes") == "***"
    # 오해 방지: 값이 **구조 안**에 있으면 키로 판정할 수 있으므로 그대로 둔다.
    # (여기까지 가리면 모든 로그가 `***` 가 되어 아무도 안 본다.)
    assert mask_sensitive({"note": "hello"})["note"] == "hello"


def test_문자열_마스킹이_URL_대체수단을_가리킨다():
    """가리지 못하는 입력에는 **대신 무엇을 쓸지**가 적혀 있어야 한다.

    `"***"` 만 돌려주고 끝나면 다음 사람은 "왜 로그가 비었지"에서 멈춘다.
    URL 의 정답은 `log_target(path, query)`(쿼리 **이름만** 남긴다)이고,
    그 사실은 함수 문서에 있어야 한다 — 문서가 없으면 다음 사람은 함수 이름을 믿는다.
    """
    from app.main import log_target

    assert "log_target" in (mask_sensitive.__doc__ or ""), (
        "mask_sensitive 문서가 URL 대체수단을 알려주지 않는다")
    assert log_target("/api/v1/map/complexes", "bbox=126.9&max_price_krw=1") == (
        "/api/v1/map/complexes [q: bbox,max_price_krw]")
