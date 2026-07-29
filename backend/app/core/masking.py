"""비밀이 **문자열로 새는 경로**를 한곳에서 막는다 — URL · 예외 메시지 · 로그.

왜 이 모듈이 필요한가 (SR17-1)
------------------------------
공공데이터포털(국토부 실거래가)은 인증키를 **쿼리스트링**으로 받는다:

    https://apis.data.go.kr/.../getRTMSDataSvcAptTrade?serviceKey=<인증키>&LAWD_CD=11680

그래서 요청 URL 이 담긴 문자열은 그 자체가 인증키다. 문제는 URL 이 로그뿐 아니라
**예외 메시지**로도 흘러나온다는 것이다. `httpx.Response.raise_for_status()` 가 던지는
`HTTPStatusError` 의 문자열에는 요청 URL 이 통째로 들어간다:

    Client error '403 Forbidden' for url 'https://apis.data.go.kr/...?serviceKey=AbC%2B...'

이 문자열은 로거 레벨을 낮춰도 막히지 않는다. `str(exc)` 를 그대로 받아
`ingest_log`·`run.failures`·stdout·`config/region_code_verification.yaml`(커밋 대상!)
로 옮겨 적는 코드가 있기 때문이다. **로거 억제는 방어가 아니다.**

그래서 이 모듈이 하는 일
------------------------
1. `mask_secrets()` — 문자열 안의 비밀 파라미터 값을 `***` 로 바꾼다.
   원본(`serviceKey=`)뿐 아니라 **URL 인코딩된 형태**(`serviceKey%3D`, `%253D`)와
   dict/JSON 표기(`"serviceKey": "..."`)도 잡는다.
2. `masked_error()` / `secret_safe()` — 예외를 **비밀이 지워진 예외로 감싸** 올린다.
   비밀을 **가진 계층**(fetch, runner, probe)에서 한 번 감싸면 그 아래 모든 싱크가
   안전해진다. 진입점마다 억제를 부르는 방식은 하나만 빠져도 새기 때문이다.
3. `install_log_masking()` — 로그 레코드 팩토리·핸들러에 마스킹을 건다(마지막 그물).

원칙
----
- **비밀을 아는 쪽이 지운다.** 호출자가 기억해서 부르는 방어는 언젠가 빠진다.
- 못 미더우면 지운다. 과하게 가려서 디버깅이 불편한 것이 키가 새는 것보다 낫다.
"""
from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable
from contextlib import contextmanager
from typing import Any

MASK = "***"

#: 값이 비밀인 쿼리 파라미터 / JSON 키. 소문자 비교(대소문자 무시)로 매칭한다.
#: `key` 는 흔한 단어라 여기 넣지 않고 `_BARE_KEY_RE` 로 쿼리스트링 안에서만 잡는다.
SECRET_PARAM_KEYS: tuple[str, ...] = (
    "serviceKey", "service_key",
    "apiKey", "api_key", "apikey",
    "authKey", "auth_key",
    "accessKey", "access_key", "secretKey", "secret_key",
    "appKey", "app_key", "appkey",
    "client_secret", "clientSecret",
    "access_token", "refresh_token", "id_token", "token",
    "authorization", "auth",
    "password", "passwd", "pwd", "secret", "signature",
)

#: 값 자체를 문자열 어디서든 지워야 하는 환경변수. 파라미터 이름을 못 알아봐도
#: (리다이렉트·본문 echo·헤더 덤프 등) 실제 비밀값이면 지워진다.
#:
#: ⚠️ **새 비밀 칸을 `.env.example` 에 만들면 여기에도 넣는다.** 이름 기반 규칙
#: (`_QUERY_RE` 등)은 파라미터 이름이 우리가 아는 형태일 때만 듣고, 경로형 URL·
#: dict repr·오류 본문의 되비침은 못 잡는다. 그 구멍으로 SR24-1(경로형 인증키)이
#: 났고, `NEIS_API_KEY` 는 칸만 만들어진 채 이 목록에 없었다(SR29-2).
#: `tests/test_script_hygiene.py` 가 `.env.example` 과 이 목록을 대조한다(SR29-9).
SECRET_ENV_VARS: tuple[str, ...] = (
    "MOLIT_API_KEY", "DATA_GO_KR_API_KEY",
    "KAKAO_REST_API_KEY", "KAKAO_JS_APP_KEY",
    "NEIS_API_KEY",
    "ANTHROPIC_API_KEY",
    "JWT_SECRET", "FIELD_ENCRYPTION_KEY",
    "POSTGRES_PASSWORD",
)

