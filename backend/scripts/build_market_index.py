"""시장 가격지수 계산·적재 — `market_price_index` (migration 015).

무엇을 만드는가
---------------
지역(시군구/시도)·월별로 아파트 ₩/㎡ 의 **상대 지수**를 만든다. 적정가 밴드가 6~36개월
창의 거래를 시점 구분 없이 섞는 문제를 보정하는 데 쓴다(왜 필요한지는
`app/domain/valuation/timeadjust.py` 와 migration 015 주석에 실측과 함께 적혀 있다).

계산 방법 — 고정효과 중위 (method = `fe_median_log_ppm_v1`)
-----------------------------------------------------------
    index(지역, 월) = exp( median( ln(price/area) − avg_group(ln(price/area)) ) )

    group = (complex_id, round(area_m2))

그룹 평균을 빼는 이유: 어느 달에 어떤 단지·평형이 거래됐는지에 따라 단순 중위는 크게
흔들린다(믹스효과). 같은 그룹 안의 편차만 보면 그 흔들림이 사라진다.

**2개월 이상 거래한 그룹만** 쓴다. 한 달에만 거래된 그룹은 잔차가 정확히 0 이라 지수를
1 쪽으로 끌어당긴다(감쇠). 실측으로 확인된 크기 — 서울 18개월 변화:
전체 그룹 +20.6% vs 다월 그룹 +26.6%. 감쇠를 방치하면 보정이 체계적으로 모자란다.

⚠️ 운영 DB 메모리 (**실제로 한 번 죽였다**)
--------------------------------------------
운영 db 컨테이너는 `mem_limit 192MB` 다. 2026-07-28 측정 중 (단지,면적) 그룹 38,000개에
`percentile_disc` 4개를 동시에 건 쿼리가 **서버를 OOM 으로 재기동시켰다**(read-only 라
데이터 손실은 없었고 자동 복구됨). 그래서 이 스크립트는:

  · **지역 하나씩** 나눠 돈다 — 한 쿼리가 보는 행이 시군구 수천 ~ 시도 30만 행을 넘지 않는다
  · **지역 하나가 한 트랜잭션**이다 — 48초짜리 트랜잭션이 vacuum 스냅샷을 붙들지 않게
    (UPSERT 가 멱등하므로 중간에 죽으면 그냥 다시 돌린다)
  · 정렬 집계는 쿼리당 **하나**(월별 median 하나)만 쓴다
  · `statement_timeout` · `work_mem` 를 세션에 명시한다 (서버 기본값에 기대지 않는다)
  · 지역 사이에 잠깐 쉰다 — 배치가 API 컨테이너의 숨통을 막지 않게

사용
----
    export DATABASE_URL=postgresql+psycopg://user:pw@host:5432/realestate
    python scripts/build_market_index.py --dry-run --region 11680   # 한 곳만 확인
    python scripts/build_market_index.py --scope sido               # 시도 3건
    python scripts/build_market_index.py                            # 전체(시군구+시도)
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import time
from typing import Any

# ⚠️ `_common` 을 먼저 import 한다 — import 부작용으로 backend 가 sys.path 에 붙고
#    로깅 억제·비밀 마스킹이 설치된다(SR17-3). 아래 app.* import 가 여기에 기댄다.
from _common import load_env, make_engine, safe_dsn

from app.domain.valuation.timeadjust import (  # noqa: E402
    INDEX_METHOD,
    MIN_INDEX_MONTH_SAMPLE,
    MIN_REFERENCE_MONTH_SAMPLE,
    SCOPE_SIDO,
    SCOPE_SIGUNGU,
    build_index,
    open_ym,
)

log = logging.getLogger("build_market_index")

#: 계산 방법 식별자. **방법을 바꾸면 이 값을 바꾼다** — 다른 방법으로 만든 값이
#: 같은 표에 섞이면 어느 달이 어느 방법인지 알 수 없게 된다.
#: 도메인이 소유한다(`timeadjust.INDEX_METHOD`) — **조회도 같은 값으로 걸러야** 하므로
#: 적재 쪽에서 따로 정의하면 둘이 어긋나는 날 조용히 0행이 된다.
METHOD = INDEX_METHOD

#: 지수를 만들 기간(개월). 밴드 사다리 최대(36개월)를 덮어야 그 창의 거래를 보정할 수 있다.
DEFAULT_MONTHS = 36

#: 세션 가드. 서버 기본값에 기대지 않는다(위 메모리 주석 참조).
#:
#: ⚠️ work_mem 12MB → 4MB (2026-07-28 실행 직전 재측정)
#: 이 값을 정할 때의 근거는 "여유가 있다"였는데, 실행 시점의 db 컨테이너는 **이미
#: 137MB 를 쓰고 있었다**(anon 64MB + shmem 64MB=shared_buffers, 한계 192MB).
#: 즉 쿼리가 쓸 수 있는 자리는 50MB 남짓이다. 이 쿼리에는 정렬 노드가 둘 있고
#: (윈도우함수 PARTITION BY 정렬 · percentile_cont 의 그룹별 tuplesort),
#: 각 노드가 work_mem 만큼을 **따로** 잡는다 — 12MB 면 최악 30~40MB 로 여유를 다 먹는다.
#: 4MB 로 낮추면 정렬이 디스크로 더 자주 흘러 느려지지만(실측 41 시도 4.7초),
#: **컨테이너가 죽지 않는다.** 이 서버에서 OOM 은 db 재기동이고, 재기동은 배치 실패보다 비싸다.
#: (서버 기본값은 2MB 다 — 우리가 올린 값이라는 사실을 잊지 말 것.)
SESSION_GUARDS = ("SET statement_timeout = '120s'", "SET work_mem = '4MB'")

#: 지역 사이 휴식(초). 배치가 API 응답을 굶기지 않도록.
PAUSE_SEC = 0.4

#: 잔차 계산에 쓸 그룹 최소 거래월 수. 1개월 그룹은 잔차가 0 이라 지수를 감쇠시킨다.
MIN_GROUP_MONTHS = 2

#: 지역 코드 접두 → 시도. 우리 서비스 범위는 수도권이다(CLAUDE.md).
SIDO_PREFIXES = {"11": "서울", "41": "경기", "28": "인천"}


# ---------------------------------------------------------------------------
# SQL — 지역 하나의 월별 지수. 파라미터 바인딩만 쓴다(문자열 조립 금지).
# ---------------------------------------------------------------------------
_INDEX_SQL = """
WITH t AS (
    SELECT tr.complex_id,
           round(tr.area_m2)::int                    AS a,
           to_char(tr.contract_date, 'YYYY-MM')      AS ym,
           ln(tr.price_krw::numeric / tr.area_m2)    AS lp
    FROM trade tr
    JOIN complex c ON c.id = tr.complex_id
    WHERE NOT tr.is_cancelled
      AND tr.area_m2 > 0
      AND tr.price_krw > 0
      AND tr.contract_date >= :since
      AND left(c.region_code, :plen) = :region
),
multi AS (
    -- 2개월 이상 거래한 그룹만(감쇠 방지). HAVING 으로 좁혀 잔차 계산 대상을 줄인다.
    SELECT complex_id, a
    FROM t GROUP BY complex_id, a
    HAVING count(DISTINCT ym) >= :min_months
),
r AS (
    SELECT t.ym,
           t.lp - avg(t.lp) OVER (PARTITION BY t.complex_id, t.a) AS resid
    FROM t JOIN multi USING (complex_id, a)
)
SELECT ym,
       exp(percentile_cont(0.5) WITHIN GROUP (ORDER BY resid)) AS idx_value,
       count(*)                                                AS sample_size
