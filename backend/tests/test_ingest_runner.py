"""수집 실행 루프·robots 게이트 테스트 (네트워크·DB 없이).

핵심 검증: **수집 실패를 조용히 넘기지 않는다**(ingest_log 기록) · rate limit 적용 ·
          robots 불확실 시 fail-closed(거부).
"""
from __future__ import annotations

import datetime as dt

from app.ingest import molit
from app.ingest.ratelimit import RateLimiter
from app.ingest.robots import RobotsGate
from app.ingest.runner import (
    IngestRun,
    incremental_months,
    run_molit_trade_ingest,
)

NOW = dt.datetime(2026, 7, 25, 3, 0, tzinfo=dt.timezone.utc)

# 최소한의 정상 응답(항목 1건). molit.parse_response 가 읽을 수 있는 형태.
_OK_XML = """<response><header><resultCode>00</resultCode></header><body><items>
<item><거래금액> 82,500</거래금액><년>2026</년><월>7</월><일>3</일>
<아파트>테스트단지</아파트><전용면적>84.97</전용면적><지역코드>11680</지역코드>
<층>10</층><건축년도>2015</건축년도></item>
</items></body></response>"""


def _fake_limiter(sleeps: list[float]) -> RateLimiter:
    """실제로 안 자고, 잔 시간만 기록하는 RateLimiter."""
    t = [0.0]

    def clock() -> float:
        return t[0]

    def sleeper(sec: float) -> None:
        sleeps.append(sec)
        t[0] += sec

    return RateLimiter(min_interval_sec=0.5, clock=clock, sleeper=sleeper)


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

def test_키없으면_가짜성공대신_실패로_기록한다():
    logged: list[IngestRun] = []
    run = run_molit_trade_ingest(
        service_key="", region_codes5=["11680"], months=["202607"],
        fetch=lambda p: _OK_XML, now=NOW, log_sink=logged.append)
    assert run.status == "failed"
    assert "MOLIT_API_KEY" in run.message
    assert logged and logged[0].status == "failed"


def test_정상수집은_행수를_세고_rate_limit_적용():
    sleeps: list[float] = []
    rows: list[int] = []
    run = run_molit_trade_ingest(
        service_key="KEY", region_codes5=["11680", "11650"], months=["202606", "202607"],
        fetch=lambda p: _OK_XML, now=NOW,
        rate_limiter=_fake_limiter(sleeps),
        row_sink=lambda trades: rows.append(len(trades)),
        log_sink=lambda r: None)
    assert run.status == "ok"
    assert run.rows_ok == 4              # 2지역 × 2달 × 1건
    assert run.rows_failed == 0
    # 4회 요청 중 첫 요청 뒤부터 rate limit 이 최소 3회 개입
    assert len([s for s in sleeps if s > 0]) >= 3


def test_일부실패는_partial이고_조용히_넘어가지_않는다():
    def flaky(params: dict) -> str:
        if params["DEAL_YMD"] == "202606":
            raise ConnectionError("타임아웃")
        return _OK_XML

    logged: list[IngestRun] = []
    run = run_molit_trade_ingest(
        service_key="KEY", region_codes5=["11680"], months=["202606", "202607"],
        fetch=flaky, now=NOW, rate_limiter=_fake_limiter([]),
        log_sink=logged.append)
    assert run.status == "partial"
    assert run.rows_ok == 1
    assert run.rows_failed == 1
    assert run.failures and "202606" in run.failures[0][0]   # 실패가 남는다
    assert logged and logged[0].failures                     # ingest_log 에도 남는다


def test_전부_파싱실패면_failed():
    run = run_molit_trade_ingest(
        service_key="KEY", region_codes5=["11680"], months=["202607"],
        fetch=lambda p: "<broken", now=NOW, rate_limiter=_fake_limiter([]),
        log_sink=lambda r: None)
    assert run.status == "failed"
    assert run.rows_ok == 0


def test_적재실패도_조용히_넘기지_않고_로그를_남긴다():
    """★INGEST-1: row_sink(적재) 예외가 새어 루프를 죽이거나 ingest_log 를 건너뛰면 안 된다."""
    def boom(trades):
        raise RuntimeError("DB 적재 실패")

    logged: list[IngestRun] = []
    run = run_molit_trade_ingest(
        service_key="KEY", region_codes5=["11680"], months=["202606"],
        fetch=lambda p: _OK_XML, now=NOW, rate_limiter=_fake_limiter([]),
        row_sink=boom, log_sink=logged.append)

    assert run.status == "failed"            # 적재 실패 = 실패(가짜 성공 아님)
    assert run.rows_ok == 0
    assert run.failures and "적재" in run.failures[0][1]
    assert logged and logged[0].status == "failed"   # ingest_log 는 반드시 남는다(finally)


