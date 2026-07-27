"""학구도 적재 — `data/raw/school_zone/*` → school_district · school_district_member · poi.

    # ① 원천 확인 후 SQL 만 만든다(DB 접속 없음). 파싱은 **여기서** 끝난다.
    python scripts/load_school_zone.py --level all --src data/raw/school_zone \
           --sql-out /tmp/sz.sql.gz

    # ② 서버로 올려서 적재 (좌표변환·유효화는 PostGIS 가 한다)
    gunzip -c sz.sql.gz | psql -v ON_ERROR_STOP=1 -U realestate -d realestate

    # 또는 DB 에 직접 (로컬 테스트 DB 처럼 메모리 여유가 있을 때)
    python scripts/load_school_zone.py --level middle --src data/raw/school_zone

학교급마다 **적재 모양이 다르다** (같게 만들면 거짓말이 된다)
--------------------------------------------------------------
  초등 통학구역 : 1행 = (구역, 배정 학교). `school_district.school_poi_id` 에 학교.
  중·고 학교군 : 1행 = 구역. `school_poi_id` 는 NULL 이고 후보 학교는
                 `school_district_member` 에 N행. 학교군은 구역 하나에 학교가
                 수도권 평균 4.46곳(중)·14.39곳(고) 걸리며(실측), 그중 어디로
                 배정되는지는 **원천에 없다**. 단수 컬럼에 넣을 수 없는 이유다.
  → migration 013 이 먼저 적용돼 있어야 한다(school_level·zone_kind·member 표).

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
    HIGH,
    MIDDLE,
    SOURCE_KESI,
    ZONE_KIND,
    SchoolDistrictRecord,
    SchoolZoneRecord,
    build_records,
    build_zone_records,
    parse_link_csv,
    parse_school_location_csv,
    parse_zone_shapefile,
)

logger = logging.getLogger("scripts.load_school_zone")

SRC_DIR = REPO_ROOT / "data" / "raw" / "school_zone"

FILE_LINK = "school_zone_link.csv"
FILE_LOCATION = "school_location.csv"

#: 급 키 → (학교급 문자열, SHP 파일명). fetch_school_zone.py 의 Dataset.key 와 맞춘다.
LEVEL_FILES: dict[str, tuple[str, str]] = {
    "elementary": (ELEMENTARY, "elementary_zone.zip"),
    "middle": (MIDDLE, "middle_zone.zip"),
    "high": (HIGH, "high_zone.zip"),
}

#: 하위호환 — 이 상수를 쓰던 예전 호출부가 있다면 초등 파일을 가리킨다.
FILE_ZONE = LEVEL_FILES["elementary"][1]

#: 한 INSERT 문에 넣을 행 수. 학구 하나의 hex 가 평균 7KB 라 크게 잡으면 문장이 비대해진다.
STAGE_BATCH = 25


# ---------------------------------------------------------------------------
# 원천 → 레코드
# ---------------------------------------------------------------------------

def _require(src: Path, name: str) -> Path:
    path = src / name
    if not path.exists():
        raise SystemExit(
            f"[FAIL] 원천이 없습니다: {path}\n"
            f"       먼저 실행: python scripts/fetch_school_zone.py")
    return path


def _log_losses(level: str, report: Any) -> None:
    """버린 것을 **세어서** 남긴다(조용한 유실 금지)."""
    if report.ambiguous_zones:
        logger.warning("[%s] 학구ID 가 서로 다른 구역 둘에 쓰인 원천 결함 %d건 — 배정을 단정할 수 "
                       "없어 버립니다(해당 단지는 '학구도 미포함'이 됩니다): %s",
                       level, len(report.ambiguous_zones), report.ambiguous_zones)
    if report.zones_without_link:
        logger.warning("[%s] 연계정보에 없는 학구 %d개 — 소속 학교를 알 수 없어 건너뜁니다 (예: %s)",
                       level, len(report.zones_without_link), report.zones_without_link[:5])
    if report.schools_without_location:
        logger.warning("[%s] 좌표가 없는 학교 %d건 — 거리 계산이 불가능해 건너뜁니다 (예: %s)",
                       level, len(report.schools_without_location),
                       report.schools_without_location[:5])
    if getattr(report, "zones_without_member", None):
        logger.warning("[%s] 후보 학교 좌표가 하나도 없어 버린 구역 %d개: %s",
                       level, len(report.zones_without_member),
                       report.zones_without_member[:5])


def read_zone_records(
    src: Path, level_key: str, *, sido_codes=CAPITAL_AREA_SD,
) -> tuple[list[SchoolZoneRecord], Any]:
    """중·고 학교군 → 구역 1행 + 후보 학교 N (`build_zone_records`)."""
    level, zone_file = LEVEL_FILES[level_key]
    for name in (zone_file, FILE_LINK, FILE_LOCATION):
        _require(src, name)

    zones = parse_zone_shapefile((src / zone_file).read_bytes(), sido_codes=sido_codes)
    links = parse_link_csv((src / FILE_LINK).read_bytes(), level=level)
    locations = parse_school_location_csv((src / FILE_LOCATION).read_bytes(), level=level)
    logger.info("원천[%s] — 학교군 폴리곤 %d · 연계 %d · 학교좌표 %d",
                level, len(zones), len(links), len(locations))
    records, report = build_zone_records(zones, links, locations, level=level)
    _log_losses(level, report)
    if not records:
        raise SystemExit(f"[FAIL] {level}: 적재할 구역이 0건입니다 — 원천·필터를 확인하세요.")
    return records, report


def read_records(src: Path, *, sido_codes=CAPITAL_AREA_SD) -> tuple[list[SchoolDistrictRecord], Any]:
    zone_file = LEVEL_FILES["elementary"][1]
    for name in (zone_file, FILE_LINK, FILE_LOCATION):
        _require(src, name)

    zones = parse_zone_shapefile((src / zone_file).read_bytes(), sido_codes=sido_codes)
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

#: 013 이후 학교급·구역종류·학구ID 를 함께 적는다. **학교급이 없으면 조회가 이 행을
#: 어떤 급으로도 잡지 못한다**(_SCHOOL_SQL 이 school_level 로 거른다) — 그게 안전한
#: 기본값이다. 재적재가 013 이전 행의 빈 컬럼도 메운다.
_DISTRICT_UPSERT = f"""
WITH up AS (
    INSERT INTO school_district (school_poi_id, geom, source, as_of, source_ref,
                                 school_level, zone_kind, zone_id, zone_name)
    SELECT p.id, g.geom, '{SOURCE_KESI}', g.as_of, g.source_ref,
           '{ELEMENTARY}', '{ZONE_KIND[ELEMENTARY]}', s.zone_id, s.zone_name
    FROM _sz_geom g
    JOIN _sz_stage s ON s.source_ref = g.source_ref
    JOIN poi p ON p.source = '{SOURCE_KESI}' AND p.source_ref = g.school_source_ref
    ON CONFLICT (source, source_ref) WHERE source_ref IS NOT NULL
    DO UPDATE SET school_poi_id = EXCLUDED.school_poi_id,
                  geom          = EXCLUDED.geom,
                  as_of         = EXCLUDED.as_of,
                  school_level  = EXCLUDED.school_level,
                  zone_kind     = EXCLUDED.zone_kind,
                  zone_id       = EXCLUDED.zone_id,
                  zone_name     = EXCLUDED.zone_name
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
#: ⚠️ 급을 섞어 세지 않는다. `school_level` 을 안 걸면 초등 적재가 중·고 행 전부를
#:    '없어진 행'으로 보고하게 된다(013 이후).
_STALE_COUNT = f"""
INSERT INTO _sz_stats (k, v)
SELECT 'stale', count(*)
FROM school_district d
WHERE d.source = '{SOURCE_KESI}'
  AND d.source_ref IS NOT NULL
  AND d.school_level = '{ELEMENTARY}'
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


# ---------------------------------------------------------------------------
# 학교군(중·고) 적재 — 구역 1행 + 후보 학교 N행
# ---------------------------------------------------------------------------
#
# 초등 경로와 문장을 공유하지 않는다. 겉모습이 비슷해도 **모델이 다르기 때문**이다
# (school_poi_id 가 NULL 이고 후보가 member 표에 있다). 억지로 합치면 어느 쪽이
# 어느 규칙을 따르는지 아무도 모르게 된다.

_ZONE_STAGE_DDL = """
CREATE TEMP TABLE _szz_stage (
    source_ref  text,
    zone_id     text,
    zone_name   text,
    level       text,
    zone_kind   text,
    as_of       date,
    wkb         text
) ON COMMIT DROP;
"""

_ZONE_MEMBER_DDL = """
CREATE TEMP TABLE _szz_member (
    zone_source_ref   text,
    school_source_ref text,
    school_name       text,
    lat               double precision,
    lon               double precision,
    attrs             jsonb
) ON COMMIT DROP;
"""

#: 초등과 같은 이유로 좌표변환·자기교차 보정은 PostGIS 가 한다(모듈 docstring ⚠️).
_ZONE_GEOM_DDL = """
CREATE TEMP TABLE _szz_geom ON COMMIT DROP AS
SELECT source_ref, zone_id, zone_name, level, zone_kind, as_of,
       ST_IsValid(g) AS was_valid,
       ST_Multi(ST_CollectionExtract(ST_MakeValid(g), 3)) AS geom
FROM (
    SELECT source_ref, zone_id, zone_name, level, zone_kind, as_of,
           ST_Transform(
               ST_SetSRID(ST_GeomFromWKB(decode(wkb, 'hex')), 5186), 4326) AS g
    FROM _szz_stage
) t;
"""

_ZONE_MAKEVALID_COUNT = """
INSERT INTO _sz_stats (k, v)
SELECT x.k, x.v
FROM (
    SELECT count(*) FILTER (WHERE NOT was_valid) AS fixed,
           count(*)                              AS rows_all,
           count(*) FILTER (WHERE geom IS NULL OR ST_IsEmpty(geom)) AS empty
    FROM _szz_geom
) t, LATERAL (VALUES ('makevalid_fixed', t.fixed),
                     ('geom_rows',       t.rows_all),
                     ('geom_empty',      t.empty)) AS x(k, v);
"""

#: 후보 학교 POI. 학교 하나가 여러 학교군에 걸리므로(중·고에서 흔하다)
#: **배치 안에서 먼저 접는다** — 한 INSERT 가 같은 대상 행을 두 번 건드리면
#: PostgreSQL 이 트랜잭션을 통째로 깬다(초등 경로와 같은 이유).
_ZONE_POI_UPSERT = f"""
WITH src AS (
    SELECT DISTINCT ON (school_source_ref)
           school_source_ref, school_name, lat, lon, attrs
    FROM _szz_member
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

#: 구역 upsert. `school_poi_id` 를 **명시적으로 NULL** 로 둔다 —
#: 013 의 CHECK(학교군 행에는 단수 배정 학교를 적을 수 없다)가 이걸 강제한다.
_ZONE_DISTRICT_UPSERT = f"""
WITH up AS (
    INSERT INTO school_district (school_poi_id, geom, source, as_of, source_ref,
                                 school_level, zone_kind, zone_id, zone_name)
    SELECT NULL, g.geom, '{SOURCE_KESI}', g.as_of, g.source_ref,
           g.level, g.zone_kind, g.zone_id, g.zone_name
    FROM _szz_geom g
    ON CONFLICT (source, source_ref) WHERE source_ref IS NOT NULL
    DO UPDATE SET school_poi_id = NULL,
                  geom          = EXCLUDED.geom,
                  as_of         = EXCLUDED.as_of,
                  school_level  = EXCLUDED.school_level,
                  zone_kind     = EXCLUDED.zone_kind,
                  zone_id       = EXCLUDED.zone_id,
                  zone_name     = EXCLUDED.zone_name
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

#: 이번 배포분에서 **빠진 구성원**만 지운다(이번에 적재한 구역에 한해서).
#: 학교가 학교군에서 빠지는 일은 실제로 생기고, 남겨 두면 없는 후보를 계속 세게 된다.
#: 반대로 이번에 적재하지 않은 구역은 건드리지 않는다 — 원천이 반쪽만 배포됐을 때
#: 멀쩡한 구성원을 날리지 않기 위해서다(_STALE_COUNT 와 같은 원칙).
_ZONE_MEMBER_PRUNE = f"""
WITH del AS (
    DELETE FROM school_district_member m
    USING school_district d
    WHERE m.district_id = d.id
      AND d.source = '{SOURCE_KESI}'
      AND d.source_ref IN (SELECT source_ref FROM _szz_stage)
      AND NOT EXISTS (
            SELECT 1
            FROM _szz_member ms
            JOIN poi p ON p.source = '{SOURCE_KESI}'
                      AND p.source_ref = ms.school_source_ref
            WHERE ms.zone_source_ref = d.source_ref
              AND p.id = m.school_poi_id)
    RETURNING 1
)
INSERT INTO _sz_stats (k, v) SELECT 'member_removed', count(*) FROM del;
"""

_ZONE_MEMBER_UPSERT = f"""
WITH up AS (
    INSERT INTO school_district_member (district_id, school_poi_id)
    SELECT DISTINCT d.id, p.id
    FROM _szz_member ms
    JOIN school_district d ON d.source = '{SOURCE_KESI}'
                          AND d.source_ref = ms.zone_source_ref
    JOIN poi p ON p.source = '{SOURCE_KESI}'
              AND p.source_ref = ms.school_source_ref
    ON CONFLICT (district_id, school_poi_id) DO NOTHING
    RETURNING 1
)
INSERT INTO _sz_stats (k, v) SELECT 'member_inserted', count(*) FROM up;
"""

#: 최종 구성원 수 — 적재 후 **실제로 붙어 있는** 후보 학교 연결 수를 센다.
#: 원천 행수와 대조하기 위한 값이다(insert 건수는 재실행이면 0 이 되므로 대조에 못 쓴다).
_ZONE_MEMBER_TOTAL = f"""
INSERT INTO _sz_stats (k, v)
SELECT 'member_total', count(*)
FROM school_district_member m
JOIN school_district d ON d.id = m.district_id
WHERE d.source = '{SOURCE_KESI}'
  AND d.source_ref IN (SELECT source_ref FROM _szz_stage);
"""


def _zone_stale_count(level: str) -> str:
    return f"""
INSERT INTO _sz_stats (k, v)
SELECT 'stale', count(*)
FROM school_district d
WHERE d.source = '{SOURCE_KESI}'
  AND d.source_ref IS NOT NULL
  AND d.school_level = '{level}'
  AND NOT EXISTS (SELECT 1 FROM _szz_stage s WHERE s.source_ref = d.source_ref);
"""


def _zone_ingest_log(level_key: str, level: str) -> str:
    return f"""
INSERT INTO ingest_log (source, target_table, started_at, finished_at,
                        rows_ok, rows_failed, status, message)
SELECT '{SOURCE_KESI}:{level_key}', 'school_district',
       now(), clock_timestamp(),
       pg_temp.s('district_inserted') + pg_temp.s('district_updated'),
       pg_temp.s('geom_empty'),
       CASE WHEN pg_temp.s('geom_empty') > 0 THEN 'partial' ELSE 'ok' END,
       format('{level} 학교군 신규 %s / 갱신 %s · 후보 학교 연결 %s(신규 %s / 삭제 %s)'
              ' · 학교 POI 신규 %s / 갱신 %s · 자기교차 보정 %s'
              ' · 이번 배포분에 없는 옛 구역 %s',
              pg_temp.s('district_inserted'), pg_temp.s('district_updated'),
              pg_temp.s('member_total'),      pg_temp.s('member_inserted'),
              pg_temp.s('member_removed'),
              pg_temp.s('poi_inserted'),      pg_temp.s('poi_updated'),
              pg_temp.s('makevalid_fixed'),   pg_temp.s('stale'));
"""


def _zone_pipeline(level: str) -> tuple[str, ...]:
    """학교군 적재 순서. POI 가 먼저 있어야 member 가 붙는다."""
    return (
        _ZONE_MAKEVALID_COUNT,
        _ZONE_POI_UPSERT,
        _ZONE_DISTRICT_UPSERT,
        _ZONE_MEMBER_PRUNE,
        _ZONE_MEMBER_UPSERT,
        _ZONE_MEMBER_TOTAL,
        _zone_stale_count(level),
    )


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


def _zone_stage_values(record: SchoolZoneRecord) -> str:
    return "(" + ", ".join((
        _literal(record.source_ref),
        _literal(record.zone_id),
        _literal(record.zone_name),
        _literal(record.level),
        _literal(record.zone_kind),
        f"CAST({_literal(record.as_of)} AS date)",
        _literal(record.wkb_hex),
    )) + ")"


def _zone_member_values(record: SchoolZoneRecord) -> Iterator[str]:
    for m in record.members:
        yield "(" + ", ".join((
            _literal(record.source_ref),
            _literal(m.school_source_ref),
            _literal(m.school_name),
            _literal(m.lat),
            _literal(m.lon),
            f"CAST({_literal(json.dumps(m.attrs, ensure_ascii=False))} AS jsonb)",
        )) + ")"


def iter_zone_sql(records: Sequence[SchoolZoneRecord], level_key: str, *,
                  batch: int = STAGE_BATCH) -> Iterator[str]:
    """학교군 적재 SQL. 초등과 **다른 문장**이다(모델이 다르다)."""
    level = LEVEL_FILES[level_key][0]
    members = sum(len(r.members) for r in records)
    yield f"-- {level} 학교군 적재 (scripts/load_school_zone.py 생성)\n"
    yield (f"-- 구역 {len(records):,}개 · 후보 학교 연결 {members:,}건 "
           f"· 원천 {SOURCE_KESI}\n")
    yield "BEGIN;\n"
    yield _ZONE_STAGE_DDL
    yield _ZONE_MEMBER_DDL
    yield _STATS_DDL
    for i in range(0, len(records), batch):
        chunk = records[i:i + batch]
        yield ("INSERT INTO _szz_stage VALUES\n"
               + ",\n".join(_zone_stage_values(r) for r in chunk) + ";\n")
    rows = [v for r in records for v in _zone_member_values(r)]
    member_batch = batch * 20                 # 멤버 행은 지오메트리가 없어 가볍다
    for i in range(0, len(rows), member_batch):
        yield ("INSERT INTO _szz_member VALUES\n"
               + ",\n".join(rows[i:i + member_batch]) + ";\n")
    yield _ZONE_GEOM_DDL
    for statement in _zone_pipeline(level):
        yield statement
    yield _STATS_FN
    yield _zone_ingest_log(level_key, level)
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


def write_zone_sql(records: Sequence[SchoolZoneRecord], level_key: str,
                   out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if out.suffix == ".gz" else open
    with opener(out, "wt", encoding="utf-8") as fh:      # type: ignore[operator]
        for piece in iter_zone_sql(records, level_key):
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


def load_zones_to_db(engine: Any, records: Sequence[SchoolZoneRecord],
                     level_key: str) -> dict[str, int]:
    """학교군 직접 적재. `iter_zone_sql` 과 **같은 문장·같은 순서**를 쓴다."""
    from sqlalchemy import text

    level = LEVEL_FILES[level_key][0]
    stats: dict[str, int] = {}
    with engine.begin() as conn:
        conn.execute(text(_ZONE_STAGE_DDL))
        conn.execute(text(_ZONE_MEMBER_DDL))
        conn.execute(text(_STATS_DDL))

        zone_params = [{
            "source_ref": r.source_ref, "zone_id": r.zone_id, "zone_name": r.zone_name,
            "level": r.level, "zone_kind": r.zone_kind, "as_of": r.as_of,
            "wkb": r.wkb_hex,
        } for r in records]
        zone_insert = text("""
            INSERT INTO _szz_stage VALUES
            (:source_ref, :zone_id, :zone_name, :level, :zone_kind,
             CAST(:as_of AS date), :wkb)
        """)
        for i in range(0, len(zone_params), STAGE_BATCH):
            conn.execute(zone_insert, zone_params[i:i + STAGE_BATCH])

        member_params = [{
            "zone_source_ref": r.source_ref,
            "school_source_ref": m.school_source_ref,
            "school_name": m.school_name, "lat": m.lat, "lon": m.lon,
            "attrs": json.dumps(m.attrs, ensure_ascii=False),
        } for r in records for m in r.members]
        member_insert = text("""
            INSERT INTO _szz_member VALUES
            (:zone_source_ref, :school_source_ref, :school_name, :lat, :lon,
             CAST(:attrs AS jsonb))
        """)
        for i in range(0, len(member_params), STAGE_BATCH * 20):
            conn.execute(member_insert, member_params[i:i + STAGE_BATCH * 20])

        conn.execute(text(_ZONE_GEOM_DDL))
        for statement in _zone_pipeline(level):
            conn.execute(text(statement))
        conn.execute(text(_STATS_FN))
        conn.execute(text(_zone_ingest_log(level_key, level)))
        stats = {r.k: int(r.v) for r in conn.execute(text(
            "SELECT k, v FROM _sz_stats")).all()}

    logger.info("[%s] 학교군 신규 %s / 갱신 %s · 후보 연결 %s(신규 %s / 삭제 %s)"
                " · 학교 POI 신규 %s / 갱신 %s · 자기교차 보정 %s · 옛 구역 %s",
                level, stats.get("district_inserted"), stats.get("district_updated"),
                stats.get("member_total"), stats.get("member_inserted"),
                stats.get("member_removed"),
                stats.get("poi_inserted"), stats.get("poi_updated"),
                stats.get("makevalid_fixed"), stats.get("stale"))
    return stats


# ---------------------------------------------------------------------------

def _sql_out_path(base: str, level_key: str, multi: bool) -> Path:
    """급이 여러 개면 파일도 급별로 나눈다(한 파일에 이어 붙이면 부분 실패가 섞인다)."""
    path = Path(base)
    if not multi:
        return path
    suffixes = "".join(path.suffixes)                # '.sql.gz'
    stem = path.name[:-len(suffixes)] if suffixes else path.name
    return path.with_name(f"{stem}_{level_key}{suffixes}")


def _run_elementary(src: Path, sido_codes, sql_out: Path | None) -> int:
    records, _ = read_records(src, sido_codes=sido_codes)
    schools = {r.school_source_ref for r in records}
    logger.info("[초등학교] 레코드 %d건 (학구 %d · 학교 %d · 기준일자 %s)",
                len(records), len({r.zone_id for r in records}), len(schools),
                sorted({r.as_of for r in records}))
    if sql_out is not None:
        write_sql(records, sql_out)
        return 0
    stats = load_to_db(make_engine(), records)
    print(f"[DONE] 초등 통학구역 신규 {stats['district_inserted']} / "
          f"갱신 {stats['district_updated']} · "
          f"poi(school) 신규 {stats['poi_inserted']} / 갱신 {stats['poi_updated']} · "
          f"자기교차 보정 {stats['makevalid_fixed']}")
    return 0


def _run_zone(src: Path, level_key: str, sido_codes, sql_out: Path | None) -> int:
    records, report = read_zone_records(src, level_key, sido_codes=sido_codes)
    level = LEVEL_FILES[level_key][0]
    logger.info("[%s] 구역 %d개 · 후보 학교 연결 %d건 · 학교 %d곳 · 기준일자 %s",
                level, len(records), report.members,
                len({m.school_source_ref for r in records for m in r.members}),
                sorted({r.as_of for r in records}))
    if sql_out is not None:
        write_zone_sql(records, level_key, sql_out)
        return 0
    stats = load_zones_to_db(make_engine(), records, level_key)
    print(f"[DONE] {level} 학교군 신규 {stats['district_inserted']} / "
          f"갱신 {stats['district_updated']} · 후보 연결 {stats['member_total']}"
          f"(신규 {stats['member_inserted']} / 삭제 {stats['member_removed']}) · "
          f"poi(school) 신규 {stats['poi_inserted']} / 갱신 {stats['poi_updated']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="학구도 적재(초등 통학구역 · 중고 학교군)")
    ap.add_argument("--src", default=str(SRC_DIR), help="fetch_school_zone.py 저장 폴더")
    ap.add_argument("--level", choices=(*LEVEL_FILES, "all"), default="elementary",
                    help="적재할 학교급. 기본은 초등(예전 동작 유지)")
    ap.add_argument("--sql-out", help="적재 SQL 을 파일로 저장(.gz 지원). DB 접속 안 함. "
                                      "--level all 이면 급별 파일로 나뉜다")
    ap.add_argument("--nationwide", action="store_true",
                    help="수도권 필터 해제(권장하지 않음 — DB 5배)")
    args = ap.parse_args(argv)

    load_env()
    src = Path(args.src)
    sido_codes = None if args.nationwide else CAPITAL_AREA_SD
    keys = list(LEVEL_FILES) if args.level == "all" else [args.level]

    for key in keys:
        out = (_sql_out_path(args.sql_out, key, len(keys) > 1)
               if args.sql_out else None)
        if key == "elementary":
            _run_elementary(src, sido_codes, out)
        else:
            _run_zone(src, key, sido_codes, out)

    if args.sql_out:
        print("\n       다음(서버에서): 급별 파일을 **순서대로** 흘려 넣는다\n"
              "       gunzip -c <파일> | psql -v ON_ERROR_STOP=1 -U realestate -d realestate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
