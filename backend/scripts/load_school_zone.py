"""초등학교 학구도 적재 — `data/raw/school_zone/*` → school_district · poi(category=school).

    # ① 원천 확인 후 SQL 만 만든다(DB 접속 없음). 파싱은 **여기서** 끝난다.
    python scripts/load_school_zone.py --src data/raw/school_zone --sql-out /tmp/sz.sql.gz

    # ② 서버로 올려서 적재 (좌표변환·유효화는 PostGIS 가 한다)
    gunzip -c sz.sql.gz | psql -v ON_ERROR_STOP=1 -U realestate -d realestate

    # 또는 DB 에 직접 (로컬 테스트 DB 처럼 메모리 여유가 있을 때)
    python scripts/load_school_zone.py --src data/raw/school_zone

왜 SQL 파일 경유인가 — 운영 VPS 메모리 제약
--------------------------------------------
대상 VPS 는 가용 메모리가 **160MB 안팎**이고 실서비스가 같이 돈다. 통학구역 SHP 는
압축 35MB · 해제 55MB 라, 서버에서 파싱하면 zip 버퍼 + shp 본문만으로 90MB 를 먹는다.
반면 psql 로 SQL 을 흘려 넣으면 문장 단위로 처리돼 메모리가 평평하다(실측 백엔드 26MB).
그래서 **파싱은 개발기, 좌표변환·유효화·적재는 서버 PostGIS** 로 나눈다.
geopandas/fiona/GDAL 은 설치하지 않는다(디스크 300MB+ · import 만으로 100MB+).

멱등 (012)
----------
`(source, source_ref)` 유니크 위 upsert 다. 학구도는 매년 **3월·9월** 재배포되므로
재실행이 행을 쌓으면 안 된다. source_ref 는 `kesi:{학구ID}/{학교ID}` —
공동학구가 있어 학구ID 단독으로는 키가 되지 못한다(012 주석).

⚠️ 좌표변환을 파이썬에서 하지 않는다
   `ST_Transform(5186 → 4326)` 을 PostGIS 가 수행한다. 파이썬에서 TM 역투영을
   재구현하면 pyproj 없이는 검증할 방법이 없고, 틀려도 좌표가 '그럴듯하게' 나온다.

⚠️ 자기교차 링 보정
   원천 폴리곤 중 일부(실측 0.5%)는 링이 자기교차한다. 그대로 넣으면
   `ST_Contains` 가 GEOS 예외를 던져 **입지 분석 전체가 실패**한다. 그래서
   `ST_Multi(ST_CollectionExtract(ST_MakeValid(...), 3))` 을 거친다.
   `ST_CollectionExtract(..., 3)` 은 MakeValid 가 돌려줄 수 있는
   GeometryCollection 에서 **면(폴리곤)만** 뽑는다 — 이게 없으면 선·점이 섞여
   `geometry(MultiPolygon,4326)` 제약에 걸려 적재가 통째로 실패한다.
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import _common  # noqa: F401  (import 부작용: 로깅 억제·마스킹 설치)
from _common import REPO_ROOT, load_env, make_engine

from app.ingest.school_zone import (
    CAPITAL_AREA_SD,
    ELEMENTARY,
    SOURCE_KESI,
    SchoolDistrictRecord,
    build_records,
    parse_link_csv,
    parse_school_location_csv,
    parse_zone_shapefile,
)

logger = logging.getLogger("scripts.load_school_zone")

SRC_DIR = REPO_ROOT / "data" / "raw" / "school_zone"

FILE_ZONE = "elementary_zone.zip"
FILE_LINK = "school_zone_link.csv"
FILE_LOCATION = "school_location.csv"

#: 한 INSERT 문에 넣을 행 수. 학구 하나의 hex 가 평균 7KB 라 크게 잡으면 문장이 비대해진다.
STAGE_BATCH = 25


# ---------------------------------------------------------------------------
# 원천 → 레코드
# ---------------------------------------------------------------------------

def read_records(src: Path, *, sido_codes=CAPITAL_AREA_SD) -> tuple[list[SchoolDistrictRecord], Any]:
    for name in (FILE_ZONE, FILE_LINK, FILE_LOCATION):
        if not (src / name).exists():
            raise SystemExit(
                f"[FAIL] 원천이 없습니다: {src / name}\n"
                f"       먼저 실행: python scripts/fetch_school_zone.py")

    zones = parse_zone_shapefile((src / FILE_ZONE).read_bytes(), sido_codes=sido_codes)
    links = parse_link_csv((src / FILE_LINK).read_bytes(), level=ELEMENTARY)
    locations = parse_school_location_csv((src / FILE_LOCATION).read_bytes(),
                                          level=ELEMENTARY)
    logger.info("원천 — 학구 폴리곤 %d · 연계(초등) %d · 학교좌표(초등) %d",
                len(zones), len(links), len(locations))
    records, report = build_records(zones, links, locations, level=ELEMENTARY)
    if report.ambiguous_zones:
        logger.warning("학구ID 가 서로 다른 구역 둘에 쓰인 원천 결함 %d건 — 배정을 단정할 수 "
                       "없어 버립니다(해당 단지는 '학구도 미포함'이 됩니다): %s",
                       len(report.ambiguous_zones), report.ambiguous_zones)
    if report.zones_without_link:
        logger.warning("연계정보에 없는 학구 %d개 — 배정 학교를 알 수 없어 건너뜁니다 (예: %s)",
                       len(report.zones_without_link), report.zones_without_link[:5])
    if report.schools_without_location:
        logger.warning("좌표가 없는 학교 %d건 — 거리 계산이 불가능해 건너뜁니다 (예: %s)",
                       len(report.schools_without_location),
                       report.schools_without_location[:5])
    if not records:
        raise SystemExit("[FAIL] 적재할 레코드가 0건입니다 — 원천·필터를 확인하세요.")
    return records, report


# ---------------------------------------------------------------------------
# SQL 생성 — 직접 적재와 **같은 문장**을 쓴다(두 경로가 갈라지지 않게)
# ---------------------------------------------------------------------------

_STAGE_DDL = """
CREATE TEMP TABLE _sz_stage (
    source_ref        text,
    zone_id           text,
    zone_name         text,
    school_source_ref text,
    school_name       text,
    lat               double precision,
    lon               double precision,
    as_of             date,
    attrs             jsonb,
    wkb               text
) ON COMMIT DROP;
"""

#: 결과 집계를 담는 자리. SQL 파일 경로도 직접 적재와 **같은 통계**를 내고
#: 같은 `ingest_log` 행을 남기게 하려고 둔다(두 경로의 관측이 갈라지면 안 된다).
_STATS_DDL = """
CREATE TEMP TABLE _sz_stats (k text PRIMARY KEY, v bigint) ON COMMIT DROP;
"""

#: 5186 → 4326 변환 + 자기교차 보정. `was_valid` 를 남겨 **보정 건수를 실증**한다.
_GEOM_DDL = """
CREATE TEMP TABLE _sz_geom ON COMMIT DROP AS
SELECT source_ref, school_source_ref, as_of,
       ST_IsValid(g) AS was_valid,
       ST_Multi(ST_CollectionExtract(ST_MakeValid(g), 3)) AS geom