#: 이보다 짧은 값은 리터럴 치환 대상에서 뺀다 — 흔한 짧은 문자열을 전부 `***` 로
#: 바꿔 버리면 로그가 못 읽게 된다(그리고 그런 값은 애초에 비밀로 쓰면 안 된다).
MIN_LITERAL_SECRET_LEN = 8

# --- 정규식 ---------------------------------------------------------------
# `=` 는 URL 인코딩되면 `%3D`, 두 번 인코딩되면 `%253D` 로 온다. 셋 다 받는다.
_EQ = r"(?:%253[Dd]|%3[Dd]|=)"
# 값의 끝: `&`(또는 인코딩된 `%26`), 공백, 따옴표, 괄호류, 쉼표/세미콜론, 역슬래시, `#`.
# base64 키에 흔한 `+ / = % - _` 는 끝 문자가 아니므로 값 안에 그대로 남는다.
_VALUE = r"(?:(?!%26)[^&\s\"'<>\)\]\},;\\#])+"
_KEY_ALT = "|".join(re.escape(k) for k in sorted(SECRET_PARAM_KEYS, key=len, reverse=True))

#: `serviceKey=...` / `serviceKey%3D...` — 앞 글자가 영숫자·`_` 면 매칭하지 않는다
#: (`sort_token=` 같은 다른 이름의 꼬리를 잘못 잡지 않게).
_QUERY_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?P<key>" + _KEY_ALT + r")(?P<eq>" + _EQ + r")(?P<val>" + _VALUE + r")",
    re.IGNORECASE,
)

#: 쿼리스트링 안의 `?key=` / `&key=` 만. 일반 문장의 'key=' 는 건드리지 않는다.
_BARE_KEY_RE = re.compile(
    r"(?<=[?&])(?P<key>key)(?P<eq>" + _EQ + r")(?P<val>" + _VALUE + r")",
    re.IGNORECASE,
)

#: `"serviceKey": "..."` / `'password': '...'` — dict repr·JSON 덤프 경로.
_MAPPING_RE = re.compile(
    r"(?P<pre>[\"'](?P<key>" + _KEY_ALT + r")[\"']\s*:\s*)(?P<q>[\"'])(?P<val>(?:[^\"'\\]|\\.)*)(?P=q)",
    re.IGNORECASE,
)


def _literal_variants(secrets: Iterable[str]) -> list[str]:
    """비밀 원문 + URL 인코딩 변형들. 긴 것부터 지워야 부분 치환이 안 생긴다."""
    from urllib.parse import quote, quote_plus, unquote

    out: set[str] = set()
    for raw in secrets:
        value = (raw or "").strip()
        if len(value) < MIN_LITERAL_SECRET_LEN:
            continue
        for variant in (value, quote(value, safe=""), quote_plus(value), unquote(value)):
            if len(variant) >= MIN_LITERAL_SECRET_LEN:
                out.add(variant)
                # httpx 는 대문자 hex(%3D)를 쓰지만 라이브러리에 따라 소문자(%3d)도 있다.
                lowered = re.sub(r"%([0-9A-Fa-f]{2})", lambda m: "%" + m.group(1).lower(), variant)
                out.add(lowered)
    return sorted(out, key=len, reverse=True)


def env_secrets() -> tuple[str, ...]:
    """현재 프로세스 환경에 실려 있는 비밀값들(값이 있는 것만)."""
    out: list[str] = []
    for name in SECRET_ENV_VARS:
        value = os.getenv(name, "").strip()
        if len(value) >= MIN_LITERAL_SECRET_LEN:
            out.append(value)
    return tuple(out)


