-- 012_school_district_natural_key.sql
-- 학구도(school_district) 적재의 **멱등성**을 만든다. 011 이 poi·road_segment·
-- transit_plan 에 한 것과 같은 규칙을 school_district 에도 적용한다.
--
-- 왜 지금인가
--   학구도는 매년 **3월·9월** 갱신 배포된다(한국교육시설안전원). 자연키가 없으면
--   재적재할 때마다 같은 학구가 한 행씩 쌓이고, 그러면 `_SCHOOL_SQL` 의
--   `JOIN school_district ... LIMIT 1` 이 어느 판을 고를지 알 수 없게 된다.
--   낡은 판과 새 판이 섞인 채 "배정 초등학교"를 단정하는 것이 최악이다.
--   011 주석이 이미 이 순간을 예고해 뒀다("나중에 학구도를 수기로 넣을 때").
--
-- 자연키가 (학구ID, 학교ID) 인 이유
--   학구ID 단독은 키가 못 된다. **공동학구**는 학구 하나에 학교가 여럿 걸리고
--   (수도권 초등 2,658개 학구 → 3,256행, 중복배수 1.22), 현재 스키마가
--   1행 = 1(구역, 학교) 라 학구ID 로 조이면 공동학구의 두 번째 학교부터 적재가 깨진다.
--   그래서 source_ref 는 'kesi:{학구ID}/{학교ID}' 형태다.
--
-- 부분 유니크인 이유
--   011 과 같다. source_ref 가 NULL 인 행(다른 경로·수기 적재)을 막지 않는다.
--
-- 적용
--   신규 DB : docker-entrypoint-initdb.d 가 001→…→012 순서로 자동 적용.
--   기존 DB : psql -f 로 수동 적용. **기존 데이터를 지우지 않는다**(ADD COLUMN·CREATE INDEX 뿐).

BEGIN;

ALTER TABLE school_district ADD COLUMN IF NOT EXISTS source_ref text;

COMMENT ON COLUMN school_district.source_ref IS
    '원천 고유 ID(자연키). ''kesi:{학구ID}/{학교ID}''. '
    '학구ID 단독은 공동학구 때문에 키가 되지 못한다. (source, source_ref) 유니크로 '
    '연 2회(3월·9월) 재배포분 재적재를 멱등하게 만든다.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_school_district_source_ref
    ON school_district (source, source_ref)
    WHERE source_ref IS NOT NULL;

COMMIT;
