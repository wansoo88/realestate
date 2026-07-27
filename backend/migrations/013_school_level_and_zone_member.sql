-- 013_school_level_and_zone_member.sql
-- 학구도에 **학교급**을 들이고, 중·고 「학교군」을 담을 자리를 만든다.
--
-- 왜 지금인가 — 012 까지의 school_district 는 '초등 전용'이라는 전제 위에 서 있었다
-- ---------------------------------------------------------------------------
-- `repositories/postgis.py` 의 `_SCHOOL_SQL` 은 school_district 를 **학교급 구분 없이**
-- 조회해 최근접 1건을 고르고, 도메인(`assess_school`)이 그것을 `assigned_elementary`
-- 로 단정한다. 이 상태에서 중·고 구역을 같은 표에 부으면
-- **가장 가까운 중학교가 '배정 초등학교'로 보고된다.** 그래서 컬럼과 필터가 먼저다.
--
-- 학교급마다 자료의 의미가 다르다 (원천 데이터셋 제목이 이미 다르다)
-- ---------------------------------------------------------------------------
--   초등 : 「초등학교통학구역」 (공공데이터포털 15159265)
--   중   : 「중학교학교군」     (15159264)
--   고   : 「고등학교학교군」   (15159263)
-- '통학구역'과 '학교군'은 원천이 붙인 이름이지 우리 해석이 아니다. 그래서 zone_kind 로
-- **그 낱말을 그대로** 보관한다.
--
-- ⚠️ **배정 방식(단일배정/추첨/평준화)은 이 데이터 어디에도 없다.**
--    SHP 속성(HAKGUDO_ID·HAKGUDO_NM·HAKGUDO_GB·SD_CD·BASE_DT·EDU_*), 연계정보 CSV
--    (학구ID·학교ID·학교명·학교급구분·교육지원청), 학교위치 CSV 를 전부 확인했고
--    배정 방식을 적은 필드가 없다. 데이터셋 설명문에도 없다.
--    그러므로 `assignment_method` 같은 컬럼을 만들어 '추첨'을 채워 넣지 않는다 —
--    "중학교는 대체로 추첨이니까"는 데이터가 아니라 짐작이고, 짐작을 컬럼에 넣으면
--    그 다음부터는 아무도 그게 짐작인 줄 모른다.
--    대신 우리가 **셀 수 있는 사실**만 남긴다: 이 구역에 연계된 학교가 몇 곳인가
--    (school_district_member). 후보가 여럿이면 "배정 후보 N곳"이라고만 말한다.
--
-- 왜 member 테이블인가 — 1행=1(구역,학교) 모델이 중·고에서 무너진다
-- ---------------------------------------------------------------------------
-- 지금 스키마는 학교 하나가 1행이고 행마다 구역 지오메트리 사본을 갖는다. 공동학구가
-- 드문 초등(수도권 중복배수 1.22)에서는 값싼 표현이지만, 중(4.46)·고(14.39)에서는
-- **같은 폴리곤을 4~14벌 복제**한다. 실측: 수도권 고유 지오메트리 중 6.7MB(중)·2.1MB(고)
-- 가 복제되면 32.3MB·30.2MB 가 된다(적재 SQL 은 hex 라 그 2배). 대상 VPS 는 디스크
-- 여유가 2.4GB, DB 컨테이너 메모리 상한이 192MB 다.
-- 더 중요한 건 **의미**다. 학교군은 '학교마다 구역이 하나'가 아니라 '구역 하나에
-- 학교가 여럿'이다. school_poi_id(단수)로는 그 사실을 적을 수 없다.
--   · 통학구역(초등) : school_poi_id 에 배정 학교. 기존 그대로 — 회귀 없음.
--   · 학교군(중·고)  : school_poi_id 는 NULL, 후보 학교는 school_district_member 에.
--
-- 적용
--   신규 DB : docker-entrypoint-initdb.d 가 001 → … → 013 순서로 자동 적용.
--   기존 DB : psql -v ON_ERROR_STOP=1 -f 로 수동 적용.
--             **기존 데이터를 지우지 않는다** (ADD COLUMN · CREATE TABLE · UPDATE 뿐).

BEGIN;

-- ---------------------------------------------------------------------------
-- ① 학교급 · 구역 종류 · 학구 식별자
-- ---------------------------------------------------------------------------

ALTER TABLE school_district ADD COLUMN IF NOT EXISTS school_level text;
ALTER TABLE school_district ADD COLUMN IF NOT EXISTS zone_kind    text;
ALTER TABLE school_district ADD COLUMN IF NOT EXISTS zone_id      text;
ALTER TABLE school_district ADD COLUMN IF NOT EXISTS zone_name    text;

COMMENT ON COLUMN school_district.school_level IS
    '학교급(초등학교|중학교|고등학교). 원천 연계정보 CSV 의 학교급구분 값을 그대로 쓴다. '
    'NULL 이면 학교급 미상 → 조회가 어떤 급으로도 잡지 않는다(추측 금지).';