def mask_secrets(value: Any, *, extra_secrets: Iterable[str] = (),
                 use_env: bool = True) -> str:
    """문자열에서 비밀로 보이는 값들을 `***` 로 바꾼다.

    잡는 것
    -------
    - `serviceKey=<값>` · `serviceKey%3D<값>` · `serviceKey%253D<값>` (대소문자 무시)
    - `?key=<값>` (쿼리스트링 안의 짧은 이름)
    - `"password": "<값>"` 같은 dict/JSON 표기
    - `extra_secrets` · 환경변수(`SECRET_ENV_VARS`)의 **실제 값**과 그 URL 인코딩 변형

    문자열이 아니면 `str()` 로 바꿔서 처리한다(예외 객체를 그대로 넘겨도 된다).
    """
    text = value if isinstance(value, str) else str(value)

    text = _QUERY_RE.sub(lambda m: m.group("key") + m.group("eq") + MASK, text)
    text = _BARE_KEY_RE.sub(lambda m: m.group("key") + m.group("eq") + MASK, text)
    text = _MAPPING_RE.sub(
        lambda m: m.group("pre") + m.group("q") + MASK + m.group("q"), text)

    literals = list(extra_secrets)
    if use_env:
        literals.extend(env_secrets())
    for literal in _literal_variants(literals):
        text = text.replace(literal, MASK)
    return text


def mask_url(url: str, *, extra_secrets: Iterable[str] = ()) -> str:
    """URL 하나를 마스킹한다. `mask_secrets` 의 의도를 드러내는 이름."""
    return mask_secrets(url, extra_secrets=extra_secrets)


# --- 예외 ------------------------------------------------------------------

class SecretSafeError(RuntimeError):
    """비밀이 지워진 메시지만 들고 있는 예외.

    원본 예외는 **체인에서 끊는다**(`raise ... from None`). `__cause__`/`__context__`
    로 남겨 두면 traceback 출력에 원본 메시지(=URL=키)가 다시 찍히기 때문이다.
    """

    def __init__(self, message: str, *, original_type: str | None = None,
                 status_code: int | None = None) -> None:
        super().__init__(message)
        self.original_type = original_type
        self.status_code = status_code


def masked_error(exc: BaseException, *, prefix: str = "",
                 extra_secrets: Iterable[str] = ()) -> SecretSafeError:
    """예외 → 비밀이 지워진 `SecretSafeError`. 상태코드는 살려서 넘긴다."""
    detail = mask_secrets(f"{type(exc).__name__}: {exc}", extra_secrets=extra_secrets)
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if not isinstance(status, int):
        status = getattr(exc, "status_code", None)
        if not isinstance(status, int):
            status = None
    return SecretSafeError(f"{prefix}{detail}" if prefix else detail,
                           original_type=type(exc).__name__, status_code=status)


@contextmanager
def secret_safe(prefix: str = "", *, extra_secrets: Iterable[str] = ()):
    """블록 안에서 난 예외를 마스킹한 예외로 바꿔 올린다.

    비밀을 **가진 계층**에서 이 블록으로 감싸는 것이 이 모듈의 주 사용법이다.
    """
    try:
        yield
    except SecretSafeError:
        raise                                   # 이미 안전하다 — 두 번 감싸지 않는다
    except Exception as exc:
        raise masked_error(exc, prefix=prefix, extra_secrets=extra_secrets) from None


# --- 로깅 ------------------------------------------------------------------