FROM (
    SELECT source_ref, school_source_ref, as_of,
           ST_Transform(
               ST_SetSRID(ST_GeomFromWKB(decode(wkb, 'hex')), 5186), 4326) AS g
    FROM _sz_stage
) t;
"""

#: 학교 POI upsert. 같은 학교가 여러 학구에 걸릴 수 있어 **배치 안에서 먼저 접는다** —
#: 한 INSERT 가 같은 대상 행을 두 번 건드리면 PostgreSQL 이 트랜잭션을 통째로 깬다.
_POI_UPSERT = f"""
WITH src AS (
    SELECT DISTINCT ON (school_source_ref)
           school_source_ref, school_name, lat, lon, attrs
    FROM _sz_stage
    ORDER BY school_source_ref
), up AS (
    INSERT INTO poi (category, name, geom, attrs, source, source_ref)
    SELECT 'school', school_name,
           ST_SetSRID(ST_MakePoint(lon, lat), 4326), attrs,
           '{SOURCE_KESI}', school_source_ref
    FROM src
    ON CONFLICT (source, source_ref) WHERE source_ref IS NOT NULL
    DO UPDATE SET name     = EXCLUDED.name,
                  geom     = EXCLUDED.geom,
                  attrs    = EXCLUDED.attrs,
                  category = EXCLUDED.category
    RETURNING (xmax = 0) AS inserted
), agg AS (
    SELECT count(*) FILTER (WHERE inserted)     AS ins,
           count(*) FILTER (WHERE NOT inserted) AS upd
    FROM up
)
INSERT INTO _sz_stats (k, v)
SELECT x.k, x.v
FROM agg, LATERAL (VALUES ('poi_inserted', agg.ins),
                          ('poi_updated',  agg.upd)) AS x(k, v);