def test_한_배치_적재실패가_다른_배치를_막지_않는다():
    """INGEST-1: 적재 예외가 루프를 죽이면 뒤 지역·달이 통째로 유실된다."""
    calls = [0]

    def flaky_sink(trades):
        calls[0] += 1
        if calls[0] == 1:
            raise RuntimeError("일시 적재 실패")

    logged: list[IngestRun] = []
    run = run_molit_trade_ingest(
        service_key="KEY", region_codes5=["11680"], months=["202605", "202606"],
        fetch=lambda p: _OK_XML, now=NOW, rate_limiter=_fake_limiter([]),
        row_sink=flaky_sink, log_sink=logged.append)

    assert calls[0] == 2                     # 첫 배치가 터져도 둘째 배치를 시도한다
    assert run.status == "partial"
    assert run.rows_ok == 1 and run.rows_failed == 1
    assert logged and logged[0].status == "partial"


# ---------------------------------------------------------------------------
# 페이지네이션 — 1000건 넘는 시군구·달이 조용히 잘리면 안 된다
# (실측 2026-07-25: 화성시 동탄구 202605 totalCount=1411)
# ---------------------------------------------------------------------------

def _xml(items: int, total: int) -> str:
    body = "".join(
        "<item><거래금액> 82,500</거래금액><년>2026</년><월>7</월>"
        f"<일>{i % 28 + 1}</일><아파트>테스트단지</아파트><전용면적>84.97</전용면적>"
        "<지역코드>41597</지역코드><층>10</층></item>"
        for i in range(items)
    )
    return ("<response><header><resultCode>00</resultCode></header><body><items>"
            f"{body}</items><totalCount>{total}</totalCount></body></response>")


def test_1000건_넘는_달은_페이지를_돌아_전부_받는다():
    """★ 1페이지만 받으면 411건이 오류 없이 사라진다 — 200 OK · resultCode 00 이라 아무도 모른다."""
    seen_pages: list[str] = []

    def fetch(params: dict) -> str:
        seen_pages.append(params["pageNo"])
        return _xml(10, 25) if params["pageNo"] != "3" else _xml(5, 25)

    run = run_molit_trade_ingest(
        service_key="KEY", region_codes5=["41597"], months=["202605"],
        fetch=fetch, now=NOW, rate_limiter=_fake_limiter([]),
        log_sink=lambda r: None, rows_per_page=10)

    assert seen_pages == ["1", "2", "3"]
    assert run.rows_ok == 25                 # 10 + 10 + 5
    assert run.status == "ok"


def test_총건수를_못채우면_성공으로_기록하지_않는다():
    """잘린 데이터를 status=ok 로 남기면 '조용한 결측'이 그대로 굳는다."""
    run = run_molit_trade_ingest(
        service_key="KEY", region_codes5=["41597"], months=["202605"],
        fetch=lambda p: _xml(0, 500) if p["pageNo"] == "2" else _xml(10, 500),
        now=NOW, rate_limiter=_fake_limiter([]),
        log_sink=lambda r: None, rows_per_page=10)

    assert run.status == "failed"
    assert any("500" in why for _, why in run.failures)


def test_totalCount가_없으면_덜찬_페이지가_끝_신호():
    """구버전 응답 호환 — totalCount 가 없어도 무한 루프에 빠지지 않는다."""
    run = run_molit_trade_ingest(
        service_key="KEY", region_codes5=["11680"], months=["202607"],
        fetch=lambda p: _OK_XML, now=NOW, rate_limiter=_fake_limiter([]),
        log_sink=lambda r: None, rows_per_page=1000)
    assert run.status == "ok" and run.rows_ok == 1


def test_증분_월목록은_신고지연_흡수용_이전달을_포함():
    months = incremental_months(dt.date(2026, 7, 25), lookback_months=1)
    assert months == ["202606", "202607"]
    # 연초 경계
    assert incremental_months(dt.date(2026, 1, 10), lookback_months=2) == \
        ["202511", "202512", "202601"]


# ---------------------------------------------------------------------------
# robots 게이트
# ---------------------------------------------------------------------------

_ROBOTS = """User-agent: *
Disallow: /private
Crawl-delay: 3
"""


def test_robots_허용경로는_통과하고_crawl_delay를_읽는다():
    gate = RobotsGate("pjt13-realestate/0.1", fetcher=lambda u: _ROBOTS)
    d = gate.check("https://example.com/public/list")
    assert d.allowed is True
    assert d.crawl_delay_sec == 3.0


def test_robots_금지경로는_거부한다():
    gate = RobotsGate("pjt13-realestate/0.1", fetcher=lambda u: _ROBOTS)
    assert gate.check("https://example.com/private/secret").allowed is False


def test_robots_못읽으면_fail_closed로_거부():
    gate = RobotsGate("pjt13-realestate/0.1", fetcher=lambda u: None)
    d = gate.check("https://example.com/anything")
    assert d.allowed is False
    assert "거부" in d.reason
