"""우리 `complex` ↔ 부동산원 `reb_complex` 매칭 · 동수/세대수/사용승인일 보강.

무엇을 하는가
-------------
1. 같은 **법정동코드** 안에서만 단지명을 대조해 매칭한다(app/ingest/reb.match_complex).
2. 매칭된 단지에 `complex.reb_complex_id` · `reb_match_method` · `reb_matched_at` 을 쓴다.
3. 부동산원 동수·세대수·사용승인일을 `complex.total_buildings` · `total_households` ·
   `built_year` 로 옮긴다.
4. 부동산원 동 목록을 `building` 으로 승격한다 — **읽어낸 표기만**(`dong_label IS NOT NULL`).

⚠️ 애매하면 매칭하지 않는다
---------------------------
한 단계에서 후보가 둘 이상이면 'ambiguous' 로 세고 **아무것도 쓰지 않는다.**
'가락동 우성' 을 '가락우성1차' 나 '가락우성2차' 중 하나에 임의로 붙이면
좌표·동수·세대수·사용승인일이 통째로 남의 단지 것이 된다. GEO-1 이 "틀린 걸 넣느니
비운다"로 정리된 직후에 그 원칙을 뒤집을 수는 없다.

⚠️ 동(棟)에 대해
----------------
- `complex.total_buildings` 는 **개수**다. 개수를 안다고 목록을 아는 게 아니다.
- `building` 행은 부동산원 동정보에서 **실제로 읽어낸 동만** 만든다. 개수만큼
  '101동…105동'을 지어내지 않는다(F4 가 거짓 근거 위에서 돌게 된다).
- MOLIT 이름 오염으로 한 단지가 여러 `complex` 행으로 갈라진 경우, 갈라진 행 각각에
  같은 동 목록이 붙는다. 그 행들의 실거래(`trade.apt_dong`)도 같은 단지 것이므로
  "이 단지에 동이 몇 개인데 몇 개를 측정했나"를 묻는 데는 이게 맞다.

사용
----
    export DATABASE_URL=postgresql+psycopg://user:pw@host:5432/realestate
    python scripts/match_reb_complexes.py --dry-run    # 쓰지 않고 매칭률만
    python scripts/match_reb_complexes.py              # 매칭 + 보강 + building 적재
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import database_url, load_env, make_engine, safe_dsn  # noqa: E402

from app.ingest.reb import REB_KIND_APT, RebComplex, match_complex  # noqa: E402

#: 매칭 대상 단지종류. 우리 실거래는 MOLIT '아파트' API 에서 왔으므로 아파트만 본다.
#: 연립(2)까지 열면 후보가 늘어 애매 판정만 늘고, 잘못 붙으면 다른 건물이 된다.
DEFAULT_MATCH_KINDS = (REB_KIND_APT,)

#: ⚠️ region_code 가 NULL 인 단지도 **뺴지 않고** 읽는다. 빼면 분모가 조용히 줄어
#:    "6,538 중 몇 건"이라는 질문에 6,534 로 답하게 된다 — 매칭할 수 없는 단지도
#:    매칭 실패로 세는 것이 정직하다.
_SELECT_COMPLEXES = """
    SELECT c.id, c.name, c.region_code, c.address_jibun
    FROM complex c
    ORDER BY c.id
"""

_SELECT_REB = """
    SELECT reb_complex_id, parcel_id, legal_dong_code,
           name_price, name_ledger, name_road, kind
    FROM reb_complex
    WHERE kind = ANY(:kinds)
"""

_UPDATE_MATCH = """
    UPDATE complex
    SET reb_complex_id = :reb_id,
        reb_match_method = :method,
        reb_matched_at = now(),
        updated_at = now()
    WHERE id = :id
"""

#: 부동산원 값으로 보강한다. **NULL 로 덮지 않는다** — 부동산원이 모르는 값을
#: 우리가 알고 있을 수도 있고, 모름으로 되돌리는 건 정보를 잃는 일이다.
_ENRICH = """
    UPDATE complex c
    SET total_buildings  = COALESCE(b.building_count, c.total_buildings),
        total_households = COALESCE(b.household_count, c.total_households),
        built_year       = COALESCE(EXTRACT(YEAR FROM b.approved_on)::int, c.built_year),
        updated_at       = now()
    FROM reb_complex b
    WHERE b.reb_complex_id = c.reb_complex_id
      AND (b.building_count IS NOT NULL OR b.household_count IS NOT NULL
           OR b.approved_on IS NOT NULL)
"""

#: 부동산원 동 목록 → building. `dong_label IS NOT NULL` 이 핵심이다(읽어낸 것만).
#: 같은 단지에 같은 라벨이 둘 이상이면(원본 표기 차이) 하나로 접는다 — DISTINCT ON.
_PROMOTE_BUILDINGS = """
    INSERT INTO building (complex_id, name, floors, source)
    SELECT DISTINCT ON (c.id, rb.dong_label)
           c.id, rb.dong_label, rb.floors, 'reb_dong'
    FROM complex c
    JOIN reb_building rb ON rb.reb_complex_id = c.reb_complex_id
    WHERE c.reb_complex_id IS NOT NULL AND rb.dong_label IS NOT NULL
    ORDER BY c.id, rb.dong_label, rb.floors DESC NULLS LAST
    ON CONFLICT (complex_id, name) DO UPDATE SET
        floors = EXCLUDED.floors,
        source = EXCLUDED.source
