"""보안 코어 테스트 — security-review 게이트(G3)의 실증.

여기서 실패하면 개인 금융정보가 새는 것이므로, 다른 어떤 테스트보다 우선한다.
"""
from __future__ import annotations

import datetime as dt

import jwt
import pytest

from app.core.security import (
    DecryptionError,
    decode_token,
    decrypt_amount,
    encrypt_amount,
    generate_key,
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
