"""국토부 실거래가 일일 수집 실행 배선 — fetch(HTTP)·load(PostGIS)·ingest_log 를 묶는다.

설계 근거: architecture.md §2.3(일 1회 야간 배치) · config/sources.yaml(molit_apt_trade)

★ MOLIT_API_KEY 는 사람이 발급한다(.env). 키가 없으면 run_molit_trade_ingest 가
  '가짜 성공' 대신 status=failed 로 기록한다(runner.py). 키가 오면 이 모듈이 그대로 돈다.

worker-ingest(큐, T7)가 스케줄에 맞춰 `run_daily` 를 호출하는 진입점이다.
"""
from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterable, Sequence
from typing import Any

from app.ingest import molit
from app.ingest.loader import PostgisTradeLoader, RegionResolver
from app.ingest.ratelimit import RateLimiter
from app.ingest.runner import Fetcher, IngestRun, incremental_months, run_molit_trade_ingest

logger = logging.getLogger("ingest.run_molit")

#: config/sources.yaml 의 molit_apt_trade.endpoint 와 일치. 서비스키 발급 시 상세페이지에서 최종 확인.
MOLIT_ENDPOINT = (
    "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
)


def make_http_fetch(endpoint: str = MOLIT_ENDPOINT, *, client: Any = None,
                    timeout: float = 20.0) -> Fetcher:
    """params → 응답 본문(text). httpx 클라이언트는 주입 가능(테스트용).

    공공데이터포털은 오류도 HTTP 200 으로 주므로, 여기서는 전송 계층 오류만 raise 하고
    결과코드 판정은 parse_response 가 한다(molit.py).
    """
    def fetch(params: dict[str, str]) -> str:
        c = client
        if c is None:
            import httpx
            c = httpx
        resp = c.get(endpoint, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.text

    return fetch


def postgis_log_sink(engine: Any):
    """IngestRun → ingest_log 한 행. 수집 실패를 조용히 넘기지 않기 위한 원장(erd.md)."""
    from sqlalchemy import text

    def sink(run: IngestRun) -> None:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO ingest_log (source, target_table, started_at, finished_at,
                                        rows_ok, rows_failed, status, message)
                VALUES (:source, :target_table, :started_at, :finished_at,
                        :rows_ok, :rows_failed, :status, :message)
            """), run.to_log_row())
        level = logging.INFO if run.status == "ok" else logging.WARNING
        logger.log(level, "ingest_log 기록: %s status=%s ok=%d failed=%d",
                   run.source, run.status, run.rows_ok, run.rows_failed)

    return sink


def run_daily(
    *,
    service_key: str,
    region_codes5: Sequence[str],
    engine: Any,
    today: dt.date,
    lookback_months: int = 1,
    region_resolver: RegionResolver | None = None,
    fetch: Fetcher | None = None,
    rate_limiter: RateLimiter | None = None,
    log_sink=None,
) -> IngestRun:
    """수도권 시군구·최근 (lookback+1)개월 실거래가를 수집·적재한다.

    반환 IngestRun.message 에 적재 결과(신규/갱신)를 덧붙인다.
    ⚠️ region_codes5 는 수도권 시군구 5자리 목록. region 마스터가 적재되면 거기서 파생,
       그전까지는 호출부가 목록을 넘긴다(현재 수도권 전 시군구 목록은 별도 준비 대상).
    """
    months = incremental_months(today, lookback_months=lookback_months)
    loader = PostgisTradeLoader(engine, region_resolver=region_resolver)
    now = dt.datetime.combine(today, dt.time(3, 0), tzinfo=dt.timezone.utc)

    run = run_molit_trade_ingest(
        service_key=service_key,
        region_codes5=region_codes5,
        months=months,
        fetch=fetch or make_http_fetch(),
        now=now,
        rate_limiter=rate_limiter,
        row_sink=loader.load,
        log_sink=log_sink or postgis_log_sink(engine),
    )
    # 적재 결과를 로그 메시지에 남긴다(파싱 성공 ≠ 신규 적재. 재수집이면 대부분 갱신).
    t = loader.totals
    run.message += (f" | 적재: 단지 {t.complexes_created} 신규, 타입 {t.unit_types_created} 신규, "
                    f"거래 {t.trades_inserted} 신규 / {t.trades_updated} 갱신")
    return run


def region_codes_from(sources: Iterable[str]) -> list[str]:
    """시군구 5자리 목록 정규화(공백 제거·유효성). 잘못된 코드는 조용히 버리지 않고 제외 로그."""
    out: list[str] = []
    for raw in sources:
        code = (raw or "").strip()
        if len(code) == 5 and code.isdigit():
            out.append(code)
        else:
            logger.warning("유효하지 않은 시군구 코드 제외: %r", raw)
    return out
