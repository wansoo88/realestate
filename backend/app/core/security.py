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
import functools
import logging
import os
import secrets
import threading
from typing import Any

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import (
    Argon2Error,
    InvalidHashError,
    VerifyMismatchError,
)
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger("app.core.security")

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

#: OWASP Password Storage Cheat Sheet 의 Argon2id 권장 하한.
#: **이 아래로는 내리지 않는다.** 메모리가 모자라면 파라미터가 아니라
#: 동시성(`argon2_concurrency`)을 줄인다 — 파라미터를 깎으면 오프라인 크래킹
#: 난이도가 그대로 내려가지만, 동시성을 줄이면 느려질 뿐 강도는 유지된다.
OWASP_MIN_MEMORY_KIB = 19456   # 19 MiB
OWASP_MIN_TIME_COST = 2
OWASP_MIN_PARALLELISM = 1


class DecryptionError(Exception):
    """복호화 실패. 키가 다르거나, 데이터가 변조됐거나, 다른 사용자의 암호문이다."""


class HashCapacityError(Exception):
    """비밀번호 해시를 **지금은** 수행할 수 없다 — 자원 부족. 재시도하면 될 수 있다.

    두 가지 원인을 한 타입으로 묶는다. 호출부가 할 일이 같기 때문이다(503 + 재시도).
      1. 동시 실행 슬롯을 못 얻음 (우리가 건 세마포어, SR8-1)
      2. argon2 가 메모리 확보에 실패 (`HashingError`/`VerificationError`, SR8-2)

    대기하다 스레드풀이 전부 막히면 지도·리포트 같은 **다른 기능까지 죽는다.**
    인증만 잠깐 503 으로 흘려보내는 편이 낫다(main.py 가 503 으로 변환).

    ⚠️ **500 으로 내보내면 안 된다.** 500 은 "서버 버그, 재시도해도 소용없다"는 뜻이라
    자원 부족(잠시 뒤 되는 상태)에 붙이면 클라이언트가 재시도를 포기한다. (SR8-2)
    """


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


def argon2_parameter_problems(settings: Any) -> list[str]:
    """설정된 Argon2 파라미터가 OWASP 하한을 만족하는지. 정상이면 빈 목록."""
    problems: list[str] = []
    if settings.argon2_memory_kib < OWASP_MIN_MEMORY_KIB:
        problems.append(
            f"ARGON2_MEMORY_KIB={settings.argon2_memory_kib} 는 OWASP 하한"
            f" {OWASP_MIN_MEMORY_KIB}KiB(19MiB) 미만입니다. 메모리가 부족하면"
            " 파라미터가 아니라 ARGON2_CONCURRENCY 를 줄이세요"
        )
    if settings.argon2_time_cost < OWASP_MIN_TIME_COST:
        problems.append(
            f"ARGON2_TIME_COST={settings.argon2_time_cost} 는 OWASP 하한"
            f" {OWASP_MIN_TIME_COST} 미만입니다"
        )
    if settings.argon2_parallelism < OWASP_MIN_PARALLELISM:
        problems.append(
            f"ARGON2_PARALLELISM={settings.argon2_parallelism} 는"
            f" {OWASP_MIN_PARALLELISM} 이상이어야 합니다"
        )
    if settings.argon2_concurrency < 1:
        problems.append("ARGON2_CONCURRENCY 는 1 이상이어야 합니다")
    return problems


@functools.lru_cache(maxsize=8)
def _build_hasher(memory_kib: int, time_cost: int, parallelism: int) -> PasswordHasher:
    """파라미터별 해셔. 값이 바뀌면 새로 만든다(설정을 바꾼 테스트도 그대로 동작).

    하한 검증을 여기서도 한 번 더 한다. `validate_runtime` 은 기동 점검일 뿐
    호출을 강제할 수 없어서, **실제로 해시를 만드는 길목**에 문을 달아 둔다.
    """
    if (memory_kib < OWASP_MIN_MEMORY_KIB or time_cost < OWASP_MIN_TIME_COST
            or parallelism < OWASP_MIN_PARALLELISM):
        raise ValueError(
            f"Argon2 파라미터가 OWASP 하한 미만입니다 "
            f"(m={memory_kib}KiB t={time_cost} p={parallelism} < "
            f"m={OWASP_MIN_MEMORY_KIB} t={OWASP_MIN_TIME_COST} "
            f"p={OWASP_MIN_PARALLELISM}). 비밀번호 강도를 낮추는 대신 "
            f"ARGON2_CONCURRENCY 를 줄이세요"
        )
    return PasswordHasher(memory_cost=memory_kib, time_cost=time_cost,
                          parallelism=parallelism, type=Type.ID)


