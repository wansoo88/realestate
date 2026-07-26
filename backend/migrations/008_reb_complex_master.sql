-- 008_reb_complex_master.sql
-- REB-1 — 한국부동산원 공동주택 단지 식별정보를 적재하고 우리 `complex` 와 잇는다.
--
-- 왜 필요한가 (2026-07-26 운영 DB 실측)
-- ------------------------------------
-- GEO-1 로 틀린 좌표를 걷어내자 좌표 확보율이 93.6% → 80.0% 가 됐다.
-- 미확보 1,307건의 사유는 **검증불합격 749 + 검색0건 518** 이고, 둘 다
-- "단지명으로 찾기"의 한계다. MOLIT 단지명이 오염돼 있기 때문이다:
--   '현대2차(10,11,20,23,24,25동)' · '대치우성아파트1동,2동,3동' · '가락동 우성'(1차? 2차?)
--
-- 이름으로 더 짜내면 정확도가 깎인다. 그래서 **이름이 아니라 주소로 찾는다.**
-- 부동산원 마스터에는 단지고유번호 · 필지고유번호(PNU) · 지번주소 · 단지명 3종 ·
-- 단지종류 · 동수 · 세대수 · 사용승인일이 있고, PNU 앞 10자리가 법정동코드다.
--
-- 이 마이그레이션이 하는 일
-- -------------------------
--   reb_complex            — 부동산원 단지 마스터(수도권). 우리가 가공하지 않은 원본 사실.
--   reb_building           — 부동산원 동(棟) 목록. `building` 을 채우는 근거.
--   complex.reb_complex_id — 매칭 결과(FK). 매칭 방법·시각도 함께 남긴다.
--   geom_confidence 'address' 허용 — 주소 경로로 확보한 좌표.
--
-- 하지 않는 일 (의도적)
-- ---------------------
--   * 파티션(trade)·자연키(004)·007 은 건드리지 않는다.
--   * reb_complex.legal_dong_code 에 region FK 를 걸지 않는다 — 부동산원 스냅샷에는
--     우리 region 에 없는(폐지·개편 전) 코드가 섞일 수 있고, FK 로 막으면 적재가
--     통째로 실패한다. 매칭은 코드 문자열 대조로 하고, 못 맞춘 건 못 맞췄다고 센다.
--   * complex.reb_complex_id 에 UNIQUE 를 걸지 않는다 — MOLIT 이름 오염으로 한 단지가
--     여러 행으로 갈라져 있어(‘삼환나띠르빌(1002-10)’~’(1002-22)’) **여러 complex 가 한
--     부동산원 단지를 가리키는 것이 정상**이다. UNIQUE 를 걸면 정상 데이터가 적재를 막는다.
--
-- 적용: 신규 DB 는 001→…→008 자동. 기존 DB 는 psql -f 로 수동.

BEGIN;

-- ---------------------------------------------------------------------------
-- 부동산원 단지 마스터
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reb_complex (
    reb_complex_id  text PRIMARY KEY,          -- 단지고유번호 (14자리)
    parcel_id       text NOT NULL,             -- 필지고유번호(PNU) 19자리
    -- PNU 를 쪼갠 값들. 적재 시 한 번 계산해 두어야 지오코딩 검증이 조회만으로 끝난다.
    legal_dong_code char(10) NOT NULL,         -- PNU[0:10] — region.code 와 같은 체계
    sigungu_code    char(5)  NOT NULL,         -- PNU[0:5]
    is_mountain     boolean  NOT NULL DEFAULT false,   -- 산번지 ('산87-85' ≠ '87-85')
    main_no         int      NOT NULL,         -- 본번
    sub_no          int      NOT NULL DEFAULT 0,       -- 부번
    address_jibun   text,                      -- '서울특별시 종로구 청운동 56-45'
    -- 단지명이 셋인 이유: 출처마다 표기가 다르다. 공시가격 이름은 '우정(102동)' 처럼
    -- 동이 섞이고, 건축물대장 이름이 정식 명칭인 경우가 많다. 하나만 두면 매칭을 놓친다.
    name_price      text,                      -- 단지명_공시가격
    name_ledger     text,                      -- 단지명_건축물대장
    name_road       text,                      -- 단지명_도로명주소
    kind            text,                      -- 단지종류 '1'아파트 '2'연립 '3'다세대
    building_count  int,                       -- 동수
    household_count int,                       -- 세대수
    approved_on     date,                      -- 사용승인일
    loaded_at       timestamptz NOT NULL DEFAULT now()
);

-- 매칭은 항상 "같은 법정동 안에서" 이뤄진다(구조적으로 그렇게만 허용한다).
CREATE INDEX IF NOT EXISTS reb_complex_dong_idx ON reb_complex (legal_dong_code, kind);

COMMENT ON TABLE reb_complex IS
    '한국부동산원 공동주택 단지 식별정보(기본정보) 스냅샷. 출처: 공공데이터포털 15106861. '
    '우리가 가공하지 않은 원본 사실만 담는다 — 매칭 결과는 complex.reb_complex_id 에 있다.';