"""

_DISTRICT_UPSERT = f"""
WITH up AS (
    INSERT INTO school_district (school_poi_id, geom, source, as_of, source_ref)
    SELECT p.id, g.geom, '{SOURCE_KESI}', g.as_of, g.source_ref
    FROM _sz_geom g
    JOIN poi p ON p.source = '{SOURCE_KESI}' AND p.source_ref = g.school_source_ref
    ON CONFLICT (source, source_ref) WHERE source_ref IS NOT NULL
    DO UPDATE SET school_poi_id = EXCLUDED.school_poi_id,
                  geom          = EXCLUDED.geom,
                  as_of         = EXCLUDED.as_of
    RETURNING (xmax = 0) AS inserted
), agg AS (
    SELECT count(*) FILTER (WHERE inserted)     AS ins,
           count(*) FILTER (WHERE NOT inserted) AS upd
    FROM up
)
INSERT INTO _sz_stats (k, v)
SELECT x.k, x.v
FROM agg, LATERAL (VALUES ('district_inserted', agg.ins),
                          ('district_updated',  agg.upd)) AS x(k, v);
"""

_MAKEVALID_COUNT = """
INSERT INTO _sz_stats (k, v)
SELECT x.k, x.v
FROM (
    SELECT count(*) FILTER (WHERE NOT was_valid) AS fixed,
           count(*)                              AS rows_all,
           count(*) FILTER (WHERE geom IS NULL OR ST_IsEmpty(geom)) AS empty
    FROM _sz_geom
) t, LATERAL (VALUES ('makevalid_fixed', t.fixed),
                     ('geom_rows',       t.rows_all),
                     ('geom_empty',      t.empty)) AS x(k, v);
"""

#: 이번 배포분에 없는 옛 행. **지우지 않고 센다** — 학구 폐지와 '원천 일시 누락'을
#: 구분할 수 없는데 지우면, 어느 날 원천이 반쪽만 배포됐을 때 배정이 통째로 사라진다.
_STALE_COUNT = f"""
INSERT INTO _sz_stats (k, v)
SELECT 'stale', count(*)
FROM school_district d
WHERE d.source = '{SOURCE_KESI}'
  AND d.source_ref IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM _sz_stage s WHERE s.source_ref = d.source_ref);
"""

#: 원장 한 행. **조용한 실패 금지** — psql 로 흘려 넣어도 흔적이 남아야 한다.
#: `now()` 는 트랜잭션 시작 시각이라 적재 시작 시각으로 정확하다.
_INGEST_LOG = f"""
INSERT INTO ingest_log (source, target_table, started_at, finished_at,
                        rows_ok, rows_failed, status, message)
