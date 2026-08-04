"""자기 채점(백테스트) 실행기 — **읽기 전용 SELECT 만 한다.**

설계 정본: `docs/02-design/backtest.md` (§8 실행)

무엇을 하는가
-------------
과거 시점 `T` 로 시계를 되돌려 **그때 알 수 있었던 것만으로** (단지, 면적대) 후보에
점수를 매기고, `T+12개월` 실현 수익률을 벤치마크·무작위 대조군과 비교한다.

⚠️ 결과를 읽기 전에 알아야 하는 것
----------------------------------
학군·교통·생활인프라(현행 총점 가중치의 **55%**)는 과거 상태를 알 방법이 없어
채점 대상에서 **제외**했다. 이 스크립트가 재는 것은 시변 축 셋(가격매력·환금성·
가격추세, 합 0.45)뿐이다. 근거는 문서 §2-F.

그리고 **하락기 폴드가 없으면 결과를 '검증됨'이라 부르지 않는다**(§4-C).
상승장에서는 아무거나 사도 오르기 때문이다. `verdict=rising_only` 로 나온다.

운영 DB 예의 (mem_limit 192MB · 디스크 92% · 서버 가용 261MB)
------------------------------------------------------------
`build_market_index.py` 와 같은 규칙을 따른다 — 시군구 단위로 나눠 읽고, 세션
`statement_timeout`·`work_mem` 을 명시하고, 지역 사이에 잠깐 쉰다. 쓰기는 없다.

⚠️ **거래를 리스트로 접지 않는다.** 예전 판은 `list(repo.trades_for_backtest(...))` 였고,
   그 한 줄이 첫 실행 예시에서만 613,228행 ≈ **235MB** 였다(가용 261MB 의 90%).
   지금은 `FoldCollector` 가 청크(기본 5,000행)로 끊어 읽으며 셀별 ₩/㎡ 값만 남긴다.
   근거와 버린 대안은 `app/domain/backtest/collect.py` 머리주석 · `backtest.md §5-1`.
   ⚠️ 상한은 **2 × chunk_rows** 다(청크 + 그 as-of 뷰 — 동 마스킹으로 사본이 생긴다 · CR50-1).
   ⚠️ 그리고 그건 **파이썬 객체**의 상한이다. 드라이버 버퍼는 `stream_results` 로 따로
      막는다(CR50-2 · `PostgresBacktestRepository` 주석 · `backtest.md §7-13`).

사용
----
    export DATABASE_URL=postgresql+psycopg://user:pw@host:5432/realestate
    python scripts/run_backtest.py --as-of 2025-01-31 --dry-run        # 데이터 범위만 확인
    python scripts/run_backtest.py --as-of 2025-01-31 --top-n 30
    python scripts/run_backtest.py --folds 2022-01-31,2022-07-31,2023-01-31 \
        --scorer current_weights --json out.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import time
from collections.abc import Iterable, Iterator, Sequence

# ⚠️ `_common` 을 먼저 import 한다 — import 부작용으로 backend 가 sys.path 에 붙고
#    로깅 억제·비밀 마스킹이 설치된다(SR17-3). 아래 app.* import 가 여기에 기댄다.
from _common import load_env, make_engine, safe_dsn

from app.domain.backtest.asof import (  # noqa: E402
    REPORT_LAG_DAYS,
    CancellationPolicy,
)
from app.domain.backtest.collect import (  # noqa: E402
    DEFAULT_CHUNK_ROWS,
    DEFAULT_MAX_SAMPLES,
    FoldCollector,
)
from app.domain.backtest.engine import (  # noqa: E402
    DEFAULT_NULL_DRAWS,
    DEFAULT_RNG_SEED,
    DEFAULT_TOP_N,
    BacktestReport,
    fold_row,
    run_fold,
    summarize,
)
from app.domain.backtest.models import (  # noqa: E402
    DEFAULT_HORIZON_MONTHS,
    DEFAULT_WINDOW_MONTHS,
    MIN_TRADES_PER_ENDPOINT,
    BacktestTrade,
    FoldSpec,
)
from app.domain.backtest.outcome import MIN_PEER_CELLS, UnmeasuredPolicy  # noqa: E402
from app.domain.backtest.scorers import (  # noqa: E402
    AXIS_LIQUIDITY,
    AXIS_PRICE_ATTRACTIVENESS,
    AXIS_PRICE_TREND,
    constant_scorer,
    random_scorer,
    single_axis_scorer,
    universe_axis_summary,
    weighted_scorer,
)

log = logging.getLogger("run_backtest")

#: 세션 가드. 서버 기본값에 기대지 않는다(`build_market_index.py` 와 같은 이유·같은 값).
#:
#: ⚠️ 앞의 두 줄은 **읽기 전용을 DB 가 강제하게** 만든다(SR45-6). 순서가 중요하다:
#:   · `SET TRANSACTION READ ONLY` 는 **지금 이 트랜잭션**에 걸린다. 첫 질의 전에 와야 한다.
#:   · `SET default_transaction_read_only` 는 **다음 트랜잭션부터**다 — 이 줄만 있으면
#:     정작 지금 도는 트랜잭션은 여전히 쓰기가 가능하다. 그래서 둘 다 건다.
#: 우회 시도는 `ERROR: cannot execute INSERT in a read-only transaction` 으로 죽는다.
#: ⛔ 그래도 **정본은 읽기 전용 role** 이다. 이건 세션 설정이라 같은 연결에서 누군가
#:    `SET default_transaction_read_only = off` 를 부르면 풀린다. 운영 `DATABASE_URL` 의
#:    쓰기 권한 자체는 그대로다(`backtest.md §7-14`).
SESSION_GUARDS = ("SET TRANSACTION READ ONLY",
                  "SET default_transaction_read_only = on",
                  "SET statement_timeout = '120s'", "SET work_mem = '4MB'")

#: 가드가 **실제로 걸렸는지** DB 에 되묻는 한 줄. 철자가 아니라 효과를 본다.
READ_ONLY_PROBE = "SHOW transaction_read_only"

#: `SET TRANSACTION READ ONLY` 는 **트랜잭션 블록 안**에서만 뜻이 있다. AUTOCOMMIT 이면
#: 경고만 내고 무효다 — 첫 줄이 조용히 사라지는데 검사는 초록으로 남는다(CR50-6).
AUTOCOMMIT_REFUSED = (
    "이 연결이 AUTOCOMMIT 입니다 — `SET TRANSACTION READ ONLY` 는 트랜잭션 블록 안에서만 "
    "뜻이 있어서 첫 가드가 조용히 무효가 됩니다(backtest.md §7-14 · CR50-6). "
    "백테스트는 읽기 전용 전제 위에서만 돌립니다. isolation_level 을 되돌리거나 "
    "읽기 전용 role 로 접속하세요.")

READ_ONLY_NOT_IN_EFFECT = (
    "세션 가드를 걸었는데도 DB 가 transaction_read_only={} 라고 답했습니다 — "
    "읽기 전용 전제가 깨졌습니다. 이 상태로는 돌리지 않습니다(CR50-6).")


def apply_session_guards(conn) -> None:
    """세션 가드를 걸고 **효과를 확인한다.**

    두 단계다:
      ① **전제 검사** — AUTOCOMMIT 이면 거부한다. 그 모드에서는 `SET TRANSACTION READ ONLY`
         가 아무 일도 안 하는데, 상수 튜플의 순서만 보는 검사는 그대로 초록이다.
      ② **효과 검사** — 가드를 건 뒤 `SHOW transaction_read_only` 로 DB 에 직접 되묻는다.
         전제가 어떤 이유로 깨지든(연결 설정·서버 기본값·누군가의 `SET … = off`)
         여기서 걸린다. 정적 토큰 검사가 못 하는 일이 정확히 이것이다.
    """
    from sqlalchemy import text

    options = {**conn.engine.get_execution_options(), **conn.get_execution_options()}
    if str(options.get("isolation_level") or "").upper() == "AUTOCOMMIT":
        raise RuntimeError(AUTOCOMMIT_REFUSED)

    for guard in SESSION_GUARDS:
        conn.execute(text(guard))

    actual = conn.execute(text(READ_ONLY_PROBE)).scalar()
    if str(actual).strip().lower() not in ("on", "true", "t", "1"):
        raise RuntimeError(READ_ONLY_NOT_IN_EFFECT.format(actual))

#: 시군구 사이 휴식(초). 배치가 API 컨테이너의 숨통을 막지 않게.
PAUSE_SEC = 0.4

#: 지역 코드 접두 → 시도. 서비스 범위는 수도권이다(CLAUDE.md).
SIDO_PREFIXES = ("11", "41", "28")

#: 거래 조회. **파라미터 바인딩만** 쓴다(문자열 조립 금지).
#:
#: ⚠️ `is_cancelled` 로 거르지 않는다. 해제 정책은 도메인이 정한다
#:    (`repository.py` 의 금지 목록 참조). 여기서 미리 거르면 `INCLUDE_ALL` 이 무력화된다.
_TRADES_SQL = """
SELECT t.complex_id,
       t.contract_date,
       t.price_krw,
       t.area_m2,
       c.region_code,
       t.is_cancelled,
       t.registered_at,
       t.apt_dong,
       t.floor
