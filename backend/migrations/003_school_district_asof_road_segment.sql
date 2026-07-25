-- 003_school_district_asof_road_segment.sql
-- 03-arch 보고에서 올린 스키마 공백 2건을 메운다. 승인: re-pm (ORDER 2026-07-25-10-arch)
--
-- ① school_district.as_of — **학구도는 해마다 바뀐다.**
--    기준연도를 적을 자리가 없어 CHARTER §5(세율·규제는 출처와 기준일자를 함께)를
--    지킬 수 없었다. 지금까지는 poi.attrs->>'district_as_of' 로 우회했다.
--
-- ② road_segment — 도로 **선형(line)** 데이터.
--    점(poi) 만으로는 "통학로가 대로를 건너는가"를 판정할 수 없어
--    `crosses_main_road` 를 계속 NULL(모름)로 넘겨야 했다.
--    선형이 생기면 단지→학교 직선과의 교차 판정이 가능해진다.
--
-- 적용
--   신규 DB : docker-entrypoint-initdb.d 가 001 → 002 → 003 순서로 자동 적용.
--   기존 DB : psql -f 로 수동 적용. 기존 데이터를 지우지 않는다(ADD COLUMN·CREATE TABLE 뿐).

BEGIN;

-- ① 학구도 기준연도 ---------------------------------------------------------
-- NULL 을 허용한다. 이미 들어온 행에 가짜 연도를 채워 넣는 것보다
-- "모른다"로 두고 리포지토리가 근거를 비우게 하는 편이 정직하다.
ALTER TABLE school_district ADD COLUMN IF NOT EXISTS as_of date;

COMMENT ON COLUMN school_district.as_of IS
    '학구도 기준연도. NULL 이면 기준일자 미상 → 근거로 쓰지 않는다(G2).';

-- ② 도로 선형 ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS road_segment (
    id         bigserial PRIMARY KEY,
    name       text,
    -- 통학로 횡단 판정에 쓰는 건 간선급 이상이다. 이면도로까지 넣으면
    -- 모든 단지가 '대로 횡단'이 돼서 판정이 무의미해진다.
    road_class text NOT NULL
               CHECK (road_class IN ('고속도로','자동차전용','간선','보조간선','일반')),
    lanes      smallint CHECK (lanes IS NULL OR lanes > 0),
    -- LineString·MultiLineString 을 모두 받는다. 출처마다 형태가 달라
    -- 한쪽으로 강제하면 적재가 실패한다(ST_Multi 강요 대신 CHECK 로 좁힌다).
    geom       geometry(Geometry, 4326),
    source     text,
    source_url text,
    as_of      date,
    CONSTRAINT road_segment_is_line CHECK (
        geom IS NULL
        OR GeometryType(geom) IN ('LINESTRING','MULTILINESTRING')
    )
);

CREATE INDEX IF NOT EXISTS idx_road_segment_geom  ON road_segment USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_road_segment_class ON road_segment (road_class);

COMMENT ON TABLE road_segment IS
    '도로 선형. 통학로 대로 횡단 판정(crosses_main_road)과 동별 간선도로 거리에 쓴다.';

COMMIT;
