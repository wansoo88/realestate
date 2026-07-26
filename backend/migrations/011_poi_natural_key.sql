-- 011_poi_natural_key.sql
-- 입지(F3) 데이터 적재의 **멱등성**을 만든다.
--
-- 문제
--   poi · road_segment · transit_plan 에는 자연키가 없다. 지금은 0행이라 티가 안 나지만,
--   주 1회 갱신(sources.yaml cadence)을 돌리는 순간 같은 지하철역이 매주 한 행씩 쌓인다.
--   그러면 "최근접 역"은 여전히 맞지만 **환승역 판정(line_count)** 과 개수 통계가 망가지고,
--   무엇보다 재실행이 안전하지 않아 수집을 다시 돌릴 수 없게 된다.
--
-- 해법
--   원천 ID 를 `source_ref` 로 보존하고 (source, source_ref) 에 유니크를 건다.
--   이름·좌표를 키로 쓰지 않는 이유: 원천이 좌표를 1m 고치면 같은 시설이 두 행이 된다.
--   원천 ID 는 시설이 사라지지 않는 한 안 바뀐다.
--     - OSM      : 'node/123' · 'way/456'
--     - NEIS 학교 : 'neis:B10/7031110'
--
-- 부분 유니크인 이유
--   source_ref 가 NULL 인 행(수기 입력·다른 경로 적재)을 막지 않는다. NOT NULL 로 조이면
--   나중에 학구도를 수기로 넣을 때 이 마이그레이션이 걸림돌이 된다.
--
-- 적용
--   신규 DB : docker-entrypoint-initdb.d 가 001→…→011 순서로 자동 적용.
--   기존 DB : psql -f 로 수동 적용. **기존 데이터를 지우지 않는다**(ADD COLUMN·CREATE INDEX 뿐).

BEGIN;

-- ① poi ---------------------------------------------------------------------
ALTER TABLE poi ADD COLUMN IF NOT EXISTS source_ref text;

COMMENT ON COLUMN poi.source_ref IS
    '원천 고유 ID(자연키). OSM ''node/123'' · NEIS ''neis:B10/7031110''. '
    '(source, source_ref) 유니크로 재수집 멱등을 보장한다.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_poi_source_ref
    ON poi (source, source_ref)
    WHERE source_ref IS NOT NULL;

-- ② road_segment ------------------------------------------------------------
ALTER TABLE road_segment ADD COLUMN IF NOT EXISTS source_ref text;

COMMENT ON COLUMN road_segment.source_ref IS
    '원천 고유 ID(자연키). OSM way id. (source, source_ref) 유니크.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_road_segment_source_ref
    ON road_segment (source, source_ref)
    WHERE source_ref IS NOT NULL;

-- ③ transit_plan ------------------------------------------------------------
-- 001 에는 source 컬럼 자체가 없다(source_url 만 있다). 자연키를 (source, source_ref)
-- 로 통일하기 위해 추가한다 — 세 표가 같은 규칙을 쓰면 적재 코드가 한 벌로 끝난다.
ALTER TABLE transit_plan ADD COLUMN IF NOT EXISTS source text;
ALTER TABLE transit_plan ADD COLUMN IF NOT EXISTS source_ref text;

COMMENT ON COLUMN transit_plan.source_ref IS
    '원천 고유 ID(자연키). OSM way id. (source, source_ref) 유니크.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_transit_plan_source_ref
    ON transit_plan (source, source_ref)
    WHERE source_ref IS NOT NULL;

-- ④ 조회 보강은 하지 않는다 --------------------------------------------------
-- (category, geom) 복합 GiST 를 고려했으나 text 를 GiST 에 넣으려면 btree_gist
-- 확장이 필요하고, 그건 superuser 권한과 배포 순서 의존을 새로 만든다.
-- 적재 규모가 수만 행이라 기존 idx_poi_category + idx_poi_geom 으로 충분하다 —
-- 필요해지면 실측(EXPLAIN)을 근거로 그때 추가한다.

COMMIT;
