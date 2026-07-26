"""부동산원 단지 마스터 CSV → `reb_complex` · `reb_building` 적재.

이 스크립트는 **원본 사실만 옮긴다.** 우리 `complex` 와의 매칭은 다음 단계
(`match_reb_complexes.py`)에서 한다 — 적재와 판단을 섞으면, 매칭 규칙을 고칠 때마다
45MB 파일을 다시 파싱해야 하고 "지금 DB 에 있는 게 어느 규칙의 결과인지" 알 수 없어진다.

범위
----
- 기본정보 307,407행 전국 중 **수도권(11·41·28) + 지정한 단지종류만** 넣는다.
  서비스 범위가 수도권 아파트이기 때문이다(CLAUDE.md). 기본값은 아파트(1)+연립(2) —
  연립까지 넣는 이유는 **부동산원이 아파트를 연립으로 분류한 경우를 진단**하기 위해서다
  (매칭 자체는 아파트만 대상으로 한다. match 스크립트의 --kinds 참고).
- 동정보는 위에서 적재한 단지의 것만 넣는다(FK).

사용
----
    export DATABASE_URL=postgresql+psycopg://user:pw@host:5432/realestate
    python scripts/load_reb_complexes.py \
        --basic data/reference/reb_complex_basic.csv \
        --dong  data/reference/reb_complex_dong.csv
    python scripts/load_reb_complexes.py --basic <파일> --dry-run   # 파싱만 확인
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import database_url, load_env, make_engine, safe_dsn  # noqa: E402

from app.ingest.reb import (  # noqa: E402
    RebBuilding,
    RebComplex,
    address_is_mountain,
    decode_csv,
    parse_basic_csv,
    parse_dong_csv,
)

#: 수도권 시도 코드(법정동코드 앞 2자리). 서비스 범위(CLAUDE.md).
CAPITAL_SIDO = ("11", "41", "28")

#: 기본 적재 대상 단지종류 — 1 아파트 · 2 연립.
DEFAULT_KINDS = ("1", "2")

_UPSERT_COMPLEX = """
    INSERT INTO reb_complex (
        reb_complex_id, parcel_id, legal_dong_code, sigungu_code, is_mountain,
        main_no, sub_no, address_jibun, name_price, name_ledger, name_road,
        kind, building_count, household_count, approved_on, loaded_at)
    VALUES (
        :reb_complex_id, :parcel_id, :legal_dong_code, :sigungu_code, :is_mountain,
        :main_no, :sub_no, :address_jibun, :name_price, :name_ledger, :name_road,
        :kind, :building_count, :household_count, :approved_on, now())
    ON CONFLICT (reb_complex_id) DO UPDATE SET
        parcel_id = EXCLUDED.parcel_id,
        legal_dong_code = EXCLUDED.legal_dong_code,
        sigungu_code = EXCLUDED.sigungu_code,
        is_mountain = EXCLUDED.is_mountain,
        main_no = EXCLUDED.main_no,
        sub_no = EXCLUDED.sub_no,
        address_jibun = EXCLUDED.address_jibun,
        name_price = EXCLUDED.name_price,
        name_ledger = EXCLUDED.name_ledger,
        name_road = EXCLUDED.name_road,
        kind = EXCLUDED.kind,
        building_count = EXCLUDED.building_count,
        household_count = EXCLUDED.household_count,
        approved_on = EXCLUDED.approved_on,
        loaded_at = now()
"""

_UPSERT_BUILDING = """
    INSERT INTO reb_building (
        reb_complex_id, name_price, name_ledger, name_road, dong_label, floors, loaded_at)
    VALUES (:reb_complex_id, :name_price, :name_ledger, :name_road,
            :dong_label, :floors, now())
    ON CONFLICT (reb_complex_id, name_price, name_ledger, name_road) DO UPDATE SET
        dong_label = EXCLUDED.dong_label,
        floors = EXCLUDED.floors,
        loaded_at = now()
