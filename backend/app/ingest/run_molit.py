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

from app.core.http import request_capped
from app.core.masking import masked_error
from app.ingest import molit
from app.ingest.loader import PostgisTradeLoader, RegionResolver
from app.ingest.ratelimit import RateLimiter
from app.ingest.runner import Fetcher, IngestRun, incremental_months, run_molit_trade_ingest

logger = logging.getLogger("ingest.run_molit")

#: 운영 엔드포인트. PM 이 발급 키로 실호출 검증(2026-07-25): 강남 202412 → 192건 파싱 성공.
#: ⚠️ Dev 엔드포인트(RTMSDataSvcAptTradeDev)는 이 키로 403 Forbidden — 개발계정 전용이다.
#:   발급받은 일반 인증키는 운영(RTMSDataSvcAptTrade)에서만 동작한다.
MOLIT_ENDPOINT = (
    "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
)


def make_http_fetch(endpoint: str = MOLIT_ENDPOINT, *, client: Any = None,
                    timeout: float = 20.0) -> Fetcher:
    """params → 응답 본문(text). httpx 클라이언트는 주입 가능(테스트용).

    공공데이터포털은 오류도 HTTP 200 으로 주므로, 여기서는 전송 계층 오류만 raise 하고
    결과코드 판정은 parse_response 가 한다(molit.py).

    ⚠️ SR17-1 — 이 함수는 **인증키를 아는 유일한 지점**이다(params 로 들어온다).
    `raise_for_status()` 가 던지는 `httpx.HTTPStatusError` 의 문자열에는 요청 URL 이
    통째로 들어가고, 그 URL 에는 `serviceKey=<인증키>` 가 실려 있다. 이 예외를 그대로
    올리면 호출부(runner → run.failures → stdout/YAML)가 키를 그대로 받아 적는다.
    그래서 **여기서 마스킹한 예외로 감싸 올린다.** 호출부가 기억해서 지우는 방식은
    한 곳만 빠져도 새기 때문에, 비밀을 가진 이 계층이 책임진다.
    """
    def fetch(params: dict[str, str]) -> str:
        c = client
        if c is None:
            import httpx
            c = httpx
        # 이 요청에 실린 실제 키도 리터럴로 넘긴다 — 파라미터 이름을 못 알아보는
        # 경로(리다이렉트 URL, 본문 echo 등)로 새도 값 자체가 지워진다.
        secrets = tuple(v for k, v in params.items()
                        if "key" in k.lower() or "token" in k.lower())
        try:
            # ⚠️ SR25-1 — 예전에는 `c.get(...).text` 였다. `.text` 는 `.content` 와
            #    똑같이 본문을 **전부 읽은 뒤** 문자열로 바꾼다. 이 코드는 worker
            #    컨테이너(mem_limit 192m) 안에서 도므로 상한 없는 읽기가 곧 OOM 경로다.
            #    `request_capped` 는 스트리밍으로 받으면서 세고, 넘으면 중단한다.
            resp, body = request_capped(c, "GET", endpoint, params=params,
                                        timeout=timeout, what="MOLIT 실거래")
        except Exception as exc:                 # noqa: BLE001 - 마스킹해 다시 올린다
            raise masked_error(exc, prefix="MOLIT 요청 실패: ",
                               extra_secrets=secrets) from None
        # 원천 인코딩을 존중한다(선언이 없으면 UTF-8). 여기서 틀리면 한글 단지명이
        # 조용히 깨져 들어간다 — 파싱은 되고 값만 이상해지는 형태다.
        enc = getattr(resp, "charset_encoding", None) or "utf-8"
        return body.decode(enc, errors="replace")

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