@functools.lru_cache(maxsize=8)
def _build_gate(concurrency: int) -> threading.BoundedSemaphore:
    return threading.BoundedSemaphore(concurrency)


def _current() -> tuple[PasswordHasher, threading.BoundedSemaphore, float]:
    from app.core.config import get_settings

    s = get_settings()
    return (
        _build_hasher(s.argon2_memory_kib, s.argon2_time_cost, s.argon2_parallelism),
        _build_gate(s.argon2_concurrency),
        s.argon2_wait_timeout_sec,
    )


def get_hasher() -> PasswordHasher:
    """현재 설정의 해셔. 테스트·점검용."""
    return _current()[0]


class _Slot:
    """해시 연산 슬롯. 못 얻으면 기다리지 않고 `HashCapacityError`.

    동기 엔드포인트는 anyio 스레드풀(기본 40개)에서 돈다. 문을 안 달면
    로그인 폭주 하나로 40 × 19MiB = 760MiB 를 잡고 서버가 넘어간다.
    """

    def __init__(self, gate: threading.BoundedSemaphore, timeout: float) -> None:
        self._gate = gate
        self._timeout = timeout

    def __enter__(self) -> None:
        if not self._gate.acquire(timeout=self._timeout):
            raise HashCapacityError(
                f"비밀번호 해시 동시 실행 한도에 걸렸습니다({self._timeout}s 대기)"
            )

    def __exit__(self, *exc: Any) -> None:
        self._gate.release()


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LEN:
        raise ValueError(f"비밀번호는 최소 {MIN_PASSWORD_LEN}자여야 합니다")
    hasher, gate, timeout = _current()
    with _Slot(gate, timeout):
        try:
            return hasher.hash(password)
        except Argon2Error as exc:
            # 슬롯은 얻었지만 argon2 가 메모리를 못 잡았다 — 자원 부족이지 버그가 아니다.
            # `HashingError` 만 잡지 않고 `Argon2Error` 로 넓게 잡는다: 잘못된
            # 파라미터는 이미 `_build_hasher` 가 기동 시점에 걸러내므로, 여기까지 온
            # argon2 오류는 사실상 자원 문제다. 좁게 잡았다가 하나 놓치면 그게 500 이 된다.
            # 예외 메시지만 남긴다(비밀번호는 어떤 경우에도 로그에 넣지 않는다).
            logger.warning("Argon2 해시 실패(자원 부족 추정): %s: %s",
                           type(exc).__name__, exc)
            raise HashCapacityError("비밀번호 해시에 필요한 메모리를 확보하지 못했습니다") from exc


def verify_password(password: str, hashed: str) -> bool:
    """저장된 해시로 검증. 비밀번호가 틀리면 False, **확인 자체가 불가하면 예외.**

    이 구분이 중요하다. 메모리 부족으로 검증에 실패했는데 False 를 돌려주면
    "비밀번호가 틀렸다"고 **거짓말**하는 셈이고, 사용자는 멀쩡한 비밀번호를 의심하며
    계속 재시도한다. 확인을 못 했으면 못 했다고 말한다(→ 503).

    ⚠️ 파라미터를 바꿔도 **기존 해시는 그대로 검증된다.** argon2 는 m·t·p 를
    해시 문자열 안에 담고, 검증은 거기 적힌 값을 쓰기 때문이다.
    (그래서 SR8-1 수정에 재해시·마이그레이션이 필요 없다.)
    """
    hasher, gate, timeout = _current()
    with _Slot(gate, timeout):
        try:
            return hasher.verify(hashed, password)
        except VerifyMismatchError:
            # 비밀번호가 틀렸다 — 정상적인 실패.
            # ⚠️ `Argon2Error` 의 하위 타입이라 **반드시 먼저** 잡아야 한다.
            #    순서가 뒤바뀌면 틀린 비밀번호가 503 이 되고, 그 차이가
            #    계정 존재 여부를 알려주는 통로가 된다.
            return False
        except Argon2Error as exc:
            # 불일치가 아닌 argon2 실패 = 메모리 부족 등 자원 문제.
            logger.warning("Argon2 검증 실패(자원 부족 추정): %s: %s",
                           type(exc).__name__, exc)
            raise HashCapacityError("비밀번호 확인에 필요한 메모리를 확보하지 못했습니다") from exc
        except (InvalidHashError, ValueError):
            # 저장된 해시 문자열이 깨졌다 — 재시도해도 같다. 로그인 실패로 본다.
            return False


