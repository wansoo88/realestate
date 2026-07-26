"""단지 좌표 채우기 — 카카오 로컬 키워드검색 + **검증**으로 `complex.geom` 을 채운다.

왜 필요한가
-----------
MOLIT 실거래에는 좌표가 없다. 지도(F1)·입지 분석(F5)·동별 추정 폴백(F4)이 전부
`complex.geom` 위에서 돈다. 좌표가 없으면 그 단지는 지도에서 사라지고 입지 점수가
'정보 없음'이 된다 — 조용히 빠지는 게 아니라 **미확보 건수를 사유별로 세어 보고**한다.

⚠️ CR-020 GEO-1 — 확보율은 품질이 아니다
----------------------------------------
이전 버전은 카카오 1위 결과를 검증 없이 저장해 확보율 93.6% 를 냈지만,
운영 DB 에 **다른 단지와 좌표가 완전히 같은 단지 514건(7.9%, 그중 68건은 법정동까지 다름)**
을 만들었다. 이제 법정동·시군구·단지명 대조를 통과한 좌표만 채택한다(geocode.py).
**확보율은 떨어진다. 그게 맞다** — 틀린 좌표를 빼면 당연히 떨어진다.

⚠️ REB-1 — 이름으로 못 찾는 것은 **주소로** 찾는다
--------------------------------------------------
GEO-1 후 미확보 1,307건의 사유는 검증불합격 749 + 검색0건 518 이었고, 둘 다 이름의 한계였다.
부동산원 단지 마스터와 매칭된 단지는 지번주소를 알기 때문에 카카오 **주소검색**으로
좌표를 얻을 수 있다(`--address`). 주소 경로도 검증을 우회하지 않는다 — 법정동코드·본번·
부번이 일치해야 하고, 동 중심점(`REGION`)은 받지 않는다.

이어 돌기
---------
못 찾은 단지는 geom 이 NULL 로 남는다. 커서(`--after`) 없이 반복하면 실패 건만
계속 다시 시도하므로, 배치마다 `last_id` 를 이어받아 앞으로 나아간다.

사용
----
    export DATABASE_URL=...
    python scripts/geocode_complexes.py --dry-run --sample 300   # 쓰기 없이 품질만 측정
    python scripts/geocode_complexes.py --reverify               # 레거시 좌표 백업→비움→재검증
    python scripts/geocode_complexes.py --batch 200              # 미확보분만 이어서
    python scripts/geocode_complexes.py --address                # 부동산원 매칭분을 주소로 회수
    python scripts/geocode_complexes.py --recheck-shared --dry-run   # 잘못 공유된 점 목록만
    python scripts/geocode_complexes.py --recheck-shared --address   # 비우고 주소로 재확보

⚠️ CR-021 GEO-3 — 좌표 공유 판정을 다시 봐야 했던 이유
------------------------------------------------------
`--reverify` 후 남은 좌표 충돌 199건을 "전부 같은 법정동 안의 동일 단지"라고 결론냈는데,
같은 라운드에 적재한 부동산원 마스터가 그걸 반증했다 — 같은 점을 쓰면서 단지고유번호가
**서로 다른** 그룹이 15개(30단지) 있었다. `--recheck-shared` 는 이미 들어간 좌표를
현재 규칙으로 다시 판정해 그런 점을 백업 후 비운다.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import database_url, load_env, make_engine, require, safe_dsn  # noqa: E402

from app.ingest.geocode import (  # noqa: E402
    KakaoAddressSearch,
    KakaoPlaceSearch,
    NullPlaceSearch,
    VerifiedGeocoder,
    enrich_geom,
    enrich_postgis_geom,
    load_occupied,
    load_placed,
    row_target,
    unsafe_shared_ids,
)
from app.ingest.ratelimit import RateLimiter  # noqa: E402

#: dry-run 표본용 — geom 유무와 무관하게 대상 행을 읽는다.
#: 부동산원 주소는 매칭된 단지에만 붙는다(LEFT JOIN) — 주소 경로 품질도 같이 재려면 필요하다.
_SAMPLE_SQL = """
    SELECT c.id, c.name, c.address_jibun, r.sido, r.sigungu, c.reb_complex_id,
           b.address_jibun AS reb_address, b.legal_dong_code AS reb_dong_code,
           b.main_no AS reb_main_no, b.sub_no AS reb_sub_no,
           b.is_mountain AS reb_is_mountain
    FROM complex c
    LEFT JOIN region r ON r.code = c.region_code
    LEFT JOIN reb_complex b ON b.reb_complex_id = c.reb_complex_id
    ORDER BY c.id