"""


def complex_params(c: RebComplex) -> dict[str, object]:
    parts = c.pnu
    assert parts is not None                     # parse_basic_csv 가 이미 걸렀다
    return {
        "reb_complex_id": c.reb_id,
        "parcel_id": c.parcel_id,
        "legal_dong_code": parts.legal_dong_code,
        "sigungu_code": parts.sigungu_code,
        # 산번지 판정은 **주소 문자열을 우선**한다. 우리가 카카오에 실제로 물어보는 것은
        # 주소 문자열이고, PNU 산여부 자리에는 1·2 외의 값(3~7)도 섞여 있다(실측).
        "is_mountain": address_is_mountain(c.address_jibun) or parts.is_mountain,
        "main_no": parts.main_no,
        "sub_no": parts.sub_no,
        "address_jibun": c.address_jibun or None,
        "name_price": c.name_price or None,
        "name_ledger": c.name_ledger or None,
        "name_road": c.name_road or None,
        "kind": c.kind or None,
        "building_count": c.building_count,
        "household_count": c.household_count,
        "approved_on": c.approved_on,
    }


def building_params(b: RebBuilding) -> dict[str, object]:
    return {
        "reb_complex_id": b.reb_id,
        # UNIQUE 키의 일부다 — NULL 로 두면 중복 판정이 무너지므로 빈 문자열을 유지한다.
        "name_price": b.name_price,
        "name_ledger": b.name_ledger,
        "name_road": b.name_road,
        "dong_label": b.label,
        "floors": b.floors,
    }


def _read(path: Path) -> str:
    if not path.exists():
        raise SystemExit(
            f"[FAIL] 파일이 없습니다: {path}\n"
            "       python scripts/fetch_reb_complex_master.py 로 먼저 받으세요.")
    return decode_csv(path.read_bytes())


def _insert(engine, sql: str, rows: list[dict[str, object]], *, chunk: int = 2000) -> int:
    from sqlalchemy import text

    stmt = text(sql)
    done = 0
    for i in range(0, len(rows), chunk):
        with engine.begin() as conn:
            conn.execute(stmt, rows[i:i + chunk])
        done += len(rows[i:i + chunk])
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="부동산원 단지 마스터 적재")
    ap.add_argument("--basic", required=True, help="기본정보 CSV")
    ap.add_argument("--dong", help="동정보 CSV (선택)")
    ap.add_argument("--kinds", default=",".join(DEFAULT_KINDS),
                    help="적재할 단지종류 (1아파트,2연립,3다세대)")
    ap.add_argument("--all-regions", action="store_true", help="전국 (기본: 수도권만)")
    ap.add_argument("--dry-run", action="store_true", help="적재하지 않고 파싱만")
    args = ap.parse_args(argv)

    kinds = tuple(k.strip() for k in args.kinds.split(",") if k.strip())

    print(f"[INFO] 기본정보 파싱: {args.basic}")
    parsed = parse_basic_csv(_read(Path(args.basic)))
    print(f"       전체 {len(parsed):,}건")

    selected = [c for c in parsed
                if c.kind in kinds
                and (args.all_regions or c.legal_dong_code[:2] in CAPITAL_SIDO)]
    by_kind = Counter(c.kind for c in selected)
    scope = "전국" if args.all_regions else "수도권"
    print(f"       적재 대상({scope} · 종류 {','.join(kinds)}): {len(selected):,}건 "
          f"— {dict(sorted(by_kind.items()))}")
    if not selected:
        raise SystemExit("[FAIL] 적재할 행이 없습니다 — 파일·옵션을 확인하세요.")

    no_address = sum(1 for c in selected if not c.address_jibun)
    print(f"       주소 없음 {no_address:,}건 (이 단지는 주소 지오코딩 대상이 아닙니다)")

    buildings: list[RebBuilding] = []
    if args.dong:
        print(f"[INFO] 동정보 파싱: {args.dong}")
        keep = {c.reb_id for c in selected}
        all_dong = parse_dong_csv(_read(Path(args.dong)))
        buildings = [b for b in all_dong if b.reb_id in keep]
        readable = sum(1 for b in buildings if b.label)
        print(f"       전체 {len(all_dong):,}건 · 대상 단지분 {len(buildings):,}건 "
              f"· 동 표기를 읽어낸 것 {readable:,}건 "
              f"({readable / len(buildings) * 100 if buildings else 0:.1f}%)")
        print("       ⚠️ 읽어내지 못한 표기는 dong_label=NULL 로 남습니다 — "
              "building 으로 승격하지 않습니다(없는 동을 만들지 않는다).")

    if args.dry_run:
        for c in selected[:3]:
            print(f"       예시 {c.reb_id} {c.legal_dong_code} {c.address_jibun} "
                  f"| {c.names} | 동{c.building_count} 세대{c.household_count} "
                  f"| {c.approved_on}")
        print("[DONE] --dry-run 이므로 적재하지 않았습니다.")
        return 0

    load_env()
    url = database_url()
    engine = make_engine(url)
    print(f"[INFO] DB {safe_dsn(url)}")
    try:
        n = _insert(engine, _UPSERT_COMPLEX, [complex_params(c) for c in selected])
        print(f"[DONE] reb_complex 적재 {n:,}건")
        if buildings:
            m = _insert(engine, _UPSERT_BUILDING, [building_params(b) for b in buildings])
            print(f"[DONE] reb_building 적재 {m:,}건")
    finally:
        engine.dispose()

    print("       다음: python scripts/match_reb_complexes.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