SELECT '{SOURCE_KESI}:elementary', 'school_district',
       now(), clock_timestamp(),
       pg_temp.s('district_inserted') + pg_temp.s('district_updated'),
       pg_temp.s('geom_empty'),
       CASE WHEN pg_temp.s('geom_empty') > 0 THEN 'partial' ELSE 'ok' END,
       format('학구도 신규 %s / 갱신 %s · 학교 POI 신규 %s / 갱신 %s'
              ' · 자기교차 보정 %s · 이번 배포분에 없는 옛 행 %s',
              pg_temp.s('district_inserted'), pg_temp.s('district_updated'),
              pg_temp.s('poi_inserted'),      pg_temp.s('poi_updated'),
              pg_temp.s('makevalid_fixed'),   pg_temp.s('stale'));
"""

#: 통계 조회 헬퍼. 임시 함수라 세션이 끝나면 사라진다.
#: ⚠️ 반드시 `pg_temp.` 로 한정해 부른다 — 스키마 한정 없이 부르는 임시 함수는
#:    PostgreSQL 이 보안상 해석하지 않는다.
_STATS_FN = """
CREATE FUNCTION pg_temp.s(text) RETURNS bigint LANGUAGE sql STABLE AS
    $fn$ SELECT coalesce((SELECT v FROM _sz_stats WHERE k = $1), 0) $fn$;
"""

#: 마지막에 사람이 볼 요약.
_STATS_SHOW = "SELECT k AS 항목, v AS 값 FROM _sz_stats ORDER BY k;\n"

#: 적재 본체. **두 경로가 이 순서를 공유한다** — SQL 파일이든 직접 적재든 같은 문장이
#: 같은 순서로 돈다. 갈라지면 "파일로는 되는데 직접은 안 된다"가 생긴다.
_PIPELINE = (_MAKEVALID_COUNT, _POI_UPSERT, _DISTRICT_UPSERT, _STALE_COUNT)


def _literal(value: Any) -> str:
    """SQL 리터럴. 문자열은 달러인용으로 감싸 따옴표 이스케이프 사고를 없앤다."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value)
    if "$sz$" in text:                        # 실데이터에 나올 리 없지만 방어한다
        raise ValueError(f"달러인용 구분자와 충돌하는 값: {text[:40]!r}")
    return f"$sz${text}$sz$"


def _stage_values(record: SchoolDistrictRecord) -> str:
    return "(" + ", ".join((
        _literal(record.source_ref),
        _literal(record.zone_id),
        _literal(record.zone_name),
        _literal(record.school_source_ref),
        _literal(record.school_name),
        _literal(record.lat),
        _literal(record.lon),
        f"CAST({_literal(record.as_of)} AS date)",
        f"CAST({_literal(json.dumps(record.attrs, ensure_ascii=False))} AS jsonb)",
        _literal(record.wkb_hex),
    )) + ")"


def iter_sql(records: Sequence[SchoolDistrictRecord], *,
             batch: int = STAGE_BATCH) -> Iterator[str]:
    """적재 SQL 을 조각으로 흘려 준다(전문을 메모리에 쌓지 않는다)."""
    yield "-- 초등학교 학구도 적재 (scripts/load_school_zone.py 생성)\n"
    yield f"-- 레코드 {len(records):,}건 · 원천 {SOURCE_KESI} · 학교급 {ELEMENTARY}\n"
    yield "BEGIN;\n"
    yield _STAGE_DDL
    yield _STATS_DDL
    for i in range(0, len(records), batch):
        chunk = records[i:i + batch]
        yield ("INSERT INTO _sz_stage VALUES\n"
               + ",\n".join(_stage_values(r) for r in chunk) + ";\n")
    yield _GEOM_DDL
    for statement in _PIPELINE:
        yield statement
    yield _STATS_FN
    yield _INGEST_LOG
    yield _STATS_SHOW
    yield "COMMIT;\n"