"""

#: 좌표 충돌 실측 — 리포트가 확보율만 말하지 않게 하는 숫자(통과조건 5와 같은 질의).
#: `reb_rows` 는 CR-021 GEO-3 — 같은 점인데 부동산원 단지번호가 다른 행이다.
#: 법정동 대조가 못 잡는 "같은 동 안에서 남의 단지에 붙은 좌표"를 잡는다.
_COLLISION_SQL = """
    WITH pts AS (
        SELECT c.id, c.name, c.address_jibun, c.reb_complex_id, ST_AsText(c.geom) AS wkt
        FROM complex c WHERE c.geom IS NOT NULL
    ), grp AS (
        SELECT wkt, count(*) AS n, count(DISTINCT address_jibun) AS dongs,
               count(DISTINCT reb_complex_id) AS rebs
        FROM pts GROUP BY wkt HAVING count(*) > 1
    )
    SELECT
        (SELECT count(*) FROM pts p JOIN grp g ON g.wkt = p.wkt)                   AS collision_rows,
        (SELECT count(*) FROM grp)                                                 AS collision_groups,
        (SELECT count(*) FROM pts p JOIN grp g ON g.wkt = p.wkt WHERE g.dongs > 1) AS crossdong_rows,
        (SELECT count(*) FROM pts p JOIN grp g ON g.wkt = p.wkt WHERE g.rebs > 1)  AS reb_rows
"""


def build_geocoder(key: str, *, min_interval: float,
                   address_only: bool = False) -> VerifiedGeocoder:
    """카카오 백엔드 2종 + 검증 계층을 배선한다.

    ⚠️ SR18-7 — **속도 제한기는 하나다.**
    예전에는 키워드·주소 백엔드에 `RateLimiter` 를 **각각** 만들어 줬다. 두 인스턴스는
    서로의 마지막 호출 시각을 모르므로, 한 단지에서 주소→키워드로 이어 부를 때
    실효 간격이 설정값의 **절반**이 된다(0.25초 설정 → 실제 0.125초). 카카오 입장에선
    합의한 속도의 두 배로 맞는 것이고, 차단당하면 수집이 통째로 멈춘다 —
    속도 제한은 예의가 아니라 가용성 요구사항이다(ratelimit.py).
    같은 인스턴스를 넘겨 **프로세스 전체의 카카오 호출**이 한 줄로 서게 한다.

    `address_only` 면 키워드 백엔드를 아예 꽂지 않는다. 대상 단지는 이름으로 이미
    실패한 것들이라, 같은 질의를 다시 보내면 쿼터만 태우고 결과는 같다.
    """
    limiter = RateLimiter(min_interval_sec=min_interval, jitter_sec=0.15)
    place_search = (NullPlaceSearch() if address_only
                    else KakaoPlaceSearch(key, rate_limiter=limiter))
    address_search = KakaoAddressSearch(key, rate_limiter=limiter)
    return VerifiedGeocoder(place_search, address_search)


def coverage(engine) -> tuple[int, int]:
    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT count(*) AS total, count(geom) AS with_geom FROM complex")).one()
    return row.total, row.with_geom


def collisions(engine) -> tuple[int, int, int, int]:
    """(충돌 행수, 충돌 그룹수, 법정동이 다른 충돌 행수, 부동산원 번호가 다른 충돌 행수)."""
    from sqlalchemy import text

    with engine.connect() as conn:
        r = conn.execute(text(_COLLISION_SQL)).one()
    return r.collision_rows, r.collision_groups, r.crossdong_rows, r.reb_rows


def reverify_reset(engine, *, backup_table: str) -> tuple[int, int]:
    """검증 이력 없는 레거시 좌표를 **백업 후** 비운다. (백업행수, 비운행수)

    ⚠️ 파괴적 작업이다. 먼저 `backup` 스키마에 (id, geom) 을 통째로 복사하고,
       그다음 `geom_source IS NULL` 인 행만 비운다. 이미 검증을 통과해 출처가
       기록된 좌표는 건드리지 않는다 — 중단 후 재실행해도 진도가 유지된다.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS backup"))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {backup_table} AS
            SELECT id, name, address_jibun, geom, now() AS backed_up_at
            FROM complex WHERE geom IS NOT NULL
        """))
        backed = conn.execute(text(f"SELECT count(*) FROM {backup_table}")).scalar_one()
        cleared = conn.execute(text("""
            UPDATE complex SET geom = NULL, geom_confidence = NULL, updated_at = now()
            WHERE geom IS NOT NULL AND geom_source IS NULL
        """)).rowcount
    return int(backed), int(cleared)


_CLEAR_GEOM = """
    UPDATE complex
    SET geom = NULL, geom_source = NULL, geom_confidence = NULL, updated_at = now()
    WHERE id = ANY(:ids)
