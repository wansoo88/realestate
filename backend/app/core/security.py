"""보안 코어 — 필드 암호화 · 비밀번호 해시 · JWT · 로그 마스킹.

설계 근거: docs/02-design/security.md §2, §3

암호화 방식 결정 (security.md §3.1)
-----------------------------------
**앱단 AES-256-GCM**을 쓴다. pgcrypto 를 쓰지 않는 이유는 키가 SQL 문에 실려
`pg_stat_activity`·쿼리 로그에 남기 때문이다. 그러면 DB 가 뚫릴 때 데이터와 키가 함께 털린다.

앱단 암호화는 **DB 덤프가 유출돼도 복호화되지 않는다**(T1·T3 차단).
대신 DB 안에서 금액으로 검색·정렬할 수 없는데, 이 제품에서는 그럴 일이 없다.

AAD 바인딩
----------
암호문에 `user:{id}:{field}` 를 AAD 로 묶는다. 그래서 공격자가 DB 를 쓸 수 있어도
**A 사용자의 자산 암호문을 B 사용자 행에 복사해 넣는 공격**이 실패한다(복호화가 깨진다).
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

#: 암호문 포맷 버전. 키 교체·알고리즘 변경 시 올린다.
_VERSION = b"\x01"
_NONCE_LEN = 12
_KEY_LEN = 32  # AES-256

#: 로그·에러에 절대 남기면 안 되는 필드 (security.md §3.3)
SENSITIVE_FIELDS: frozenset[str] = frozenset({
    "cash_krw", "income_krw", "existing_loan_krw",
    "cash_krw_enc", "income_krw_enc", "existing_loan_krw_enc",
    "password", "password_hash",
    "access_token", "refresh_token", "authorization",
    "field_encryption_key", "jwt_secret",
})

_hasher = PasswordHasher()


class DecryptionError(Exception):
    """복호화 실패. 키가 다르거나, 데이터가 변조됐거나, 다른 사용자의 암호문이다."""


# ---------------------------------------------------------------------------
# 필드 암호화
# ---------------------------------------------------------------------------

def _aad(user_id: int, field: str) -> bytes:
    return f"user:{user_id}:{field}".encode()


def load_key(raw: str | bytes) -> bytes:
    """설정값에서 32바이트 키를 얻는다. 길이가 맞지 않으면 즉시 실패한다."""
    key = raw.encode() if isinstance(raw, str) else raw
    if len(key) != _KEY_LEN:
        raise ValueError(
            f"FIELD_ENCRYPTION_KEY 는 {_KEY_LEN}바이트여야 합니다 (현재 {len(key)}바이트). "
            "약한 키로 조용히 돌아가느니 시작을 막습니다."
        )
    return key


def generate_key() -> bytes:
    return os.urandom(_KEY_LEN)


def encrypt_amount(value: int, *, user_id: int, field: str, key: bytes) -> bytes:
    """금액을 암호화한다. 저장 형식: version(1) + nonce(12) + ciphertext."""
    if not isinstance(value, int):
        raise TypeError("금액은 정수(원)여야 합니다")
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, str(value).encode(), _aad(user_id, field))
    return _VERSION + nonce + ct


def decrypt_amount(blob: bytes | None, *, user_id: int, field: str, key: bytes) -> int | None:
    """복호화. 값이 없으면 None. 변조·타인 데이터면 DecryptionError."""
    if blob is None:
        return None
    if len(blob) < 1 + _NONCE_LEN + 16:
        raise DecryptionError("암호문 길이가 비정상입니다")
    version, nonce, ct = blob[:1], blob[1:1 + _NONCE_LEN], blob[1 + _NONCE_LEN:]
    if version != _VERSION:
        raise DecryptionError(f"지원하지 않는 암호문 버전: {version!r}")
    try:
        plain = AESGCM(key).decrypt(nonce, ct, _aad(user_id, field))
    except InvalidTag as exc:
        # 어떤 이유로 실패했는지 구체적으로 말하지 않는다(오라클 방지).
        raise DecryptionError("복호화에 실패했습니다") from exc
    return int(plain.decode())


# ---------------------------------------------------------------------------
# 비밀번호
# ---------------------------------------------------------------------------

MIN_PASSWORD_LEN = 12


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LEN:
        raise ValueError(f"비밀번호는 최소 {MIN_PASSWORD_LEN}자여야 합니다")
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def needs_rehash(hashed: str) -> bool:
    try:
        return _hasher.check_needs_rehash(hashed)
    except (InvalidHashError, ValueError):
        return True


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

ACCESS_TTL = dt.timedelta(minutes=30)
REFRESH_TTL = dt.timedelta(days=14)
_ALGORITHM = "HS256"


def create_token(user_id: int, *, secret: str, kind: str = "access",
                 now: dt.datetime | None = None) -> str:
    if kind not in ("access", "refresh"):
        raise ValueError("kind 는 access 또는 refresh")
    now = now or dt.datetime.now(dt.timezone.utc)
    ttl = ACCESS_TTL if kind == "access" else REFRESH_TTL
    payload = {
        "sub": str(user_id),
        "typ": kind,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_token(token: str, *, secret: str, expect: str = "access") -> int:
    """유효한 토큰이면 user_id 를 돌려준다. 아니면 예외."""
    payload: dict[str, Any] = jwt.decode(token, secret, algorithms=[_ALGORITHM])
    if payload.get("typ") != expect:
        # refresh 토큰으로 API 를 호출하는 것을 막는다.
        raise jwt.InvalidTokenError(f"토큰 종류가 다릅니다: {payload.get('typ')}")
    return int(payload["sub"])


# ---------------------------------------------------------------------------
# 로그 마스킹
# ---------------------------------------------------------------------------

def mask_sensitive(data: Any, *, _depth: int = 0) -> Any:
    """로그에 남기기 전에 민감 필드를 가린다.

    중첩 dict/list 를 재귀적으로 훑는다. 깊이 제한을 둬 순환 참조에서 멈춘다.
    """
    if _depth > 12:
        return "***"
    if isinstance(data, dict):
        return {
            k: ("***" if str(k).lower() in SENSITIVE_FIELDS
                else mask_sensitive(v, _depth=_depth + 1))
            for k, v in data.items()
        }
    if isinstance(data, (list, tuple)):
        return type(data)(mask_sensitive(v, _depth=_depth + 1) for v in data)
    return data