COMMENT ON COLUMN reb_complex.legal_dong_code IS
    '필지고유번호 앞 10자리(법정동코드). complex.region_code 와 같은 체계라 문자열 동명이 '
    '아니라 코드로 대조한다. region 에 대한 FK 는 의도적으로 걸지 않는다(폐지 코드 혼입).';

-- ---------------------------------------------------------------------------
-- 부동산원 동(棟) 목록
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reb_building (
    id             bigserial PRIMARY KEY,
    reb_complex_id text NOT NULL REFERENCES reb_complex(reb_complex_id) ON DELETE CASCADE,
    -- 원본 표기 3종을 그대로 둔다('101' · '제101' · '청운현대(아)101동' · '가').
    name_price     text,
    name_ledger    text,
    name_road      text,
    -- 위 표기를 읽어낸 정규 표기('101동'). **읽히지 않으면 NULL 이다** —
    -- 동 개수를 아는 것과 동 목록을 아는 것은 다르고, 모르는 동을 지어내면 F4 가 거짓이 된다.
    dong_label     text,
    floors         int,                        -- 지상층수
    loaded_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (reb_complex_id, name_price, name_ledger, name_road)
);
CREATE INDEX IF NOT EXISTS reb_building_complex_idx ON reb_building (reb_complex_id);

COMMENT ON TABLE reb_building IS
    '한국부동산원 공동주택 단지 식별정보(동정보) 스냅샷. 출처: 공공데이터포털 15106866.';
COMMENT ON COLUMN reb_building.dong_label IS
    '정규화된 동 표기(''101동''). NULL 이면 원본 표기를 동으로 읽어낼 수 없었다는 뜻 — '
    '이 행은 building 으로 승격하지 않는다(없는 동을 만들지 않는다).';

-- ---------------------------------------------------------------------------
-- 우리 complex 와의 연결
-- ---------------------------------------------------------------------------
ALTER TABLE complex ADD COLUMN IF NOT EXISTS reb_complex_id text
    REFERENCES reb_complex(reb_complex_id);
ALTER TABLE complex ADD COLUMN IF NOT EXISTS reb_match_method text;
ALTER TABLE complex ADD COLUMN IF NOT EXISTS reb_matched_at timestamptz;

-- 오타로 조용히 이상한 값이 들어가는 걸 막는다. NULL = 아직 매칭하지 않았음.
ALTER TABLE complex DROP CONSTRAINT IF EXISTS complex_reb_match_method_chk;
ALTER TABLE complex ADD CONSTRAINT complex_reb_match_method_chk
    CHECK (reb_match_method IS NULL
           OR reb_match_method IN ('name_exact', 'name_contains', 'name_fuzzy'));

-- 매칭 방법이 있으면 상대가 있어야 하고, 상대가 있으면 방법이 있어야 한다.
-- (한쪽만 채우는 스크립트 버그를 데이터가 아니라 스키마가 막는다.)
ALTER TABLE complex DROP CONSTRAINT IF EXISTS complex_reb_match_pair_chk;
ALTER TABLE complex ADD CONSTRAINT complex_reb_match_pair_chk
    CHECK ((reb_complex_id IS NULL) = (reb_match_method IS NULL));

CREATE INDEX IF NOT EXISTS complex_reb_idx ON complex (reb_complex_id)
    WHERE reb_complex_id IS NOT NULL;

COMMENT ON COLUMN complex.reb_complex_id IS
    '매칭된 부동산원 단지고유번호. NULL = 매칭 실패 또는 애매(둘을 구분하지 않는다 — '
    '어느 쪽이든 "모른다"이고, 애매한 매칭을 넣는 것이 이 프로젝트에서 가장 하면 안 되는 일이다).';
COMMENT ON COLUMN complex.reb_match_method IS
    '매칭 근거. name_exact(완전일치) > name_contains(포함) > name_fuzzy(유사도) 순으로 강하다. '
    '같은 법정동코드 안에서만 대조하며, 한 단계에서 후보가 둘 이상이면 매칭하지 않는다.';

-- ---------------------------------------------------------------------------
-- 좌표 출처에 주소 경로 추가 (007 확장)
-- ---------------------------------------------------------------------------
ALTER TABLE complex DROP CONSTRAINT IF EXISTS complex_geom_confidence_chk;
ALTER TABLE complex ADD CONSTRAINT complex_geom_confidence_chk
    CHECK (geom_confidence IS NULL
           OR geom_confidence IN ('exact', 'variant', 'address'));

COMMENT ON COLUMN complex.geom_source IS
    '좌표 출처. ''kakao_keyword'' = 키워드검색 + 법정동·시군구·단지명 검증 통과. '
    '''kakao_address'' = 부동산원 매칭 단지의 지번주소로 주소검색 + 법정동코드·본번·부번 일치. '
    'NULL 이면 검증 이력 없는 레거시 좌표(신뢰 금지).';
COMMENT ON COLUMN complex.geom_confidence IS
    '좌표 신뢰도. ''exact''=원본 단지명으로 통과, ''variant''=지번·동목록 제거 이름으로 통과, '
    '''address''=부동산원 지번주소로 통과(이름을 거치지 않음). '
    'UI 에서 ''variant'' 는 추정 표기 대상(추정치를 확정처럼 보이지 않게).';

COMMIT;