def _mask_record(record: logging.LogRecord) -> None:
    """LogRecord 의 메시지(+ 포맷 인자)를 마스킹한다.

    ⚠️ **가능하면 인자를 제자리에서 지우고, 레코드 구조를 보존한다**(SR32-1 에서 발견).
       예전에는 무조건 `record.msg = <완성된 문자열>; record.args = ()` 로 뭉갰다.
       그런데 uvicorn 의 `AccessFormatter` 는 `record.args` 를 **5-튜플로 언패킹**한다:

           (client_addr, method, path, http_version, status_code) = record.args

       그래서 접근 로그 줄에 비밀처럼 생긴 파라미터(`?secret=…`)가 하나라도 있으면
       그 줄이 뭉개져 언패킹이 터지고, logging 이 `--- Logging error ---` 폴백으로
       **원본 메시지를 그대로** 찍었다(실측). 지우려던 방어가 오히려 포맷을 무너뜨려
       가공되지 않은 줄을 내보내는 형태다. 인자만 지우면 구조가 그대로 남는다.
    """
    try:
        message = record.getMessage()
    except Exception:                            # noqa: BLE001 - 로깅이 앱을 죽이면 안 된다
        return
    if mask_secrets(message) == message:
        return

    args = record.args
    if isinstance(args, tuple) and args:
        masked_args = tuple(mask_secrets(a) if isinstance(a, str) else a for a in args)
        if masked_args != args:
            record.args = masked_args
            try:
                rendered = record.getMessage()
            except Exception:                    # noqa: BLE001
                rendered = None
            if rendered is not None and mask_secrets(rendered) == rendered:
                return                           # 인자만 지워도 깨끗하다 — 구조 보존
            args = record.args                   # 아래 폴백에서 다시 렌더한다

    # 비밀이 템플릿(msg) 쪽에 있으면 구조를 지킬 방법이 없다 — 통째로 대체한다.
    try:
        record.msg = mask_secrets(record.getMessage())
    except Exception:                            # noqa: BLE001
        record.msg = mask_secrets(str(record.msg))
    record.args = ()


class SecretMaskingFilter(logging.Filter):
    """핸들러에 붙여 메시지와 **traceback 문자열**까지 마스킹한다.

    레코드 팩토리(`install_log_masking`)는 메시지를 잡지만 `exc_info` 는 못 잡는다.
    traceback 은 핸들러의 Formatter 가 나중에 문자열로 만들기 때문이다.
    여기서 미리 만들어 마스킹해 `exc_text` 에 넣어 두면 Formatter 가 그걸 쓴다.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        _mask_record(record)
        if record.exc_text:
            record.exc_text = mask_secrets(record.exc_text)
        elif record.exc_info:
            import traceback

            try:
                text = "".join(traceback.format_exception(*record.exc_info)).rstrip()
            except Exception:                    # noqa: BLE001
                return True
            record.exc_text = mask_secrets(text)
        return True


# --- 접근 로그의 쿼리스트링 ------------------------------------------------
#
# ★ SR32-1. **앱이 지운 줄을 uvicorn 이 한 줄 아래에 다시 쓴다.**
#
# `app/main.py` 의 미들웨어는 접근 로그에서 쿼리를 지운다. 그런데 uvicorn 은
# 자기 로거(`uvicorn.access`)로 같은 요청을 **쿼리째** 한 번 더 쓴다:
#
#     INFO: 127.0.0.1:51891 - "GET /api/v1/map/complexes?max_price_krw=1314310000 HTTP/1.1" 200 OK
#
# 이 로거는 우리 미들웨어를 지나지 않으므로 앱 쪽 규칙과 **무관하게** 동작한다.
# 그래서 값이 아니라 **싱크**를 막는다 — `uvicorn.access` 로거에 필터를 걸어
# 경로만 남기고 `?` 뒤를 잘라낸다.
#
# ⚠️ **왜 `--access-log` 를 끄지 않았나.** 끄는 것도 SR-032 가 제시한 선택지지만,
#    그러면 그 방어가 **배포 명령줄**(docker-compose `command:`)에 살게 된다.
#    명령줄은 서버에서 손으로 고쳐지고, 고친 사람은 이 파일을 읽지 않는다.
#    필터는 코드에 있고 테스트가 지킨다(`tests/test_access_log.py`).
#    로그 자체는 켜 둔다 — 어떤 요청이 몇 번 왔는지는 운영에 필요한 사실이다.

#: uvicorn 이 만드는 접근 로그 레코드의 인자 형태(0.49.0 기준):
#:     msg  = '%s - "%s %s HTTP/%s" %d'
#:     args = (client_addr, method, path_with_query, http_version, status_code)
#: **위치(index)에 의존하지 않는다.** uvicorn 이 인자 순서를 바꿔도 계속 듣도록
#: "슬래시로 시작하고 `?` 를 품은 문자열"이면 자른다 — 그 모양이 곧 경로+쿼리다.
def _strip_query(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("/") and "?" in value:
        return value.split("?", 1)[0]
    return value


#: 이미 **완성된 문자열** 안에서 경로+쿼리를 찾는다.
#: `'127.0.0.1:5189 - "GET /api/v1/map/complexes?bbox=… HTTP/1.1" 200'`
#: 인자가 뭉개져 들어오는 경우(비밀 마스킹 폴백 등)를 대비한 두 번째 그물이다.
_PATH_QUERY_IN_TEXT_RE = re.compile(r"(/[^\s\"'?]*)\?[^\s\"']*")


class AccessLogQueryFilter(logging.Filter):
    """접근 로그에서 **쿼리스트링을 지운다**(경로·상태코드는 남긴다).

    지우는 쪽을 기본값으로 두는 이유는 `app/main.py` 의 미들웨어 주석과 같다:
    민감한지 아닌지를 **경로 목록으로 관리하면 언젠가 한 줄이 빠진다**.
    SR32-1 이 정확히 그 형태였다(`/map/complexes` 만 목록에 없었다).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple):
            stripped = tuple(_strip_query(a) for a in args)
            if stripped != args:
                record.args = stripped
        elif isinstance(args, dict):                    # pragma: no cover - 방어
            stripped_map = {k: _strip_query(v) for k, v in args.items()}
            if stripped_map != args:
                record.args = stripped_map
        # 인자가 없어 메시지에 이미 박혀 들어온 경우(비밀 마스킹 폴백 등)도 지운다.
        if not record.args and isinstance(record.msg, str) and "?" in record.msg:
            record.msg = _PATH_QUERY_IN_TEXT_RE.sub(r"\1", record.msg)
        return True


