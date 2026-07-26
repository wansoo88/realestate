"""이름 경로로 넣은 좌표를 **주소 경로와 대조해 전수 재검사**한다 (CR-022 GEO-7).

무엇이 문제였나
---------------
GEO-1~GEO-4 로 "다른 단지와 **완전히 같은 점**"은 걷어냈다. 그런데 좌표 충돌 게이트는
소수점 6자리까지 같을 때만 도는 방어라, 카카오가 **옆 단지의 다른 출입구**나 같은 이름의
다른 건물을 주면 몇백 m 어긋난 채 조용히 들어간다. 코드 결함이 아니라 **잔존 데이터** 문제다.

표본 진단(319·320건)에서 이름 경로 좌표의 **약 2%가 주소 경로와 400m 초과로** 어긋났고,
모집단 4,530건에 외삽하면 약 90건이다. 지도에서 몇백 m 어긋난 단지는 "없는 것"보다
나쁘다 — 사용자는 그게 틀린 줄 모르고 그 위치를 근거로 판단한다.

무엇을 하나
-----------
1. `complex.geom_source = 'kakao_keyword'` 이고 부동산원 지번주소를 아는 단지를
   **단지당 카카오 주소검색 1회**로 재판정한다(`sweep_name_path`).
2. 400m 초과로 어긋난 건은 **덮지 않는다.** 백업 → 무효화(geom=NULL) → 같은 응답을
   재사용해(`ReplayGeocoder`) 주소 경로로 다시 채운다. 충돌 게이트·공유 판정은
   평소와 똑같이 탄다 — 재확보가 또 다른 오좌표를 만들지 않게 하기 위해서다.

⚠️ 손대지 않는 것 — `name_contains` / `name_fuzzy`
--------------------------------------------------
이 판정은 "부동산원 주소가 이 단지의 주소가 맞다"에 기댄다. 그 근거는 단지명이
**완전히 일치**해서 매칭됐다는 사실(`name_exact`)이다. 포함·유사도로 매칭된 건은
매칭 자체가 덜 확실해서 **주소 쪽이 틀렸을 수 있다**(실측: '개포자이프레지던스' 1,317m).
일괄 처리하면 오류를 지우는 게 아니라 심는다. 그래서 재판정만 하고 **보고만 한다**
(`app.ingest.geocode.APPLIABLE_METHODS` 가 코드로 막는다 — 옵션으로도 못 넓힌다).

사용
----
    export DATABASE_URL=...
    python scripts/sweep_name_geoms.py                       # 전수 스윕(읽기 전용)
    python scripts/sweep_name_geoms.py --resume              # 중단분 이어서
    python scripts/sweep_name_geoms.py --from-file --apply   # 스윕 결과로 무효화·재확보

`--out` 파일에 판정이 **한 줄씩 즉시** 쌓인다. 4,500여 건은 rate limit 때문에 수십 분이
걸리므로, 끊겨도 `--resume` 으로 이어 가고 `--apply` 는 그 파일만 보고 돈다
(같은 질문을 두 번 보내지 않는다 = 카카오 쿼터를 두 배로 쓰지 않는다).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import database_url, load_env, make_engine, require, safe_dsn  # noqa: E402

from geocode_complexes import collisions, coverage  # noqa: E402

from app.ingest.geocode import (  # noqa: E402
    APPLIABLE_METHODS,
    NAME_PATH_TOLERANCE_M,
    GeoFix,
    GeoTarget,
    KakaoAddressSearch,
    ReplayGeocoder,
    enrich_geom,
    load_occupied,
    row_target,
    sweep_name_path,
)
from app.ingest.ratelimit import RateLimiter  # noqa: E402

#: 재판정 대상 — 이름 경로로 들어간 좌표 중 **주소로 대조할 근거가 있는** 것만.
#: 주소 경로로 들어간 좌표('kakao_address')는 이미 코드·번지 대조를 통과했으므로 제외한다.
_SELECT_SWEEP = """
    SELECT c.id, c.name, c.address_jibun, r.sido, r.sigungu, c.reb_complex_id,
           c.reb_match_method, c.geom_confidence,
           b.address_jibun AS reb_address, b.legal_dong_code AS reb_dong_code,
           b.main_no AS reb_main_no, b.sub_no AS reb_sub_no,
           b.is_mountain AS reb_is_mountain,
           ST_X(c.geom) AS lon, ST_Y(c.geom) AS lat
    FROM complex c
    LEFT JOIN region r ON r.code = c.region_code
    JOIN reb_complex b ON b.reb_complex_id = c.reb_complex_id
    WHERE c.geom IS NOT NULL
      AND c.geom_source = 'kakao_keyword'
      AND b.address_jibun IS NOT NULL
      AND b.main_no IS NOT NULL
      AND c.reb_match_method = ANY(:methods)
    ORDER BY c.id