"""


def recheck_shared(engine, *, backup_table: str, apply: bool) -> tuple[list[int], list[str]]:
    """이미 들어간 좌표를 **현재 규칙으로 재판정**해 잘못 공유된 것을 비운다(CR-021 GEO-3).

    ⚠️ 파괴적 작업이다. `apply` 전에 `backup` 스키마로 (id, name, geom, 출처, 신뢰도)를
       먼저 복사한다. 비운 단지는 다음 배치(특히 `--address`)에서 다시 확보를 시도한다.
       어느 쪽이 틀렸는지 모르므로 **그룹 전체**를 비운다 — 남겨 두면 절반의 확률로
       틀린 좌표를 승인하는 셈이고, 이 모듈의 원칙은 "틀린 좌표는 좌표 없음보다 나쁘다"다.
    """
    from sqlalchemy import text

    placed = load_placed(engine)
    ids = unsafe_shared_ids(placed)
    by_id = {cid: (t, lon, lat) for cid, t, lon, lat in placed}
    notes = [f"#{i} '{by_id[i][0].legal_dong} {by_id[i][0].name}' "
             f"[reb {by_id[i][0].reb_id or '-'}] @ {by_id[i][1]:.6f},{by_id[i][2]:.6f}"
             for i in ids]
    if not ids or not apply:
        return ids, notes

    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS backup"))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {backup_table} AS
            SELECT id, name, address_jibun, reb_complex_id, geom,
                   geom_source, geom_confidence, now() AS backed_up_at
            FROM complex WHERE false
        """))
        conn.execute(text(f"""
            INSERT INTO {backup_table}
            SELECT id, name, address_jibun, reb_complex_id, geom,
                   geom_source, geom_confidence, now()
            FROM complex WHERE id = ANY(:ids)
        """), {"ids": ids})
        conn.execute(text(_CLEAR_GEOM), {"ids": ids})
    return ids, notes


