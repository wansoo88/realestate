"""비밀 마스킹 회귀 테스트 (SR17-1 / SR17-3).

무엇을 못 박는가
----------------
국토부 실거래가 API 는 인증키를 **쿼리스트링**으로 받는다. 그래서 요청 URL 이 담긴
문자열은 그 자체가 인증키다. `httpx` 의 `raise_for_status()` 는 요청 URL 을 통째로
넣은 예외를 던지고, 그 `str(exc)` 는 아래 경로를 타고 **파일로 나간다**:

    fetch → runner.run.failures → scripts/run_ingest.py 의 print → /tmp/*.log
    fetch → probe() → classify() → verdict → config/region_code_verification.yaml (커밋 대상!)

이 테스트는 그 두 경로의 **끝단 산출물**에 키가 없다는 것을 확인한다.
로거 레벨을 낮추는 방식으로는 통과할 수 없는 테스트다 — 일부러 그렇게 짰다.

⚠️ 여기 쓰는 키는 **가짜**다. 실제 발급 키를 테스트에 넣지 말 것.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import logging
import sys
from pathlib import Path
from urllib.parse import quote, unquote

import httpx
import pytest

from app.core.masking import (
    MASK,
    SecretMaskingFilter,
    SecretSafeError,
    install_log_masking,
    mask_secrets,
    mask_url,
    masked_error,
)
from app.ingest.ratelimit import RateLimiter
from app.ingest.run_molit import MOLIT_ENDPOINT, make_http_fetch
from app.ingest.runner import run_molit_trade_ingest

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = BACKEND_DIR / "scripts"

#: 실제 공공데이터포털 인증키의 모양을 흉내낸 **가짜** 값.
#: base64 문자(`+`, `/`, `=`)가 섞여 있어야 URL 인코딩 변형(%2B·%2F·%3D)까지 검증된다.
FAKE_KEY = "Zm9vQmFyMTIzNDU2Nzg5+abc/def=="
#: 인코딩되든 안 되든 절대 남으면 안 되는 조각.
KEY_CORE = "Zm9vQmFyMTIzNDU2Nzg5"


def assert_no_key(text: str, *, key: str = FAKE_KEY, core: str = KEY_CORE) -> None:
    """문자열(과 그 URL 디코딩본)에 키가 없어야 한다.

    `unquote` 를 한 번 돌리는 이유: `=` 만 `%3D` 로 인코딩된 형태는 **디코딩 한 번에
    원본이 복원**된다. 인코딩됐다는 이유로 안전하다고 볼 수 없다.
    """
    for candidate in (text, unquote(text), unquote(unquote(text))):
        assert key not in candidate, f"원본 키가 남았습니다: {text!r}"
        assert core not in candidate, f"키 조각이 남았습니다: {text!r}"


# ---------------------------------------------------------------------------
# 1. 마스킹 유틸 자체
# ---------------------------------------------------------------------------

def test_masks_plain_query_string():
    url = f"{MOLIT_ENDPOINT}?serviceKey={FAKE_KEY}&LAWD_CD=11680&DEAL_YMD=202506"
    out = mask_url(url)
    assert_no_key(out)
    assert "serviceKey=***" in out
    assert "LAWD_CD=11680" in out          # 비밀이 아닌 파라미터는 그대로 보여야 디버깅이 된다


def test_masks_url_encoded_forms():
    """`%3D` · `%253D` 로 인코딩된 형태도 잡아야 한다 — 한 번 디코딩하면 원본이다."""
    encoded = quote(FAKE_KEY, safe="")
    for eq in ("=", "%3D", "%3d", "%253D"):
        text = f"for url 'https://apis.data.go.kr/x?serviceKey{eq}{encoded}&LAWD_CD=11680'"
        out = mask_secrets(text)
        assert_no_key(out)
        assert MASK in out


def test_masks_mapping_and_json_forms():
    assert_no_key(mask_secrets(str({"serviceKey": FAKE_KEY, "LAWD_CD": "11680"})))
    assert_no_key(mask_secrets(f'{{"serviceKey": "{FAKE_KEY}"}}'))
    assert_no_key(mask_secrets(f"{{'password': '{FAKE_KEY}'}}"))


def test_masks_bare_key_param_only_inside_query():
    assert_no_key(mask_secrets(f"https://x.example/a?key={FAKE_KEY}"))
    # 쿼리스트링이 아닌 'key=' 는 건드리지 않는다(로그를 못 읽게 만들지 않기 위해).
    assert mask_secrets("sort_key=name") == "sort_key=name"
    assert mask_secrets("primary key=id") == "primary key=id"


def test_masks_literal_secret_even_without_param_name():
    """파라미터 이름을 못 알아봐도 **값 자체**가 알려진 비밀이면 지운다."""
    text = f"redirected to https://evil.example/cb#{quote(FAKE_KEY, safe='')}"
    assert_no_key(mask_secrets(text, extra_secrets=(FAKE_KEY,)))


def test_masks_env_secret_values(monkeypatch):
    monkeypatch.setenv("MOLIT_API_KEY", FAKE_KEY)
    assert_no_key(mask_secrets(f"unexpected blob {FAKE_KEY} in body"))


def test_short_values_are_not_masked(monkeypatch):
    """짧은 값까지 지우면 로그가 못 읽게 된다 — 그리고 그런 값은 비밀로 쓰면 안 된다."""
    monkeypatch.setenv("MOLIT_API_KEY", "abc")
    assert mask_secrets("region abc kept") == "region abc kept"


def test_masking_keeps_non_secret_text_readable():
    text = "ingest molit_apt_trade → trade: status=partial ok=120 failed=3"
    assert mask_secrets(text) == text


# ---------------------------------------------------------------------------
# 2. fetch 계층 — 예외가 마스킹된 채로 올라온다
# ---------------------------------------------------------------------------

class _StubHttp:
    """`httpx` 모듈 대역. 실제 `httpx.Response.raise_for_status()` 를 쓴다 —
    예외 문자열 포맷을 우리가 흉내내면 테스트가 현실을 검증하지 못한다."""

    def __init__(self, status: int, body: str = "<error/>") -> None:
        self.status = status
        self.body = body

    def get(self, url, params=None, timeout=None):   # noqa: ANN001 - httpx 시그니처 흉내
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(self.status, request=request, text=self.body)


@pytest.mark.parametrize("status", [403, 500])
def test_raw_httpx_error_really_contains_the_key(status):
    """전제 확인 — 마스킹이 없으면 진짜로 샌다. 이게 거짓이면 이 테스트 묶음은 무의미하다."""
    stub = _StubHttp(status)
    resp = stub.get(MOLIT_ENDPOINT, params={"serviceKey": FAKE_KEY, "LAWD_CD": "11680"})
    with pytest.raises(httpx.HTTPStatusError) as caught:
        resp.raise_for_status()
    assert KEY_CORE in unquote(str(caught.value))


@pytest.mark.parametrize("status", [403, 500])
def test_fetch_wraps_http_error_without_the_key(status):
    fetch = make_http_fetch(client=_StubHttp(status))
    with pytest.raises(SecretSafeError) as caught:
        fetch({"serviceKey": FAKE_KEY, "LAWD_CD": "11680", "DEAL_YMD": "202506"})

    exc = caught.value
    assert_no_key(str(exc))
    assert exc.status_code == status          # 진단에 필요한 정보는 살아 있어야 한다
    assert "11680" in str(exc)
    # 원본 예외를 체인에 남기면 traceback 출력으로 키가 다시 새어 나온다.
    assert exc.__cause__ is None
    assert exc.__suppress_context__ is True


def test_fetch_masks_transport_errors_too():
    class _Boom:
        def get(self, url, params=None, timeout=None):   # noqa: ANN001
            raise httpx.ConnectError(
                f"failed to connect to {url}?serviceKey={quote(FAKE_KEY, safe='')}")

    fetch = make_http_fetch(client=_Boom())
    with pytest.raises(SecretSafeError) as caught:
        fetch({"serviceKey": FAKE_KEY, "LAWD_CD": "11680"})
    assert_no_key(str(caught.value))


def test_masked_error_is_not_double_wrapped():
    original = SecretSafeError("이미 안전함")
    assert masked_error(original).args[0].endswith("이미 안전함")


# ---------------------------------------------------------------------------
# 3. 유출 경로 L1 — runner.run.failures → stdout / 로그
# ---------------------------------------------------------------------------

def _run_ingest_with_failing_fetch(status: int = 403):
    fetch = make_http_fetch(client=_StubHttp(status))
    return run_molit_trade_ingest(
        service_key=FAKE_KEY,
        region_codes5=["11680"],
        months=["202506"],
        fetch=fetch,
        now=dt.datetime(2026, 7, 26, tzinfo=dt.timezone.utc),
        rate_limiter=RateLimiter(min_interval_sec=0.0, jitter_sec=0.0),
        log_sink=lambda run: None,
    )


def test_run_failures_carry_no_key():
    run = _run_ingest_with_failing_fetch()
    assert run.status == "failed"
    assert run.failures, "실패를 조용히 넘기면 안 된다"
    for where, why in run.failures:
        assert_no_key(f"{where}: {why}")
    assert_no_key(run.message)


def test_run_failures_carry_no_key_even_with_a_leaky_fetch():
    """주입된 fetch 가 마스킹을 안 해도 runner 가 막는다 — `service_key` 를 아는 계층이므로."""
    def leaky_fetch(params):
        raise RuntimeError(f"boom for url {MOLIT_ENDPOINT}?serviceKey={params['serviceKey']}")

    run = run_molit_trade_ingest(
        service_key=FAKE_KEY,
        region_codes5=["11680"],
        months=["202506"],
        fetch=leaky_fetch,
        now=dt.datetime(2026, 7, 26, tzinfo=dt.timezone.utc),
        rate_limiter=RateLimiter(min_interval_sec=0.0, jitter_sec=0.0),
        log_sink=lambda run: None,
    )
    for where, why in run.failures:
        assert_no_key(f"{where}: {why}")


def test_stdout_style_print_of_failures_carries_no_key(capsys):
    """`scripts/run_ingest.py` 가 하는 것과 같은 출력 — 운영에서 `/tmp/*.log` 로 간다."""
    run = _run_ingest_with_failing_fetch()
    for where, why in run.failures:
        print(f"       실패 {where}: {mask_secrets(why)}")
    assert_no_key(capsys.readouterr().out)


def test_default_log_sink_warning_carries_no_key(caplog):
    """`runner._default_log_sink` 는 **WARNING** 으로 찍는다 — 레벨 억제로는 못 막는다."""
    install_log_masking()
    from app.ingest.runner import _default_log_sink

    run = _run_ingest_with_failing_fetch()
    with caplog.at_level(logging.WARNING, logger="ingest.runner"):
        _default_log_sink(run)
    assert caplog.records, "실패는 반드시 로그에 남아야 한다"
    assert_no_key(caplog.text)


# ---------------------------------------------------------------------------
# 4. 유출 경로 L2 — probe → classify → verdict → region_code_verification.yaml
# ---------------------------------------------------------------------------

def _load_verify_region_codes():
    """`scripts/verify_region_codes.py` 를 모듈로 불러온다(패키지가 아니라 스크립트라서)."""
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(
        "_test_verify_region_codes", SCRIPTS_DIR / "verify_region_codes.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_verification_yaml_never_contains_the_key(tmp_path, capsys):
    """**커밋 대상 파일**에 키가 들어가지 않는다. 여기서 새면 git 이력에 영구 기록된다."""
    vrc = _load_verify_region_codes()
    fetch = make_http_fetch(client=_StubHttp(403))
    limiter = RateLimiter(min_interval_sec=0.0, jitter_sec=0.0)

    counts, err = vrc.probe(FAKE_KEY, "11680", ["202506"], fetch, limiter)
    assert err is not None, "API 오류를 조용히 삼키면 안 된다"
    assert_no_key(err)

    status, verdict = vrc.classify("11680", counts, err, {}, ["11680"])
    assert status == "error"
    assert_no_key(verdict)

    rows = [{"code": "11680", "sido": "서울특별시", "name": "강남구",
             "by_month": counts, "total": 0, "status": status, "verdict": verdict}]
    rendered = vrc.render(rows, ["202506"], dt.date(2026, 7, 26))
    assert_no_key(rendered)

    out = tmp_path / "region_code_verification.yaml"
    out.write_text(rendered, encoding="utf-8")
    assert_no_key(out.read_text(encoding="utf-8"))

    # 콘솔 출력(운영에서 로그 파일로 리다이렉트됨)도 같이 본다.
    print(f"  [  1/  1] 11680 강남구           ERR  {err}")
    assert_no_key(capsys.readouterr().out)


def test_render_masks_even_a_leaky_verdict():
    """싱크(파일 쓰기) 직전에도 한 번 더 지운다 — 이 산출물은 되돌릴 수 없다."""
    vrc = _load_verify_region_codes()
    rows = [{"code": "11680", "sido": "서울", "name": "강남구", "by_month": {}, "total": 0,
             "status": "error",
             "verdict": f"API 오류 — url {MOLIT_ENDPOINT}?serviceKey={FAKE_KEY}"}]
    assert_no_key(vrc.render(rows, ["202506"], dt.date(2026, 7, 26)))


def test_committed_verification_file_has_no_key():
    """현재 저장소에 이미 들어 있는 산출물도 확인한다(생성 시점이 언제든)."""
    path = BACKEND_DIR.parent / "config" / "region_code_verification.yaml"
    if not path.exists():
        pytest.skip("검증 파일이 아직 생성되지 않았습니다")
    text = path.read_text(encoding="utf-8")
    for marker in ("serviceKey=", "serviceKey%3D", "servicekey="):
        assert marker.lower() not in text.lower(), f"{path} 에 인증키 흔적이 있습니다"


# ---------------------------------------------------------------------------
# 5. 로깅 마지막 그물
# ---------------------------------------------------------------------------

def test_log_record_factory_masks_message_and_args(caplog):
    install_log_masking()
    logger = logging.getLogger("test.masking")
    with caplog.at_level(logging.WARNING, logger="test.masking"):
        logger.warning("실패 %s: %s", "11680:202506",
                       f"url {MOLIT_ENDPOINT}?serviceKey={FAKE_KEY}")
    assert_no_key(caplog.text)


def test_filter_masks_traceback_text():
    """`exc_info` 는 핸들러가 나중에 문자열로 만든다 — 필터가 미리 지워 둔다."""
    try:
        raise RuntimeError(f"url {MOLIT_ENDPOINT}?serviceKey={FAKE_KEY}")
    except RuntimeError:
        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "실패", None,
                                   sys.exc_info())
    SecretMaskingFilter().filter(record)
    assert record.exc_text is not None
    assert_no_key(record.exc_text)


def test_install_log_masking_is_idempotent():
    install_log_masking()
    factory = logging.getLogRecordFactory()
    install_log_masking()
    assert logging.getLogRecordFactory() is factory
    root = logging.getLogger()
    assert sum(isinstance(f, SecretMaskingFilter) for f in root.filters) == 1