FROM r
GROUP BY ym
ORDER BY ym
"""

_UPSERT_SQL = """
INSERT INTO market_price_index
    (region_code, scope, ym, idx_value, sample_size, is_complete, method, computed_at)
VALUES (:region_code, :scope, :ym, :idx_value, :sample_size, :is_complete, :method, now())
ON CONFLICT (region_code, scope, ym) DO UPDATE SET
    idx_value   = EXCLUDED.idx_value,
    sample_size = EXCLUDED.sample_size,
    is_complete = EXCLUDED.is_complete,
    method      = EXCLUDED.method,
    computed_at = EXCLUDED.computed_at
"""

_REGIONS_SQL = """
SELECT DISTINCT left(region_code, :plen) AS code
FROM complex
WHERE region_code IS NOT NULL
  AND left(region_code, 2) = ANY(:sidos)
ORDER BY 1
"""


def _since(months: int, today: dt.date) -> dt.date:
    """지수 계산 시작일. 월 첫날로 맞춰 부분 월이 섞이지 않게 한다."""
    y, m = today.year, today.month - months
    while m <= 0:
        y, m = y - 1, m + 12
    return dt.date(y, m, 1)


def region_codes(conn: Any, scope: str) -> list[str]:
    """대상 지역 코드 목록. 시군구는 5자리, 시도는 2자리."""
    from sqlalchemy import text

    plen = 5 if scope == SCOPE_SIGUNGU else 2
    rows = conn.execute(text(_REGIONS_SQL),
                        {"plen": plen, "sidos": list(SIDO_PREFIXES)}).fetchall()
    return [r[0] for r in rows if r[0] and len(r[0]) == plen]


def compute_region(conn: Any, region: str, scope: str, *,
                   since: dt.date, as_of: dt.date) -> list[dict]:
    """지역 하나의 월별 지수. 표본 미달 월은 `build_index` 가 걸러낸다.

    `as_of` 는 **실행 시각을 한 번 정해서** 내려보낸다(`run` 이 정한다). 지역마다
    `date.today()` 를 다시 읽으면 자정을 걸친 실행에서 지역별로 완결 판정이 갈린다.
    """
    from sqlalchemy import text

    plen = 5 if scope == SCOPE_SIGUNGU else 2
    rows = conn.execute(text(_INDEX_SQL), {
        "since": since, "plen": plen, "region": region, "min_months": MIN_GROUP_MONTHS,
    }).fetchall()

    index = build_index(
        ((r[0], float(r[1]), int(r[2])) for r in rows),
        region_code=region, scope=scope, as_of=as_of, method=METHOD,
    )
    return [{
        "region_code": region, "scope": scope, "ym": p.ym,
        "idx_value": round(p.value, 6), "sample_size": p.sample_size,
        "is_complete": p.is_complete, "method": METHOD,
    } for p in sorted(index.points.values(), key=lambda p: p.ym)]


def run(*, scope: str, only_region: str | None, months: int, dry_run: bool,
        as_of: dt.date | None = None) -> int:
    from sqlalchemy import text

    load_env()
    engine = make_engine()
    # ⚠️ 시각은 **여기서 한 번만** 읽는다. 아래 계산 함수들은 시계를 읽지 않는다
    #    (읽으면 같은 실행 안에서도 지역마다 완결 판정이 달라질 수 있다).
    today = as_of or dt.date.today()
    log.info("DB=%s scope=%s months=%d dry_run=%s as_of=%s (완결 상한: %s 이전 달)",
             safe_dsn(str(engine.url)), scope, months, dry_run, today, open_ym(today))

    since = _since(months, today)
    scopes = [SCOPE_SIGUNGU, SCOPE_SIDO] if scope == "all" else [scope]
    written = 0

    # ⚠️ 트랜잭션은 **지역 단위**다(CR33-4). 예전에는 85지역·48초가 한 트랜잭션이라
    #    ① 마지막 지역이 실패하면 앞의 84곳이 통째로 롤백되고
    #    ② 48초짜리 스냅샷이 192MB db 의 vacuum 을 막았다.
    #    UPSERT 가 멱등하므로(ON CONFLICT DO UPDATE) 중간에 죽어도 그냥 다시 돌리면 된다
    #    — 부분 적용이 위험한 종류의 작업이 아니다.
    with engine.connect() as conn:
        for guard in SESSION_GUARDS:
            conn.execute(text(guard))
        conn.commit()          # `SET` 은 세션 것이라 커밋해도 남는다

        for sc in scopes:
            targets = [only_region] if only_region else region_codes(conn, sc)
            if only_region and len(only_region) != (5 if sc == SCOPE_SIGUNGU else 2):
                continue                      # 자릿수가 맞는 scope 에서만 돈다
            log.info("[%s] 지역 %d곳", sc, len(targets))

            for i, region in enumerate(targets, start=1):
                points = compute_region(conn, region, sc, since=since, as_of=today)
                if not points:
                    log.warning("[%s %s] 지수 없음 — 월 표본 %d건 미만만 존재 "
                                "(상위 지역 지수로 폴백해야 함)",
                                sc, region, MIN_INDEX_MONTH_SAMPLE)
                    conn.rollback()            # 읽기 스냅샷을 붙들고 있지 않는다
                    continue
                latest = points[-1]
                # 기준월 자격은 개별 월보다 문턱이 높다(timeadjust.MIN_REFERENCE_MONTH_SAMPLE).
                # 여기서 미리 찍어 둬야 "지수는 있는데 보정이 안 된다"를 배치 로그로 안다.
                ref = [p for p in points
                       if p["is_complete"] and p["sample_size"] >= MIN_REFERENCE_MONTH_SAMPLE]
                log.info("[%s %s] %d개월 · 기준월 %s · 최신 %s(%s, n=%d)",
                         sc, region, len(points),
                         ref[-1]["ym"] if ref else "없음(표본부족 → 폴백)",
                         latest["ym"],
                         "완결" if latest["is_complete"] else "미완결",
                         latest["sample_size"])
                if not dry_run:
                    conn.execute(text(_UPSERT_SQL), points)
                    written += len(points)
                conn.commit()                  # 지역 하나가 곧 한 트랜잭션이다
                if i < len(targets):
                    time.sleep(PAUSE_SEC)

    log.info("완료 — %s %d행", "계산만(미저장)" if dry_run else "저장", written)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="시장 가격지수 계산·적재")
    ap.add_argument("--scope", choices=[SCOPE_SIGUNGU, SCOPE_SIDO, "all"], default="all")
    ap.add_argument("--region", default=None, help="한 지역만(디버그). 시군구 5자리/시도 2자리")
    ap.add_argument("--months", type=int, default=DEFAULT_MONTHS)
    ap.add_argument("--dry-run", action="store_true", help="계산만 하고 저장하지 않는다")
    args = ap.parse_args()
    return run(scope=args.scope, only_region=args.region, months=args.months,
               dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