FROM trade t
JOIN complex c ON c.id = t.complex_id
WHERE t.contract_date BETWEEN :start AND :end
  AND t.area_m2 > 0
  AND left(c.region_code, :plen) = :region
ORDER BY t.contract_date, t.complex_id
"""

_SIGUNGU_SQL = """
SELECT DISTINCT left(region_code, 5) AS code
FROM complex
WHERE region_code IS NOT NULL
  AND left(region_code, 2) = ANY(:sidos)
ORDER BY 1
"""

_HOUSEHOLDS_SQL = """
SELECT id, total_households
FROM complex
WHERE left(region_code, :plen) = :region
"""


class PostgresBacktestRepository:
    """운영 DB 구현. `app.domain.backtest.repository.BacktestTradeRepository` 를 만족한다.

    ⛔ **쓰기 없음.** 이 클래스에는 INSERT/UPDATE/DELETE 가 없고, 있어서도 안 된다.

    ⚠️ **드라이버 버퍼도 메모리다**(CR50-2). `FoldCollector` 의 `chunk_rows` 는 파이썬
       도메인 객체의 상한일 뿐이고, 그 앞에서 psycopg 가 결과를 버퍼한다. 기본(클라이언트
       커서)이면 `execute()` 가 돌아오는 순간 **그 질의 결과 전부**가 클라이언트 메모리에
       있다 — 질의가 시군구 단위이므로 상한이 "가장 큰 시군구의 행 수"가 된다.
       그래서 `stream_results` 로 **서버측 커서**를 쓰고 `max_row_buffer` 를 청크에 맞춘다.
       남은 몫과 미측정 부분은 `backtest.md §7-13` 에 숫자로 적어 두었다.
    """

    def __init__(self, engine, *, pause_sec: float = PAUSE_SEC,
                 stream_rows: int = DEFAULT_CHUNK_ROWS) -> None:
        self._engine = engine
        self._pause_sec = pause_sec
        #: 드라이버가 한 번에 받아 둘 행 수. 수집기의 `chunk_rows` 와 같은 값으로 맞춘다 —
        #: 두 곳에 다른 숫자를 두면 "상한"이 어느 쪽 숫자인지 아무도 모르게 된다.
        self._stream_rows = max(1, int(stream_rows))

    def sigungu_codes(self) -> list[str]:
        from sqlalchemy import text

        with self._engine.connect() as conn:
            apply_session_guards(conn)
            rows = conn.execute(text(_SIGUNGU_SQL),
                                {"sidos": list(SIDO_PREFIXES)}).all()
        return [r.code for r in rows]

    def trades_for_backtest(
        self,
        *,
        start: dt.date,
        end: dt.date,
        region_codes: Sequence[str] | None = None,
    ) -> Iterator[BacktestTrade]:
        from sqlalchemy import text

        targets = list(region_codes) if region_codes else self.sigungu_codes()
        for i, region in enumerate(targets, start=1):
            with self._engine.connect() as conn:
                apply_session_guards(conn)
                # ★ 서버측 커서. 이게 없으면 시군구 하나치 결과가 통째로 클라이언트
                #   메모리에 올라온다(CR50-2). `statement_timeout` 은 FETCH 마다 따로
                #   걸리므로 가드는 그대로 유지된다.
                result = conn.execute(
                    text(_TRADES_SQL),
                    {"start": start, "end": end,
                     "region": region, "plen": len(region)},
                    execution_options={"stream_results": True,
                                       "max_row_buffer": self._stream_rows})
                for row in result:
                    yield BacktestTrade(
                        complex_id=row.complex_id,
                        contract_date=row.contract_date,
                        price_krw=int(row.price_krw),
                        area_m2=float(row.area_m2),
                        region_code=row.region_code,
                        is_cancelled=bool(row.is_cancelled),
                        # ⚠️ `trade` 에 `cancelled_on` 컬럼이 없다(마이그레이션 017 필요).
                        #    그래서 항상 None 이고 EXCLUDE_KNOWN_AT 정책을 쓸 수 없다
                        #    — 그 정책을 고르면 도메인이 예외로 멈춘다(backtest.md §2-D).
                        cancelled_on=None,
                        registered_at=row.registered_at,
                        apt_dong=row.apt_dong,
                        floor=row.floor,
                    )
            if i < len(targets):
                time.sleep(self._pause_sec)

    def household_counts(self, complex_ids: Iterable[int]) -> dict[int, int | None]:
        """전 시군구를 훑어 세대수를 모은다. 요청한 id 만 남긴다."""
        from sqlalchemy import text

        wanted = set(complex_ids)
        out: dict[int, int | None] = dict.fromkeys(wanted)
        for region in self.sigungu_codes():
            with self._engine.connect() as conn:
                apply_session_guards(conn)
                rows = conn.execute(text(_HOUSEHOLDS_SQL),
                                    {"region": region, "plen": len(region)}).all()
            for row in rows:
                if row.id in wanted:
                    out[row.id] = row.total_households
        return out


def build_scorer(name: str, *, seed: int):
    """이름 → 스코어러. 대조군(무작위·상수)을 **같은 목록에** 둔다 — 비교 없이는 못 읽는다."""
    table = {
        "current_weights": weighted_scorer,
        "price_attractiveness": lambda: single_axis_scorer(AXIS_PRICE_ATTRACTIVENESS),
        "price_trend": lambda: single_axis_scorer(AXIS_PRICE_TREND),
        "liquidity": lambda: single_axis_scorer(AXIS_LIQUIDITY),
        "random": lambda: random_scorer(seed),
        "constant": constant_scorer,
    }
    if name not in table:
        raise SystemExit(f"모르는 스코어러: {name} (가능: {', '.join(table)})")
    return table[name]()


SCORER_NAMES = ("current_weights", "price_attractiveness", "price_trend",
                "liquidity", "random", "constant")


def parse_folds(raw: str | None, as_of: str | None) -> list[dt.date]:
    dates = [d.strip() for d in (raw or as_of or "").split(",") if d.strip()]
    if not dates:
        raise SystemExit("--as-of 또는 --folds 로 기준시점을 하나 이상 주세요 (YYYY-MM-DD)")
    try:
        return [dt.date.fromisoformat(d) for d in dates]
    except ValueError as exc:
        raise SystemExit(f"날짜 형식 오류(YYYY-MM-DD): {exc}") from exc


def run_params(*, folds: Sequence[dt.date], scorer_name: str, top_n: int,
               horizon_months: int, window_months: int, min_trades: int,
               min_peer_cells: int, policy: CancellationPolicy,
               unmeasured: UnmeasuredPolicy, null_draws: int, seed: int,
               chunk_rows: int, max_samples: int | None) -> dict[str, object]:
    """이 실행을 **재현할 수 있게 하는 값 전부**. 산출 JSON 에 그대로 실린다.

    ⚠️ 특히 `cancellation` — 이게 없으면 상·하한 두 번 돌린 산출물이 **내용만으로는
       구별되지 않는다**(CR49-4). `--cancellation` 의 도움말이 직접 "두 번 돌려 범위로
       보고하라"고 지시하는데, 그 범위의 두 끝이 어느 정책이었는지 파일이 말하지 못하면
       나중에 아무도 증명할 수 없다.
    """
    return {
        "folds": [d.isoformat() for d in folds],
        "scorer": scorer_name,
        "top_n": top_n,
        "horizon_months": horizon_months,
        "window_months": window_months,
        "min_trades": min_trades,
        "min_peer_cells": min_peer_cells,
        "cancellation": policy.value,
        "unmeasured": unmeasured.value,
        "report_lag_days": REPORT_LAG_DAYS,
        "null_draws": null_draws,
        "seed": seed,
        "chunk_rows": chunk_rows,
        "max_samples": max_samples,
    }


def report_payload(report: BacktestReport,
                   params: dict[str, object]) -> dict[str, object]:
    """리포트 → JSON. **개인 정보 없음** — 셀 식별자와 통계, 그리고 재현용 파라미터뿐."""
    return {
        "scorer": report.scorer_name,
        "verdict": report.verdict,
        "regimes": list(report.regimes),
        "median_excess_market_pct": report.median_excess_market_pct,
        "median_excess_peer_pct": report.median_excess_peer_pct,
        "quotable_folds": report.quotable_folds,
        "may_calibrate_weights": report.may_calibrate_weights,
        "params": dict(params),
        "notes": list(report.notes),
        "folds": [fold_row(r) for r in report.folds],
    }


def run(*, folds: Sequence[dt.date], scorer_name: str, top_n: int,
        horizon_months: int, window_months: int, min_trades: int, min_peer_cells: int,
        policy: CancellationPolicy, unmeasured: UnmeasuredPolicy,
        null_draws: int, seed: int, json_path: str | None, dry_run: bool,
        chunk_rows: int = DEFAULT_CHUNK_ROWS,
        max_samples: int | None = DEFAULT_MAX_SAMPLES) -> int:
    env = load_env()
    log.info("환경파일: %s", env or "(없음 — 환경변수 사용)")

    params = run_params(folds=folds, scorer_name=scorer_name, top_n=top_n,
                        horizon_months=horizon_months, window_months=window_months,
                        min_trades=min_trades, min_peer_cells=min_peer_cells,
                        policy=policy, unmeasured=unmeasured, null_draws=null_draws,
                        seed=seed, chunk_rows=chunk_rows, max_samples=max_samples)
    log.info("파라미터: %s", json.dumps(params, ensure_ascii=False))

    specs = [FoldSpec(as_of=d, horizon_months=horizon_months,
                      window_months=window_months) for d in folds]
    ranges = [s.required_contract_range(report_lag_days=REPORT_LAG_DAYS) for s in specs]
    minimal = [s.required_contract_range(report_lag_days=REPORT_LAG_DAYS,
                                         include_prior=False) for s in specs]
    start = min(r[0] for r in ranges)
    end = max(r[1] for r in ranges)
    log.info("폴드 %d개 · 필요한 계약일 범위 %s ~ %s (신고지연 %d일 반영)",
             len(specs), start, end, REPORT_LAG_DAYS)
    log.info("  ⚠ 가격추세 축을 빼면 %s 부터로 충분합니다 — 직전 창이 없는 폴드에서는 "
             "그 축이 통째로 빠지고 가중치가 재정규화됩니다(backtest.md §4-D).",
             min(r[0] for r in minimal))
    for spec, (lo, hi), (mlo, _) in zip(specs, ranges, minimal, strict=True):
        log.info("  · T=%s → T+%d개월=%s · 전체 %s~%s · 추세 제외 시 %s~",
                 spec.as_of, spec.horizon_months, spec.outcome_as_of, lo, hi, mlo)

    if dry_run:
        # DB 에 **닿기 전에** 끝낸다 — 백필이 도는 동안에도 계획을 확인할 수 있어야 한다.
        log.info("--dry-run — 조회하지 않고 계획만 출력했습니다.")
        return 0

    engine = make_engine()
    log.info("DB: %s", safe_dsn(str(engine.url)))
    # 드라이버 버퍼도 청크에 맞춘다 — 파이썬 쪽만 상한을 걸고 드라이버가 시군구 하나치를
    # 통째로 버퍼하면 "상한"이라는 말이 참이 아니다(CR50-2).
    repo = PostgresBacktestRepository(engine, stream_rows=chunk_rows)

    # ⛔ `list(...)` 로 접지 않는다 — 전 구간을 한 번에 올리면 서버(가용 261MB)가
    #    스래싱한다(CR49-3). 수집기가 청크로 끊어 읽고 셀별 ₩/㎡ 값만 남긴다.
    #    폴드 전부를 **한 번의 순회**로 모으므로 DB 도 한 번만 훑는다.
    collector = FoldCollector(specs, policy=policy, min_trades=min_trades,
                              min_peer_cells=min_peer_cells, chunk_rows=chunk_rows,
                              max_samples=max_samples)
    collector.feed(repo.trades_for_backtest(start=start, end=end))
    # ⚠️ 찍는 값은 `peak_live_rows`(청크 + as-of 뷰)다. `peak_chunk_rows` 만 찍던 옛 판은
    #    운영 모양(동 마스킹 사본)에서 상한을 **절반으로** 말했다(CR50-1).
    log.info("거래 %d건 통과(계약일 %s~%s) · 순간 보유 행 최대 %d[청크 %d + 뷰]"
             "(상한 %d = 2×%d) · 누적 표본 %d",
             collector.rows_seen, start, end, collector.peak_live_rows,
             collector.peak_chunk_rows, 2 * chunk_rows, chunk_rows, collector.samples)
    if not collector.rows_seen:
        log.warning("거래가 0건입니다 — 백필이 끝났는지 확인하세요. 결과를 만들지 않습니다.")
        return 1

    households = repo.household_counts(collector.complex_ids)
    known = sum(1 for v in households.values() if v)
    log.info("세대수 확보 %d/%d 단지 (%.1f%%) — 환금성 축의 상한입니다",
             known, len(households), known / len(households) * 100 if households else 0.0)

    scorer = build_scorer(scorer_name, seed=seed)
    results = []
    for spec in specs:
        cells = collector.cells(spec, households=households)
        log.info("[%s] 후보 셀 %d개 · 축 커버리지 %s", spec.name, len(cells),
                 json.dumps(universe_axis_summary(cells), ensure_ascii=False))
        outcomes = collector.outcomes(spec, cells)
        result = run_fold(spec=spec, cells=cells, outcomes=outcomes, scorer=scorer,
                          top_n=top_n, unmeasured_policy=unmeasured,
                          min_peer_cells=min_peer_cells, null_draws=null_draws,
                          rng_seed=seed)
        results.append(result)
        log.info("[%s] %s", spec.name,
                 json.dumps(fold_row(result), ensure_ascii=False))

    report = summarize(results)
    log.info("판정: %s · 국면 %s · 인용가능 폴드 %d/%d",
             report.verdict, list(report.regimes), report.quotable_folds,
             len(report.folds))
    log.info("상위 %d 초과수익 중위(시장 대비) %s%%p · (동종 대비) %s%%p",
             top_n, report.median_excess_market_pct, report.median_excess_peer_pct)
    for note in report.notes:
        log.info("  ⚠ %s", note)

    if json_path:
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(report_payload(report, params), fh, ensure_ascii=False, indent=2)
        log.info("JSON 저장: %s", json_path)

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="자기 채점(백테스트) — 읽기 전용")
    ap.add_argument("--as-of", default=None, help="기준시점 T (YYYY-MM-DD)")
    ap.add_argument("--folds", default=None, help="여러 T 를 콤마로 (YYYY-MM-DD,...)")
    ap.add_argument("--scorer", default="current_weights", choices=SCORER_NAMES)
    ap.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    ap.add_argument("--horizon-months", type=int, default=DEFAULT_HORIZON_MONTHS)
    ap.add_argument("--window-months", type=int, default=DEFAULT_WINDOW_MONTHS)
    ap.add_argument("--min-trades", type=int, default=MIN_TRADES_PER_ENDPOINT,
                    help="한 시점 가격을 세울 최소 거래 수(낮추면 표본이 늘고 잡음도 는다)")
    ap.add_argument("--min-peer-cells", type=int, default=MIN_PEER_CELLS)
    ap.add_argument("--cancellation", default=CancellationPolicy.EXCLUDE_FINAL.value,
                    choices=[p.value for p in CancellationPolicy],
                    help="해제 거래 정책. 상·하한 두 번 돌려 범위로 보고하세요(§2-D)")
    ap.add_argument("--unmeasured", default=UnmeasuredPolicy.DROP.value,
                    choices=[p.value for p in UnmeasuredPolicy],
                    help="T+H 에 거래가 없는 셀 처리(생존 편향 — §3-D)")
    ap.add_argument("--null-draws", type=int, default=DEFAULT_NULL_DRAWS)
    ap.add_argument("--seed", type=int, default=DEFAULT_RNG_SEED)
    ap.add_argument("--chunk-rows", type=int, default=DEFAULT_CHUNK_ROWS,
                    help="한 번에 손에 쥐는 거래 행 수. 실제 상한은 그 2배다(청크 + "
                         "as-of 뷰 사본). 드라이버 버퍼도 같은 값으로 맞춘다. "
                         "키우기 전에 서버 가용 메모리를 확인하세요(1행 ≈ 383B)")
    ap.add_argument("--max-samples", type=int, default=DEFAULT_MAX_SAMPLES,
                    help="누적 표본 상한. 넘으면 멈춘다(0 이면 상한 없음 — 권장하지 않음)")
    ap.add_argument("--json", dest="json_path", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="DB 를 조회하지 않고 필요한 데이터 범위만 출력한다")
    args = ap.parse_args()

    return run(folds=parse_folds(args.folds, args.as_of),
               scorer_name=args.scorer, top_n=args.top_n,
               horizon_months=args.horizon_months, window_months=args.window_months,
               min_trades=args.min_trades, min_peer_cells=args.min_peer_cells,
               policy=CancellationPolicy(args.cancellation),
               unmeasured=UnmeasuredPolicy(args.unmeasured),
               null_draws=args.null_draws, seed=args.seed,
               chunk_rows=args.chunk_rows,
               max_samples=args.max_samples or None,
               json_path=args.json_path, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