def dry_run(engine, geocoder, *, sample: int, seed: int) -> int:
    """DB 를 바꾸지 않고 검증 결과만 집계한다 — 임계값·규칙을 실데이터로 점검하는 용도."""
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(text(_SAMPLE_SQL)).all()
    if sample and sample < len(rows):
        rows = random.Random(seed).sample(rows, sample)
        rows.sort(key=lambda r: r.id)
    targets = [(r.id, row_target(r)) for r in rows]
    print(f"[DRY] 표본 {len(targets)}건 — DB 를 쓰지 않습니다")

    accepted: list[str] = []

    def _noop(cid: int, fix) -> None:                 # noqa: ANN001 - GeoFix
        accepted.append(fix.confidence)

    res = enrich_geom(targets, geocoder, _noop, occupied={})
    n = len(targets)
    by_conf = {c: accepted.count(c) for c in ("exact", "variant", "address")}
    print(f"[DRY] 확보 {res.resolved}/{n} ({res.resolved / n * 100:.1f}%) "
          f"· {by_conf}")
    print(f"[DRY] 미확보 {res.unresolved} = 검증불합격 {res.rejected_mismatch} "
          f"+ 좌표충돌 {res.rejected_collision} "
          f"+ 검색0건 {res.unresolved - res.rejected_mismatch - res.rejected_collision}")
    print(f"[DRY] 같은 단지 좌표 공유(정상) {res.shared_point}")
    for s in res.samples:
        print(f"       {s}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="단지 좌표(geom) 채우기 — 검증 통과분만")
    ap.add_argument("--batch", type=int, default=200, help="한 배치 크기")
    ap.add_argument("--max", type=int, default=0, help="이번 실행 최대 시도 수(0=전부)")
    ap.add_argument("--after", type=int, default=0, help="시작 커서(complex.id)")
    ap.add_argument("--min-interval", type=float, default=0.25, help="요청 간 최소 간격(초)")
    ap.add_argument("--reverify", action="store_true",
                    help="검증 이력 없는 레거시 좌표를 백업 후 비우고 다시 채운다")
    ap.add_argument("--recheck-shared", action="store_true",
                    help="이미 들어간 좌표를 현재 규칙으로 재판정해 **잘못 공유된 점**을 "
                         "백업 후 비운다(CR-021 GEO-3). --dry-run 과 함께 쓰면 목록만 본다")
    ap.add_argument("--address", action="store_true",
                    help="부동산원과 매칭돼 지번주소를 아는 단지만 **주소검색**으로 회수한다 "
                         "(이름 경로는 쓰지 않는다 — 이미 실패한 질의를 다시 태우지 않기 위해)")
    ap.add_argument("--dry-run", action="store_true", help="DB 를 쓰지 않고 품질만 측정")
    ap.add_argument("--sample", type=int, default=300, help="--dry-run 표본 수(0=전부)")
    ap.add_argument("--seed", type=int, default=20260726, help="--dry-run 표본 시드")
    args = ap.parse_args(argv)

    load_env()
    key = require("KAKAO_REST_API_KEY")
    url = database_url()
    engine = make_engine(url)
    print(f"[INFO] DB {safe_dsn(url)}")

    total, with_geom = coverage(engine)
    c_rows, c_groups, c_cross, c_reb = collisions(engine)
    print(f"[INFO] 시작 시점 단지 {total}건 · 좌표 있음 {with_geom}건 "
          f"({(with_geom / total * 100) if total else 0:.1f}%)")
    print(f"[INFO] 시작 시점 좌표 충돌 {c_rows}건({c_groups}개 점) "
          f"· 그중 법정동 불일치 {c_cross}건 · 부동산원 번호 불일치 {c_reb}건")

    # 카카오 응답을 그대로 믿지 않는다 — 법정동·시군구·단지명을 대조해 통과분만 채택.
    geocoder = build_geocoder(key, min_interval=args.min_interval,
                              address_only=args.address)

    if args.recheck_shared:
        table = "backup.complex_geom_geo3"
        ids, notes = recheck_shared(engine, backup_table=table, apply=not args.dry_run)
        head = "재판정(미적용)" if args.dry_run else "재판정 → 백업 후 비움"
        print(f"[INFO] {head}: 잘못 공유된 좌표 {len(ids)}건"
              + (f" → {table}" if not args.dry_run else ""))
        for note in notes[:40]:
            print(f"       {note}")
        if args.dry_run:
            engine.dispose()
            return 0

    if args.dry_run:
        try:
            return dry_run(engine, geocoder, sample=args.sample, seed=args.seed)
        finally:
            engine.dispose()

    if args.reverify:
        table = "backup.complex_geom_pre_geo1"
        backed, cleared = reverify_reset(engine, backup_table=table)
        print(f"[INFO] 레거시 좌표 백업 {backed}건 → {table} · 비운 행 {cleared}건")

    occupied = load_occupied(engine)     # 배치마다 다시 읽지 않고 실행 내내 이어 쓴다
    print(f"[INFO] 이미 확보된 좌표 {len(occupied)}개 점 — 충돌 판정 기준선")

    resolved = unresolved = mismatch = collided = shared = by_address = 0
    cursor = args.after
    try:
        while True:
            remaining = args.batch if not args.max else min(args.batch,
                                                            args.max - resolved - unresolved)
            if remaining <= 0:
                break
            res = enrich_postgis_geom(engine, geocoder, limit=remaining,
                                      after_id=cursor, occupied=occupied,
                                      address_only=args.address)
            if res.resolved == 0 and res.unresolved == 0:
                break                                   # 후보 소진
            resolved += res.resolved
            unresolved += res.unresolved
            mismatch += res.rejected_mismatch
            collided += res.rejected_collision
            shared += res.shared_point
            by_address += res.resolved_by_address
            cursor = res.last_id
            print(f"  배치: 확보 {res.resolved} · 미확보 {res.unresolved}"
                  f"(불합격 {res.rejected_mismatch}/충돌 {res.rejected_collision}) "
                  f"(누적 {resolved}/{resolved + unresolved}) cursor={cursor}")
            for s in res.samples[:3]:
                print(f"       {s}")
    except KeyboardInterrupt:
        print("[WARN] 중단됨 — 여기까지 반영됨(재실행하면 이어서 진행)")
    finally:
        total, with_geom = coverage(engine)
        c_rows2, c_groups2, c_cross2, c_reb2 = collisions(engine)
        engine.dispose()

    attempted = resolved + unresolved
    print(f"\n[결과] 시도 {attempted}건 · 확보 {resolved}건 · 미확보 {unresolved}건 "
          f"({(resolved / attempted * 100) if attempted else 0:.1f}% 성공)")
    print(f"       미확보 내역: 검증불합격 {mismatch} · 좌표충돌 {collided} · "
          f"검색0건 {unresolved - mismatch - collided}")
    print(f"       확보 중 주소 경로 {by_address}건 · 이름 경로 {resolved - by_address}건")
    print(f"       같은 단지 좌표 공유(정상) {shared}건")
    print(f"       전체 단지 {total}건 중 좌표 보유 {with_geom}건 "
          f"({(with_geom / total * 100) if total else 0:.1f}%)")
    print(f"       좌표 충돌 {c_rows}→{c_rows2}건 · 법정동 불일치 충돌 {c_cross}→{c_cross2}건 "
          f"· 부동산원 번호 불일치 충돌 {c_reb}→{c_reb2}건")
    if unresolved:
        print("⚠️ 미확보 단지는 지도·입지 분석에서 빠집니다 — 그게 틀린 좌표보다 낫습니다.")
    if c_cross2:
        print("⛔ 법정동이 다른 좌표 충돌이 남아 있습니다 — 원인을 확인하세요.")
    if c_reb2:
        print("⛔ 부동산원 번호가 다른 좌표 충돌이 남아 있습니다(GEO-3) — 최소 하나는 틀린 좌표입니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