COMMENT ON COLUMN school_district.zone_kind IS
    '구역 종류(통학구역|학교군). 원천 데이터셋 제목에서 온다 — 초등은 「초등학교통학구역」, '
    '중·고는 「중학교학교군」·「고등학교학교군」. 배정 방식이 아니다(원천에 없음).';
COMMENT ON COLUMN school_district.zone_id IS
    '원천 학구ID(HAKGUDO_ID). 예: Z000102998. 급마다 번호대가 다르다.';
COMMENT ON COLUMN school_district.zone_name IS
    '원천 학구명(HAKGUDO_NM). 예: 서울언주초통학구역 · 강남서초학교군. '
    '고등학교는 ''1학교군'' 처럼 교육지원청 안에서만 유일하므로 표시할 때 교육지원청을 함께 쓴다.';

-- 화이트리스트. ADD CONSTRAINT 에는 IF NOT EXISTS 가 없어 카탈로그를 확인하고 건다
-- (재실행 가능해야 한다 — 기존 DB 는 사람이 손으로 적용한다).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'school_district_level_chk') THEN
        ALTER TABLE school_district ADD CONSTRAINT school_district_level_chk
            CHECK (school_level IS NULL
                   OR school_level IN ('초등학교','중학교','고등학교'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'school_district_zone_kind_chk') THEN
        ALTER TABLE school_district ADD CONSTRAINT school_district_zone_kind_chk
            CHECK (zone_kind IS NULL OR zone_kind IN ('통학구역','학교군'));
    END IF;
    -- 학교군 행에 배정 학교(단수)를 적지 못하게 막는다. 이걸 허용하면 어느 날
    -- '학교군인데 배정 학교가 하나 있는 행'이 생기고, 조회는 그걸 배정으로 읽는다.
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'school_district_group_has_no_single_school') THEN
        ALTER TABLE school_district ADD CONSTRAINT school_district_group_has_no_single_school
            CHECK (zone_kind IS DISTINCT FROM '학교군' OR school_poi_id IS NULL);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_school_district_level ON school_district (school_level);

-- ---------------------------------------------------------------------------
-- ② 학교군 구성원 — 구역 1 : 학교 N
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS school_district_member (
    district_id   bigint NOT NULL REFERENCES school_district(id) ON DELETE CASCADE,
    school_poi_id bigint NOT NULL REFERENCES poi(id),
    PRIMARY KEY (district_id, school_poi_id)
);

CREATE INDEX IF NOT EXISTS idx_sdm_school ON school_district_member (school_poi_id);

COMMENT ON TABLE school_district_member IS
    '학교군에 속한 학교 목록(원천: 학교학구도연계정보 CSV 의 학구ID↔학교ID). '
    '이 표에 여러 행이 있다는 것은 "후보가 여럿"이라는 뜻일 뿐, 어떻게 배정되는지는 '
    '원천에 없어 알 수 없다. 배정 방식을 여기서 추측하지 말 것.';

-- ---------------------------------------------------------------------------
-- ③ 기존 행 backfill — **데이터에서만** 채운다
-- ---------------------------------------------------------------------------
-- 012 까지 적재된 행은 전부 `scripts/load_school_zone.py` 가 넣은 것이고, 그 적재기는
-- poi.attrs 에 level·zone_id·zone_name 을 함께 적었다(ingest/school_zone.py
-- build_records). 즉 학교급은 **짐작하지 않아도 데이터에 있다.**
-- attrs 에 level 이 없는 행(수기 적재·테스트 등)은 **건드리지 않는다** — NULL 로 남고,
-- NULL 은 어떤 급 조회에도 걸리지 않는다(조용히 초등으로 세지 않는다).

UPDATE school_district sd
   SET school_level = p.attrs->>'level'
  FROM poi p
 WHERE p.id = sd.school_poi_id
   AND sd.school_level IS NULL
   AND p.attrs->>'level' IN ('초등학교','중학교','고등학교');

UPDATE school_district sd
   SET zone_id   = COALESCE(sd.zone_id,   p.attrs->>'zone_id'),
       zone_name = COALESCE(sd.zone_name, p.attrs->>'zone_name')
  FROM poi p
 WHERE p.id = sd.school_poi_id
   AND (sd.zone_id IS NULL OR sd.zone_name IS NULL)
   AND p.attrs ? 'zone_id';

-- zone_kind 는 attrs 에 없다(013 이전 적재기가 안 적었다). 그래서 **급에서 되돌린다**:
-- 초등 학구도를 배포하는 원천 데이터셋의 제목이 「초등학교통학구역」 하나뿐이고,
-- 이 저장소가 초등을 적재한 경로도 그것 하나뿐이다(scripts/fetch_school_zone.py).
-- 중·고 행은 013 이후 적재기가 직접 '학교군'을 적으므로 여기서 채울 것이 없다.
UPDATE school_district
   SET zone_kind = '통학구역'
 WHERE zone_kind IS NULL
   AND school_level = '초등학교';

COMMIT;