#: 쿼리를 지울 접근 로거들. uvicorn 이 표준이고, 다른 서버로 갈아타면 여기 추가한다.
ACCESS_LOGGER_NAMES: tuple[str, ...] = ("uvicorn.access",)


def install_access_log_query_stripping(
        logger_names: Iterable[str] = ACCESS_LOGGER_NAMES) -> None:
    """접근 로거에 쿼리 제거 필터를 건다. **멱등**.

    ⚠️ 로거 자체에 건다(핸들러가 아니라). uvicorn 은 `configure_logging()` 에서
       `dictConfig` 로 핸들러를 **갈아끼우는데**, 그때 로거의 필터는 지워지지 않는다
       (`logging.config.common_logger_config` 는 handlers 만 제거한다).
       핸들러에 걸면 재설정 한 번에 방어가 사라진다.
    """
    for name in logger_names:
        logger = logging.getLogger(name)
        if not any(isinstance(f, AccessLogQueryFilter) for f in logger.filters):
            logger.addFilter(AccessLogQueryFilter())


def install_log_masking() -> None:
    """레코드 팩토리 + 루트 로거/핸들러에 마스킹을 설치한다. **멱등**.

    접근 로그의 쿼리 제거(SR32-1)도 **여기서 함께** 건다 — 로그 싱크 방어를
    두 곳에서 부르게 하면 한쪽만 부르는 진입점이 생긴다(`worker.py`·`scripts/_common.py`
    도 이 함수만 부른다).
    """
    install_access_log_query_stripping()

    factory = logging.getLogRecordFactory()
    if not getattr(factory, "_secret_masking", False):
        def masking_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
            record = factory(*args, **kwargs)
            _mask_record(record)
            return record

        masking_factory._secret_masking = True   # type: ignore[attr-defined]
        logging.setLogRecordFactory(masking_factory)

    root = logging.getLogger()
    targets: list[Any] = [root, *root.handlers]
    for target in targets:
        if not any(isinstance(f, SecretMaskingFilter) for f in target.filters):
            target.addFilter(SecretMaskingFilter())