"""

_BACKUP_DDL = """
    CREATE TABLE IF NOT EXISTS {table} AS
    SELECT id, name, address_jibun, reb_complex_id, reb_match_method, geom,
           geom_source, geom_confidence, now() AS backed_up_at
    FROM complex WHERE false
"""
_BACKUP_INSERT = """
    INSERT INTO {table}
    SELECT id, name, address_jibun, reb_complex_id, reb_match_method, geom,
           geom_source, geom_confidence, now()
    FROM complex WHERE id = ANY(:ids)
"""
_CLEAR_GEOM = """
    UPDATE complex
    SET geom = NULL, geom_source = NULL, geom_confidence = NULL, updated_at = now()
    WHERE id = ANY(:ids)
"""
_UPDATE_GEOM = """
    UPDATE complex
    SET geom = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
        geom_source = :source, geom_confidence = :conf, updated_at = now()
    WHERE id = :id
"""


def load_rows(engine, methods: list[str]) -> list:
    from sqlalchemy import text

    with engine.connect() as conn:
        return conn.execute(text(_SELECT_SWEEP), {"methods": methods}).all()


def read_verdicts(path: Path) -> dict[int, dict]:
    """이미 판정한 건들(JSONL). 중단 후 이어 돌기·`--apply` 재사용에 쓴다."""
    if not path.exists():
        return {}
    out: dict[int, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue                      # 중단 순간 반쯤 쓰인 줄 — 버리고 다시 판정한다
        if isinstance(rec.get("id"), int):
            out[rec["id"]] = rec
    return out


def sweep(engine, key: str, *, methods: list[str], tolerance: float,
          min_interval: float, out_path: Path, resume: bool, limit: int) -> dict[int, dict]:
    """전수 재판정. 판정 1건마다 파일에 즉시 쓴다(중단 내성)."""
    rows = load_rows(engine, methods)
    done = read_verdicts(out_path) if resume else {}
    by_id = {r.id: r for r in rows}
    todo = [r for r in rows if r.id not in done]
    if limit:
        todo = todo[:limit]

    print(f"[INFO] 대상 {len(rows)}건 · 이미 판정 {len(done)}건 · 이번에 {len(todo)}건")
    if done and not resume:
        print("[WARN] --resume 없이 돌면 기존 판정 파일에 덧붙습니다")

    search = KakaoAddressSearch(
        key, rate_limiter=RateLimiter(min_interval_sec=min_interval, jitter_sec=0.15))

    counts: dict[str, int] = {}
    written = 0
    with out_path.open("a", encoding="utf-8") as fp:
        def _record(verdict, target) -> None:      # noqa: ANN001 - SweepVerdict
            nonlocal written
            row = by_id[verdict.complex_id]
            rec = {
                "id": verdict.complex_id,
                "status": verdict.status,
                "distance_m": (round(verdict.distance_m, 1)
                               if verdict.distance_m is not None else None),
                "method": row.reb_match_method,
                "conf": row.geom_confidence,
                "name": target.name,
                "dong": target.legal_dong,
                "address": target.address,
                "old": [round(float(row.lon), 6), round(float(row.lat), 6)],
                "new": ([round(verdict.fix.lon, 6), round(verdict.fix.lat, 6)]
                        if verdict.fix else None),
            }
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fp.flush()                              # 끊겨도 여기까지는 남는다
            done[verdict.complex_id] = rec
            counts[verdict.status] = counts.get(verdict.status, 0) + 1
            written += 1
            if written % 200 == 0:
                print(f"  진행 {written}/{len(todo)} · {counts}")

        entries = [(r.id, row_target(r), float(r.lon), float(r.lat)) for r in todo]
        try:
            sweep_name_path(entries, search, tolerance_m=tolerance, on_verdict=_record)
        except KeyboardInterrupt:
            print("[WARN] 중단됨 — 여기까지 파일에 남았습니다(--resume 으로 이어서)")
    return done


def report(done: dict[int, dict], *, tolerance: float) -> dict[str, dict[str, int]]:
    """매칭 방법 × 판정 집계 + 어긋난 건 표본 출력."""
    table: dict[str, dict[str, int]] = {}
    for rec in done.values():
        table.setdefault(rec["method"], {}).setdefault(rec["status"], 0)
        table[rec["method"]][rec["status"]] += 1

    print(f"\n[결과] 허용범위 {tolerance:.0f}m · 매칭방법별 판정")
    for method in sorted(table):
        total = sum(table[method].values())
        print(f"  {method:<14} {total:>5}건  {table[method]}")

    mismatches = sorted((r for r in done.values() if r["status"] == "mismatch"),
                        key=lambda r: -(r["distance_m"] or 0))
    print(f"\n[결과] 400m 초과 불일치 {len(mismatches)}건 (거리 내림차순 상위 25)")
    for rec in mismatches[:25]:
        flag = "" if rec["method"] in APPLIABLE_METHODS else "  ⚠️손대지않음"
        print(f"  #{rec['id']:<6} {rec['distance_m']:>8.0f}m  {rec['method']:<14} "
              f"'{rec['dong']} {rec['name']}' → {rec['address']}{flag}")
    return table


def apply_fixes(engine, done: dict[int, dict], *, backup_table: str) -> None:
    """불일치 건을 **백업 → 무효화 → 주소 경로 재확보** 순으로 반영한다.

    ⚠️ 파괴적이다. 백업과 무효화를 **한 트랜잭션**에 묶는다 — 백업만 되고 무효화가
       실패하거나 그 반대가 되면, 다음 실행이 무엇을 되돌려야 하는지 알 수 없게 된다.
    """
    from sqlalchemy import text

    targets = [rec for rec in done.values()
               if rec["status"] == "mismatch" and rec["method"] in APPLIABLE_METHODS
               and rec.get("new")]
    skipped = [rec for rec in done.values()
               if rec["status"] == "mismatch" and rec["method"] not in APPLIABLE_METHODS]
    if skipped:
        print(f"[INFO] 손대지 않는 불일치 {len(skipped)}건 "
              f"({', '.join(sorted({r['method'] for r in skipped}))}) — 주소 쪽이 "
              "틀렸을 수 있어 사람이 판단합니다")
    if not targets:
        print("[INFO] 반영할 불일치가 없습니다")
        return

    ids = sorted(rec["id"] for rec in targets)
    print(f"[APPLY] {len(ids)}건 백업 → {backup_table} → 무효화")
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS backup"))
        conn.execute(text(_BACKUP_DDL.format(table=backup_table)))
        backed = conn.execute(text(_BACKUP_INSERT.format(table=backup_table)),
                              {"ids": ids}).rowcount
        cleared = conn.execute(text(_CLEAR_GEOM), {"ids": ids}).rowcount
    print(f"[APPLY] 백업 {backed}행 · 무효화 {cleared}행")

    # 비운 **뒤에** 점유표를 다시 싣는다 — 방금 비운 점이 자기 자신을 막으면 안 된다.
    occupied = load_occupied(engine)

    entries: list[tuple[int, GeoTarget]] = []
    fixes: dict[GeoTarget, GeoFix] = {}
    missing: list[int] = []
    # 판정 시점이 아니라 **지금** 상태로 대상을 다시 읽는다(그 사이 바뀌었을 수 있다).
    with engine.connect() as conn:
        fresh = conn.execute(text("""
            SELECT c.id, c.name, c.address_jibun, r.sido, r.sigungu, c.reb_complex_id,
                   b.address_jibun AS reb_address, b.legal_dong_code AS reb_dong_code,
                   b.main_no AS reb_main_no, b.sub_no AS reb_sub_no,
                   b.is_mountain AS reb_is_mountain
            FROM complex c
            LEFT JOIN region r ON r.code = c.region_code
            JOIN reb_complex b ON b.reb_complex_id = c.reb_complex_id
            WHERE c.id = ANY(:ids)
            ORDER BY c.id
        """), {"ids": ids}).all()
    fresh_by_id = {r.id: row_target(r) for r in fresh}
    for rec in targets:
        target = fresh_by_id.get(rec["id"])
        if target is None:
            missing.append(rec["id"])
            continue
        lon, lat = rec["new"]
        fixes[target] = GeoFix(lon=float(lon), lat=float(lat), confidence="address",
                               query=target.address, matched_address=target.address,
                               source="kakao_address")
        entries.append((rec["id"], target))
    if missing:
        print(f"[WARN] 재조회에서 사라진 단지 {len(missing)}건 — 건너뜁니다")

    def _update(complex_id: int, fix: GeoFix) -> None:
        with engine.begin() as conn:
            conn.execute(text(_UPDATE_GEOM),
                         {"id": complex_id, "lon": fix.lon, "lat": fix.lat,
                          "source": fix.source, "conf": fix.confidence})

    res = enrich_geom(entries, ReplayGeocoder(fixes), _update, occupied=occupied)
    print(f"[APPLY] 재확보 {res.resolved}건 · 미확보 {res.unresolved}건"
          f"(충돌 {res.rejected_collision}) · 좌표공유 {res.shared_point}건")
    for note in res.samples[:10]:
        print(f"       {note}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="이름 경로 좌표를 주소 경로와 대조해 재검사한다(GEO-7)")
    ap.add_argument("--methods", default="name_exact,name_contains,name_fuzzy",
                    help="스윕할 매칭 방법(쉼표). 반영은 name_exact 만 — 코드로 막혀 있다")
    ap.add_argument("--tolerance", type=float, default=NAME_PATH_TOLERANCE_M,
                    help="이 거리(m)를 넘으면 불일치로 본다")
    ap.add_argument("--min-interval", type=float, default=0.25, help="요청 간 최소 간격(초)")
    ap.add_argument("--limit", type=int, default=0, help="이번 실행 최대 건수(0=전부)")
    ap.add_argument("--out", default="/tmp/geo7_sweep.jsonl", help="판정 기록 파일(JSONL)")
    ap.add_argument("--resume", action="store_true", help="기록 파일에 있는 건은 건너뛴다")
    ap.add_argument("--from-file", action="store_true",
                    help="카카오를 부르지 않고 기록 파일만 읽는다(--apply 와 함께)")
    ap.add_argument("--apply", action="store_true",
                    help="불일치를 백업 후 무효화하고 주소 경로로 재확보한다(파괴적)")
    ap.add_argument("--backup-table", default="backup.complex_geom_geo7")
    args = ap.parse_args(argv)

    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    out_path = Path(args.out)

    load_env()
    url = database_url()
    engine = make_engine(url)
    print(f"[INFO] DB {safe_dsn(url)}")

    total, with_geom = coverage(engine)
    c_rows, c_groups, c_cross, c_reb = collisions(engine)
    print(f"[INFO] 시작: 단지 {total}건 · 좌표 {with_geom}건 "
          f"({with_geom / total * 100:.2f}%) · 충돌 {c_rows}행/{c_groups}점 "
          f"· 법정동 불일치 {c_cross} · 부동산원 번호 불일치 {c_reb}")

    try:
        if args.from_file:
            done = read_verdicts(out_path)
            print(f"[INFO] 기록 파일에서 {len(done)}건 읽음 — 카카오를 부르지 않습니다")
        else:
            key = require("KAKAO_REST_API_KEY")
            done = sweep(engine, key, methods=methods, tolerance=args.tolerance,
                         min_interval=args.min_interval, out_path=out_path,
                         resume=args.resume, limit=args.limit)

        report(done, tolerance=args.tolerance)

        if args.apply:
            apply_fixes(engine, done, backup_table=args.backup_table)
        elif any(r["status"] == "mismatch" for r in done.values()):
            print("\n[DRY] 반영하지 않았습니다 — 확인 후 `--from-file --apply` 로 반영하세요")

        total2, with_geom2 = coverage(engine)
        c2 = collisions(engine)
        print(f"\n[INFO] 종료: 좌표 {with_geom}→{with_geom2}건 "
              f"({with_geom2 / total2 * 100:.2f}%) · 충돌 {c_rows}→{c2[0]}행 "
              f"· 법정동 불일치 {c_cross}→{c2[2]} · 부동산원 번호 불일치 {c_reb}→{c2[3]}")
        if c2[2]:
            print("⛔ 법정동이 다른 좌표 충돌이 생겼습니다 — GEO-1/GEO-3 회귀입니다")
        if c2[3]:
            print("⛔ 부동산원 번호가 다른 좌표 충돌이 남아 있습니다(GEO-3)")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
