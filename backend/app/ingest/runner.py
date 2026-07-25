"""수집 실행 루프 — 국토부 실거래가 증분 수집.

설계 근거: docs/02-design/architecture.md §2.3(배치) · erd.md(ingest_log) · CHARTER §4(G4)
          · team/roles/re-data.md(수집 실패는 조용히 넘기지 말고 로그·알람)

이 모듈이 지키는 것
-------------------
1. **rate limit** — 요청 사이 최소 간격(RateLimiter). 공공API 일일 한도·차단 회피(가용성 요구).
2. **증분 수집** — 전체 재수집이 아니라 필요한 달(YYYYMM)만. 신고지연 30일 → 최근 N개월 재수집.
3. **ingest_log** — 성공/실패 건수와 상태를 반드시 남긴다. "조용한 실패"가 가장 위험하다.
4. **호가·실거래 분리** — 이 러너는 trade(실거래)만 적재한다. listing 은 다른 경로.

의존성 주입
-----------
`fetch`(HTTP), `row_sink`(DB 적재), `log_sink`(ingest_log 기록), 시계(RateLimiter)를 주입받아
네트워크·DB 없이 테스트한다. 기본값은 로깅/미적재(no-op)라 import 만으로 부작용이 없다.
실제 HTTP·DB 배선은 큐 워커(worker-ingest, T7 이후)에서 이 함수를 호출해 완성한다.
"""
from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from app.ingest import molit
from app.ingest.ratelimit import RateLimiter

logger = logging.getLogger("ingest.runner")

#: (params) -> 응답 본문 텍스트. 주입 안 하면 실행 시 명시적으로 실패한다.
Fetcher = Callable[[dict[str, str]], str]
#: 파싱된 레코드들을 받아 적재. 미주입 시 no-op(적재 안 함, 로그만).
RowSink = Callable[[Sequence[molit.MolitTrade]], None]
#: 완료된 IngestRun 을 ingest_log 에 기록. 미주입 시 로깅.
LogSink = Callable[["IngestRun"], None]


@dataclass
class IngestRun:
    """한 번의 수집 실행 결과 — erd.md 의 ingest_log 한 행에 대응."""

    source: str
    target_table: str
    started_at: dt.datetime
    finished_at: dt.datetime | None = None
    rows_ok: int = 0
    rows_failed: int = 0
    status: str = "running"          # ok | partial | failed | running
    message: str = ""
    #: 실패한 달(YYYYMM)과 사유 — 조용히 넘기지 않기 위해 남긴다
    failures: list[tuple[str, str]] = field(default_factory=list)

    def to_log_row(self) -> dict[str, object]:
        return {
            "source": self.source,
            "target_table": self.target_table,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "rows_ok": self.rows_ok,
            "rows_failed": self.rows_failed,
            "status": self.status,
            "message": self.message,
        }


def incremental_months(today: dt.date, *, lookback_months: int) -> list[str]:
    """오늘 기준 최근 (lookback_months+1) 개월의 YYYYMM 목록.

    신고지연(최대 30일)을 흡수하려면 당월만이 아니라 이전 달도 다시 받아야 한다.
    """
    if lookback_months < 0:
        raise ValueError("lookback_months 는 0 이상")
    start_year = today.year
    start_month = today.month - lookback_months
    while start_month <= 0:
        start_month += 12
        start_year -= 1
    return molit.months_between(dt.date(start_year, start_month, 1), today)


def _default_log_sink(run: IngestRun) -> None:
    level = logging.INFO if run.status == "ok" else logging.WARNING
    logger.log(level, "ingest %s → %s: status=%s ok=%d failed=%d %s",
               run.source, run.target_table, run.status,
               run.rows_ok, run.rows_failed, run.message)
    for ym, why in run.failures:
        logger.warning("  실패 %s: %s", ym, why)


def run_molit_trade_ingest(
    *,
    service_key: str,
    region_codes5: Iterable[str],
    months: Sequence[str],
    fetch: Fetcher,
    now: dt.datetime,
    rate_limiter: RateLimiter | None = None,
    row_sink: RowSink | None = None,
    log_sink: LogSink = _default_log_sink,
    rows_per_page: int = 1000,
) -> IngestRun:
    """지정한 시군구·달에 대해 실거래가를 수집·적재하고 ingest_log 를 남긴다.

    개별 (지역,달) 이 깨져도 전체를 중단하지 않되, **조용히 넘기지 않고** 실패로 집계한다.
    한 건이라도 성공하고 일부 실패면 status=partial, 전부 실패면 failed.
    """
    if not service_key:
        # 키가 없으면 도는 척하지 않고 즉시 실패로 남긴다(가짜 성공 금지).
        run = IngestRun(source=molit.SOURCE_NAME, target_table="trade",
                        started_at=now, finished_at=now, status="failed",
                        message="MOLIT_API_KEY 미설정 — .env 에서 주입 필요")
        log_sink(run)
        return run

    limiter = rate_limiter or RateLimiter(min_interval_sec=0.5, jitter_sec=0.3)
    run = IngestRun(source=molit.SOURCE_NAME, target_table="trade", started_at=now)
    attempted = 0

    # INGEST-1: 적재(row_sink)까지 try 안에서 처리하고, log_sink 는 finally 로 옮긴다.
    # 적재가 실패해도 예외가 새어 루프를 죽이면 안 되고(다른 지역·달은 계속돼야 한다),
    # 무엇보다 **어떤 경우에도 ingest_log 는 남아야** 한다 — '조용한 실패'가 가장 위험하다.
    try:
        for region in region_codes5:
            for ym in months:
                attempted += 1
                limiter.wait()                  # rate limit — 예의가 아니라 가용성
                try:
                    params = molit.build_params(
                        service_key=service_key, region_code5=region, ym=ym,
                        rows=rows_per_page)
                    body = fetch(params)
                    trades = molit.parse_response(body, now=now)
                    if row_sink is not None:
                        row_sink(trades)         # 적재 실패도 이 배치의 실패로 잡힌다
                    run.rows_ok += len(trades)
                except molit.MolitParseError as exc:
                    run.rows_failed += 1
                    run.failures.append((f"{region}:{ym}", f"파싱 실패: {exc}"))
                except Exception as exc:        # 네트워크·적재 등 — 실패로 남기고 계속
                    run.rows_failed += 1
                    run.failures.append((f"{region}:{ym}", f"수집/적재 실패: {exc}"))

        if run.rows_failed == 0:
            run.status = "ok"
        elif run.rows_ok > 0 or run.rows_failed < attempted:
            run.status = "partial"
        else:
            run.status = "failed"
        run.message = f"{attempted}개 (지역·달) 시도, 실패 {len(run.failures)}건"
    finally:
        # 루프 밖에서 예기치 못한 예외가 나도 원장은 반드시 남긴다.
        run.finished_at = now
        if run.status == "running":
            run.status = "failed"
            run.message = run.message or f"{attempted}개 시도 중 예기치 못한 중단"
        log_sink(run)
    return run
