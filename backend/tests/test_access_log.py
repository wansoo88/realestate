"""접근 로그에 **쿼리스트링 값이 남지 않는가** — 세 싱크 전부 (★ SR32-1).

왜 이 파일이 따로 있나
----------------------
`SR31-4` 는 앱 미들웨어에서 `/me/listings` 의 쿼리를 지웠다. 코드만 보면 닫힌
결함이었다. 그런데 리뷰어가 **실제로 uvicorn 을 띄워** 로그를 꺼내 보니, 앱이 방금
지운 바로 그 요청을 uvicorn 이 한 줄 아래에 쿼리째 다시 쓰고 있었다:

    INFO: 127.0.0.1:51891 - "GET /api/v1/me/listings?complex_id=1234 HTTP/1.1" 200 OK

그 옆줄에는 `/map/complexes?…&max_price_krw=1314310000` 이 있었다 — AES-256-GCM 으로
암호화해 보관하는 자산·소득·대출을 **복호화해 계산한 최대 구매가능 금액**이다.
운영 nginx 로그에 148줄, 그중 101줄이 0644(월드 리더블)였고 동거 계정으로 실제
읽혔다(CWE-532).

그래서 이 파일은 **함수를 부르는 것으로 끝내지 않는다.** 마지막 테스트는 진짜
uvicorn 프로세스를 띄워 요청을 쏘고, 그 프로세스가 실제로 찍은 로그를 검사한다.
"세 싱크" 중 nginx 는 설정 파일이라 `test_deploy_config.py` 가 맡는다.
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"

#: 로그 어디에도 나오면 안 되는 값. 실제 사고에서 나온 숫자를 그대로 쓴다.
CANARY = "1314310000"


@pytest.fixture(autouse=True)
def _app_env(monkeypatch):
    """`app.main` 은 import 시점에 `create_app()` 을 부른다 — 설정이 먼저 있어야 한다."""
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "k" * 32)
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    monkeypatch.setenv("TAX_RULES_PATH", str(FIXTURES / "tax_rules_test.yaml"))

    from app.core.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 1. 앱 미들웨어 — 값이 아니라 이름만 남긴다
# ---------------------------------------------------------------------------

def test_log_target_은_값을_남기지_않는다():
    from app.main import log_target

    got = log_target("/api/v1/map/complexes", f"bbox=126.9,37.4&max_price_krw={CANARY}")
    assert got == "/api/v1/map/complexes [q: bbox,max_price_krw]"
    assert CANARY not in got


def test_log_target_은_이름_자리의_값도_버린다():
    from app.main import log_target

    got = log_target("/api/v1/map/complexes", f"{CANARY}=1&a@b.co=2&zoom=15")
    assert CANARY not in got and "a@b.co" not in got
    assert "zoom" in got and "+2" in got


def test_쿼리가_없으면_경로만_남는다():
    from app.main import log_target

    assert log_target("/api/v1/health", "") == "/api/v1/health"


# ---------------------------------------------------------------------------
# 2. uvicorn.access — 필터가 **실제 로거에** 걸려 있는가
# ---------------------------------------------------------------------------

def test_마스킹_설치가_uvicorn_접근로거에_필터를_건다():
    """`install_log_masking()` 하나만 부르면 접근 로그 방어도 함께 걸린다.

    변이: `install_log_masking` 안의 `install_access_log_query_stripping()` 호출을
    지우면 여기서 깨진다. (`worker.py`·`scripts/_common.py` 도 이 함수만 부른다 —
    두 곳에서 각각 부르게 하면 언젠가 한쪽만 부르는 진입점이 생긴다.)
    """
    from app.core.masking import AccessLogQueryFilter, install_log_masking

    access = logging.getLogger("uvicorn.access")
    access.filters = [f for f in access.filters
                      if not isinstance(f, AccessLogQueryFilter)]

    install_log_masking()

    assert any(isinstance(f, AccessLogQueryFilter) for f in access.filters)
    # 멱등: 두 번 불러도 필터가 쌓이지 않는다.
    install_log_masking()
    assert sum(1 for f in access.filters if isinstance(f, AccessLogQueryFilter)) == 1


def test_uvicorn_이_찍는_그_줄에서_쿼리가_사라진다(caplog):
    """uvicorn 의 **실제 포맷터·실제 인자 모양**으로 한 줄을 찍어 본다.

    uvicorn 0.49 의 호출부(`httptools_impl.py`):
        access_logger.info('%s - "%s %s HTTP/%s" %d',
                           client_addr, method, get_path_with_query_string(scope),
                           http_version, status_code)
    """
    from uvicorn.logging import AccessFormatter

    from app.core.masking import install_access_log_query_stripping

    install_access_log_query_stripping()
    logger = logging.getLogger("uvicorn.access")

    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append           # type: ignore[method-assign]
    logger.addHandler(handler)
    # uvicorn 은 기동 시 dictConfig 로 이 로거를 INFO 로 올린다. 테스트에서는 그
    # 설정이 없으므로 같은 조건을 만들어 준다(안 하면 레벨에서 걸려 필터가 안 돈다).
    previous = logger.level
    logger.setLevel(logging.INFO)
    try:
        logger.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:51891", "GET",
                    f"/api/v1/map/complexes?bbox=126.9&max_price_krw={CANARY}",
                    "1.1", 200)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)

    assert records, "레코드가 만들어지지 않았다"
    line = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s',
                           use_colors=False).format(records[0])
    assert CANARY not in line, line
    assert "/api/v1/map/complexes" in line, "경로는 남아야 한다"
    assert "?" not in line


def test_인자가_뭉개진_레코드에서도_쿼리를_지운다():
    """**두 번째 그물.** 비밀 마스킹이 레코드를 통째로 대체하면 인자가 사라진다
    (비밀이 템플릿 쪽에 있을 때는 구조를 지킬 방법이 없다). 그때는 이미 완성된
    문자열 안에서 경로+쿼리를 찾아 자른다.

    변이: `AccessLogQueryFilter.filter` 의 `record.msg` 처리 줄을 지우면 여기서 깨진다.
    (첫 번째 그물이 살아 있는 한 실제 서버 로그로는 관측되지 않는 층이라, 이 단위
     테스트가 없으면 그 줄은 아무 테스트에도 걸리지 않는다 — 변이 M14 실측.)
    """
    from app.core.masking import AccessLogQueryFilter

    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        f'127.0.0.1:5189 - "GET /api/v1/map/complexes?max_price_krw={CANARY} HTTP/1.1" 200',
        (), None)
    AccessLogQueryFilter().filter(record)

    assert CANARY not in record.getMessage(), record.getMessage()
    assert "/api/v1/map/complexes" in record.getMessage()
    assert 'HTTP/1.1" 200' in record.getMessage(), "경로 뒤 정보는 살아 있어야 한다"


def test_필터가_모르는_모양의_레코드는_건드리지_않는다():
    """uvicorn 이 인자 모양을 바꿔도 로깅을 깨뜨리지 않는다(로그가 앱을 죽이면 안 된다)."""
    from app.core.masking import AccessLogQueryFilter

    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1,
                               "%s %s", ("GET", "no-query-here"), None)
    assert AccessLogQueryFilter().filter(record) is True
    assert record.args == ("GET", "no-query-here")


# ---------------------------------------------------------------------------
# 3. ★ 진짜 uvicorn 프로세스 — 코드가 아니라 **로그 파일**을 본다
# ---------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def live_server():
    """실제 `uvicorn app.main:app` 프로세스. 인메모리 리포지토리(DEBUG)로 뜬다."""
    port = _free_port()
    env = {
        **os.environ,
        "JWT_SECRET": "x" * 40,
        "FIELD_ENCRYPTION_KEY": "k" * 32,
        "TAX_RULES_PATH": str(FIXTURES / "tax_rules_test.yaml"),
        "DEBUG": "true",
        # DB 설정을 비워야 인메모리로 뜬다(factory.build_repository).
        "POSTGRES_USER": "", "POSTGRES_PASSWORD": "",
        "PYTHONPATH": str(BACKEND_ROOT),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(BACKEND_ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            if proc.poll() is not None:
                raise AssertionError("uvicorn 이 곧바로 종료됐다:\n"
                                     + (proc.stdout.read() if proc.stdout else ""))
            try:
                if httpx.get(f"{base}/api/v1/health", timeout=1.0).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            proc.kill()
            raise AssertionError("uvicorn 이 30초 안에 뜨지 않았다")
        yield base, proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - 방어
            proc.kill()


def test_실제_uvicorn_접근로그에_쿼리_값이_남지_않는다(live_server):
    """★ 이 파일의 본론. **코드를 읽지 않고 로그를 읽는다.**

    변이: `install_log_masking()` 에서 `install_access_log_query_stripping()` 를 빼면
    uvicorn 이 `"GET /api/v1/health?max_price_krw=1314310000 HTTP/1.1"` 을 그대로 찍어
    여기서 깨진다(실측으로 확인).
    """
    base, proc = live_server

    # 인증 없이 닿는 경로로 쏜다 — 검사 대상은 응답이 아니라 **로그 줄**이다.
    httpx.get(f"{base}/api/v1/health",
              params={"max_price_krw": CANARY, "bbox": "126.9,37.4,127.1,37.6"},
              timeout=5.0)
    # 인증 경로에도 한 번(401 이어도 접근 로그는 남는다).
    httpx.get(f"{base}/api/v1/map/complexes",
              params={"budget": "mine", "zoom": 15}, timeout=5.0)
    # ⚠️ **비밀처럼 생긴 이름**을 일부러 하나 섞는다. 비밀 마스킹이 레코드를 뭉개면
    #    uvicorn 의 AccessFormatter 가 인자 언패킹에 실패해 logging 폴백이
    #    **원본 메시지를 통째로** 찍는다 — 지우려던 방어가 포맷을 무너뜨려 새는 형태다.
    httpx.get(f"{base}/api/v1/me/listings",
              params={"complex_id": 1234, "secret": CANARY}, timeout=5.0)

    proc.terminate()
    out, _ = proc.communicate(timeout=15)

    assert "/api/v1/health" in out, f"접근 로그 자체가 없다:\n{out}"
    assert CANARY not in out, f"쿼리 값이 uvicorn 접근 로그에 남았다:\n{out}"
    assert "complex_id=1234" not in out, out
    assert "Logging error" not in out, (
        "logging 이 폴백으로 원본 메시지를 찍었다 — 그 줄에는 쿼리가 들어 있다:\n" + out)
    request_lines = [ln for ln in out.splitlines() if '"GET /api/v1' in ln]
    assert len(request_lines) >= 3, f"요청 줄이 모자란다:\n{out}"
    for line in request_lines:
        assert "?" not in line, f"접근 로그 줄에 쿼리가 남았다: {line}"