def write_sql(records: Sequence[SchoolDistrictRecord], out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if out.suffix == ".gz" else open
    with opener(out, "wt", encoding="utf-8") as fh:      # type: ignore[operator]
        for piece in iter_sql(records):
            fh.write(piece)
    logger.info("SQL 생성 — %s (%.1f MB)", out, out.stat().st_size / 1e6)
    return out


# ---------------------------------------------------------------------------
# 직접 적재
# ---------------------------------------------------------------------------

def load_to_db(engine: Any, records: Sequence[SchoolDistrictRecord]) -> dict[str, int]:
    """SQL 생성 경로와 **같은 문장**으로 적재한다. 결과 통계를 돌려준다."""
    from sqlalchemy import text

    stats: dict[str, int] = {}
    with engine.begin() as conn:
        conn.execute(text(_STAGE_DDL))
        conn.execute(text(_STATS_DDL))
        params = [{
            "source_ref": r.source_ref, "zone_id": r.zone_id, "zone_name": r.zone_name,
            "school_source_ref": r.school_source_ref, "school_name": r.school_name,
            "lat": r.lat, "lon": r.lon, "as_of": r.as_of,
            "attrs": json.dumps(r.attrs, ensure_ascii=False), "wkb": r.wkb_hex,
        } for r in records]
        insert = text("""
            INSERT INTO _sz_stage VALUES
            (:source_ref, :zone_id, :zone_name, :school_source_ref, :school_name,
             :lat, :lon, CAST(:as_of AS date), CAST(:attrs AS jsonb), :wkb)
        """)
        for i in range(0, len(params), STAGE_BATCH):
            conn.execute(insert, params[i:i + STAGE_BATCH])

        conn.execute(text(_GEOM_DDL))
        for statement in _PIPELINE:
            conn.execute(text(statement))
        # ingest_log 도 **같은 SQL** 로 남긴다 — psql 경로와 원장이 갈라지지 않는다.
        conn.execute(text(_STATS_FN))
        conn.execute(text(_INGEST_LOG))
        stats = {r.k: int(r.v) for r in conn.execute(text(
            "SELECT k, v FROM _sz_stats")).all()}

    logger.info("학구도 신규 %s / 갱신 %s · 학교 POI 신규 %s / 갱신 %s"
                " · 자기교차 보정 %s · 이번 배포분에 없는 옛 행 %s",
                stats.get("district_inserted"), stats.get("district_updated"),
                stats.get("poi_inserted"), stats.get("poi_updated"),
                stats.get("makevalid_fixed"), stats.get("stale"))
    return stats


# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="초등학교 학구도 적재")
    ap.add_argument("--src", default=str(SRC_DIR), help="fetch_school_zone.py 저장 폴더")
    ap.add_argument("--sql-out", help="적재 SQL 을 파일로 저장(.gz 지원). DB 접속 안 함")
    ap.add_argument("--nationwide", action="store_true",
                    help="수도권 필터 해제(권장하지 않음 — DB 5배)")
    args = ap.parse_args(argv)

    load_env()
    records, report = read_records(Path(args.src),
                                   sido_codes=None if args.nationwide else CAPITAL_AREA_SD)
    schools = {r.school_source_ref for r in records}
    logger.info("레코드 %d건 (학구 %d · 학교 %d · 기준일자 %s)",
                len(records), len({r.zone_id for r in records}), len(schools),
                sorted({r.as_of for r in records}))

    if args.sql_out:
        write_sql(records, Path(args.sql_out))
        print("\n       다음(서버에서): "
              "gunzip -c sz.sql.gz | psql -v ON_ERROR_STOP=1 -U realestate -d realestate")
        return 0

    stats = load_to_db(make_engine(), records)
    print(f"[DONE] school_district 신규 {stats['district_inserted']} / "
          f"갱신 {stats['district_updated']} · "
          f"poi(school) 신규 {stats['poi_inserted']} / 갱신 {stats['poi_updated']} · "
          f"자기교차 보정 {stats['makevalid_fixed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