@functools.lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    """**존재하지 않는 계정**을 검증할 때 쓰는 버림용 해시 (계정 열거 방지).

    왜 필요한가
    -----------
    `user is not None and verify_password(...)` 는 논리적으로는 맞지만
    **시간이 다르다.** 없는 계정은 argon2 를 아예 돌리지 않아 즉시 401 이 나가고,
    있는 계정은 19MiB 해시를 돌린 뒤 401 이 나간다. 응답 본문이 똑같아도
    그 수십 ms 차이가 "이 이메일은 가입돼 있다"를 알려주는 오라클이 된다.
    승인제를 붙이면 이 신호의 값어치가 더 커진다 — 공격자는 "누가 가입 대기 중인지"를
    훑어 표적을 고를 수 있다.

    그래서 없는 계정에도 **같은 비용의 검증을 태운다.** 이 해시와는 어떤 비밀번호도
    일치하지 않는다(프로세스마다 난수로 만들고 밖으로 나가지 않는다).
    """
    # 12자 하한(MIN_PASSWORD_LEN)을 넉넉히 넘긴다. 이 값은 어디에도 저장되지 않는다.
    return hash_password(secrets.token_urlsafe(32))


def needs_rehash(hashed: str) -> bool:
    """현재 파라미터와 다른 해시인가.

    ⚠️ 파라미터를 **낮춘** 지금은 옛 64MiB 해시가 True 로 나온다. 그렇다고
    자동 재해시하면 더 약한 해시로 내려가는 셈이라, 호출부를 두지 않았다.
    """
    try:
        return _current()[0].check_needs_rehash(hashed)
    except (InvalidHashError, ValueError):
        return True


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

ACCESS_TTL = dt.timedelta(minutes=30)

#: refresh 수명. 설계(security.md §2.1)는 14일이었으나 **7일로 단축한다** (SR15-1).
#:
#: 근거: refresh 를 `httpOnly`+`Secure`+`SameSite=Strict` 쿠키로 옮기고 호출마다
#: 회전시켜 탈취 난이도는 크게 올라갔다. 하지만 **서버측 폐기 수단(jti denylist)이
#: 아직 없다** — 한 번 새어나간 refresh 는 만료될 때까지 되돌릴 방법이 없다.
#: 회수 수단이 없는 동안은 노출 창을 시간으로 줄이는 것이 유일한 통제라 절반으로 자른다.
#: (denylist 도입 = 후속 과제 SR15-3. 그때 이 값을 다시 논의한다.)
REFRESH_TTL = dt.timedelta(days=7)
_ALGORITHM = "HS256"

#: 클라이언트에 알려줄 access 수명(초). 라우터가 숫자를 따로 적지 않게 여기서 판다 —
#: 상수를 두 곳에 적으면 언젠가 어긋나고, 그러면 프론트가 만료 시각을 잘못 잡는다.
ACCESS_TTL_SECONDS = int(ACCESS_TTL.total_seconds())
REFRESH_TTL_SECONDS = int(REFRESH_TTL.total_seconds())


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
        # 토큰 고유 식별자. 두 가지 일을 한다.
        #   1) 같은 초에 두 번 발급해도 토큰 문자열이 달라진다 → 쿠키 회전이 실제로 회전이 된다.
        #   2) 서버측 폐기(denylist)를 붙일 때 필요한 키. 지금은 저장하지 않는다(SR15-3).
        "jti": secrets.token_urlsafe(12),
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_token(token: str, *, secret: str, expect: str = "access") -> int:
    """유효한 토큰이면 user_id 를 돌려준다. 아니면 예외.

    ⚠️ `typ` 검증은 **선택이 아니다.** 이게 없으면 수명이 긴 refresh 로 API 를 계속
    호출하거나(위), 반대로 access 를 refresh 쿠키에 넣어 갱신 루프를 돌릴 수 있다.
    호출부는 항상 기대하는 종류를 `expect` 로 명시한다.
    """
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
