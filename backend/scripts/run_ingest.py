"""국토부 실거래가 수집 실행 (운영 진입점 `run_daily` 의 CLI 껍데기).

설계 근거: backend/app/ingest/run_molit.py · architecture.md §2.3(일 1회 야간 배치)

이 스크립트가 하는 일은 **배선뿐**이다 — 수집 로직은 전부 `app.ingest` 에 있다.
큐 워커(worker-ingest)가 붙기 전까지 사람이 같은 경로를 손으로 돌릴 수 있게 한다.

지역 목록
---------
기본은 `config/region_code_verification.yaml` 에서 **실호출로 데이터가 확인된 코드만**
쓴다. 검증 파일이 없으면 `regions_capital.yaml` 전체를 쓰되 경고한다 —
일반구가 있는 시(수원시 41110 등)는 정상적으로 0건이라 그대로 돌리면 로그가 지저분해지고,
진짜 문제(신설/폐지 코드로 인한 조용한 결측)가 묻힌다.

사용
----
    export DATABASE_URL=postgresql+psycopg://user:pw@172.19.0.2:5432/realestate
    python scripts/run_ingest.py --codes 11680,11650,11710 --lookback 5
    python scripts/run_ingest.py --verified --lookback 1 --today 2026-07-25
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# ⚠️ `_common` import 자체가 로깅 억제·마스킹을 설치한다(SR17-3). 지우지 말 것.
from _common import (  # noqa: E402
    REPO_ROOT,
    configure_logging,
    database_url,
    load_env,
    make_engine,
    mask_secrets,
    require,
    safe_dsn,
)

from app.core.regions import load_capital_sigungu  # noqa: E402
from app.ingest.loader import make_db_region_resolver  # noqa: E402
from app.ingest.ratelimit import RateLimiter  # noqa: E402
from app.ingest.run_molit import region_codes_from, run_daily  # noqa: E402

VERIFICATION_PATH = REPO_ROOT / "config" / "region_code_verification.yaml"


def verified_codes(path: Path = VERIFICATION_PATH) -> list[str] | None:
    """검증 파일에서 `has_data` 코드만. 파일이 없으면 None."""
    if not path.exists():
        return None
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [str(c["code"]) for c in (raw.get("codes") or [])
            if c.get("status") == "has_data"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="국토부 실거래가 수집 실행")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--codes", help="시군구 5자리(쉼표)")
    src.add_argument("--verified", action="store_true", help="검증된 코드 전체(기본)")
    src.add_argument("--all", action="store_true", help="regions_capital.yaml 전체(검증 무시)")
    ap.add_argument("--lookback", type=int, default=1, help="today 기준 소급 개월 수")
    ap.add_argument("--today", help="기준일(YYYY-MM-DD). 과거 구간 백필에 쓴다")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 N개 코드만(단계적 검증용)")
    ap.add_argument("--min-interval", type=float, default=0.4, help="요청 간 최소 간격(초)")
    args = ap.parse_args(argv)

    # 로깅 억제·마스킹은 `_common` import 시점에 이미 걸려 있다(SR17-3).
    # 여기서는 레벨만 명시한다 — 부르는 것을 잊어도 구멍이 생기지 않는다.
    configure_logging(logging.INFO)
    load_env()
    service_key = require("MOLIT_API_KEY")           # 없으면 즉시 멈춘다(가짜 성공 금지)

    if args.codes:
        codes = region_codes_from(args.codes.split(","))
    elif args.all:
        codes = [s.code for s in load_capital_sigungu()]
    else:
        codes = verified_codes()
        if codes is None:
            print("[WARN] 검증 파일이 없습니다 — regions_capital.yaml 전체를 씁니다.")
            print("       먼저 scripts/verify_region_codes.py 를 돌리는 것을 권장합니다.")
            codes = [s.code for s in load_capital_sigungu()]
    if args.limit:
        codes = codes[:args.limit]
    if not codes:
        print("[FAIL] 수집할 시군구 코드가 없습니다.")
        return 1

    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    url = database_url()
    engine = make_engine(url)
    print(f"[INFO] DB {safe_dsn(url)}")
    print(f"[INFO] 시군구 {len(codes)}개 × 최근 {args.lookback + 1}개월 (기준일 {today})")

    try:
        resolver = make_db_region_resolver(engine)
        run = run_daily(
            service_key=service_key,
            region_codes5=codes,
            engine=engine,
            today=today,
            lookback_months=args.lookback,
            region_resolver=resolver,
            rate_limiter=RateLimiter(min_interval_sec=args.min_interval, jitter_sec=0.3),
        )
    finally:
        engine.dispose()

    print(f"\n[결과] status={run.status} rows_ok={run.rows_ok} rows_failed={run.rows_failed}")
    print(f"       {mask_secrets(run.message)}")
    # stdout 은 운영에서 `/tmp/*.log` 로 리다이렉트된다 — 여기로 새면 파일에 남는다.
    # runner 가 이미 지우고 올리지만, 파일로 나가는 마지막 지점에서 한 번 더 지운다.
    for where, why in run.failures[:20]:
        print(f"       실패 {where}: {mask_secrets(why)}")
    if len(run.failures) > 20:
        print(f"       ... 외 {len(run.failures) - 20}건")
    return 0 if run.status == "ok" else (2 if run.status == "failed" else 0)


if __name__ == "__main__":
    sys.exit(main())