"""


def load_candidates(engine, kinds: tuple[str, ...]) -> dict[str, list[RebComplex]]:
    from sqlalchemy import text

    by_dong: dict[str, list[RebComplex]] = defaultdict(list)
    with engine.connect() as conn:
        for r in conn.execute(text(_SELECT_REB), {"kinds": list(kinds)}):
            by_dong[r.legal_dong_code].append(RebComplex(
                reb_id=r.reb_complex_id, parcel_id=r.parcel_id,
                name_price=r.name_price or "", name_ledger=r.name_ledger or "",
                name_road=r.name_road or "", kind=r.kind or ""))
    return dict(by_dong)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="complex ↔ 부동산원 단지 매칭")
    ap.add_argument("--kinds", default=",".join(DEFAULT_MATCH_KINDS),
                    help="매칭 대상 단지종류 (기본 1=아파트)")
    ap.add_argument("--dry-run", action="store_true", help="쓰지 않고 매칭률만 측정")
    ap.add_argument("--no-enrich", action="store_true",
                    help="동수·세대수·사용승인일 보강과 building 승격을 건너뛴다")
    ap.add_argument("--samples", type=int, default=8, help="애매 사례 표본 출력 수")
    args = ap.parse_args(argv)

    kinds = tuple(k.strip() for k in args.kinds.split(",") if k.strip())

    load_env()
    url = database_url()
    engine = make_engine(url)
    print(f"[INFO] DB {safe_dsn(url)}")

    from sqlalchemy import text

    try:
        by_dong = load_candidates(engine, kinds)
        n_cand = sum(len(v) for v in by_dong.values())
        print(f"[INFO] 부동산원 후보 {n_cand:,}건 · 법정동 {len(by_dong):,}개 "
              f"(종류 {','.join(kinds)})")

        with engine.connect() as conn:
            rows = conn.execute(text(_SELECT_COMPLEXES)).all()
        print(f"[INFO] 우리 단지 {len(rows):,}건")

        status = Counter()
        methods = Counter()
        no_candidate_dong = 0
        updates: list[dict[str, object]] = []
        ambiguous_samples: list[str] = []

        for row in rows:
            candidates = by_dong.get((row.region_code or "").strip(), [])
            if not candidates:
                no_candidate_dong += 1
            result = match_complex(row.name or "", candidates)
            status[result.status] += 1
            if result.matched:
                methods[result.method] += 1
                updates.append({"id": row.id, "reb_id": result.reb_id,
                                "method": result.method})
            elif result.status == "ambiguous" and len(ambiguous_samples) < args.samples:
                ambiguous_samples.append(
                    f"애매 #{row.id} '{row.address_jibun} {row.name}' → "
                    f"{result.method} 단계에서 후보 {len(result.rivals)}개 "
                    f"{result.rivals}")

        total = len(rows)
        matched = status["matched"]
        print(f"\n[매칭] 전체 {total:,} · 성공 {matched:,}"
              f"({matched / total * 100 if total else 0:.1f}%) "
              f"· 애매 {status['ambiguous']:,} · 실패 {status['unmatched']:,}")
        print(f"       성공 내역: {dict(sorted(methods.items()))}")
        print(f"       실패 중 '해당 법정동에 부동산원 후보가 아예 없음' {no_candidate_dong:,}건")
        for s in ambiguous_samples:
            print(f"       {s}")
        print("       ⚠️ 애매·실패 건은 아무것도 쓰지 않습니다 — "
              "틀린 매칭은 틀린 좌표·틀린 동수가 됩니다.")

        if args.dry_run:
            print("[DONE] --dry-run 이므로 DB 를 쓰지 않았습니다.")
            return 0

        with engine.begin() as conn:
            for i in range(0, len(updates), 1000):
                conn.execute(text(_UPDATE_MATCH), updates[i:i + 1000])
        print(f"[DONE] complex.reb_complex_id 반영 {len(updates):,}건")

        if not args.no_enrich:
            with engine.begin() as conn:
                enriched = conn.execute(text(_ENRICH)).rowcount
                promoted = conn.execute(text(_PROMOTE_BUILDINGS)).rowcount
            print(f"[DONE] 동수·세대수·사용승인일 보강 {enriched:,}건")
            print(f"[DONE] building 승격(읽어낸 동만) {promoted:,}행")

        with engine.connect() as conn:
            stat = conn.execute(text("""
                SELECT count(*) FILTER (WHERE reb_complex_id IS NOT NULL) AS matched,
                       count(*) FILTER (WHERE total_buildings IS NOT NULL) AS with_dong,
                       count(*) FILTER (WHERE total_households IS NOT NULL) AS with_hh,
                       count(*) FILTER (WHERE built_year IS NOT NULL) AS with_year,
                       count(*) AS total
                FROM complex
            """)).one()
            n_building = conn.execute(text("SELECT count(*) FROM building")).scalar_one()
            n_bcomplex = conn.execute(
                text("SELECT count(DISTINCT complex_id) FROM building")).scalar_one()
        print(f"\n[상태] 단지 {stat.total:,} · 부동산원 매칭 {stat.matched:,} "
              f"· 동수 확보 {stat.with_dong:,} · 세대수 {stat.with_hh:,} "
              f"· 사용승인연도 {stat.with_year:,}")
        print(f"       building {n_building:,}행 · 동 목록을 아는 단지 {n_bcomplex:,}개")
        print("       (동수를 아는 단지 ≠ 동 목록을 아는 단지 — 후자가 더 적은 게 정상입니다)")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
