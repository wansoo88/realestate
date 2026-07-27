-- 014_redevelopment_project.sql
-- 정비사업(재건축·재개발) 구역 원본 + 단지 매칭.
--
-- 왜 001 의 `redevelopment` 테이블을 쓰지 않는가
-- ---------------------------------------------
-- 001 의 `redevelopment` 는 (complex_id, stage, stage_date, est_extra_cost_krw, source_url)
-- 다섯 칸짜리 스케치였고 **0행**이다. 실제 자료를 받아 보니 세 가지가 안 맞는다.
--   ① 원본 사실과 매칭 결과가 한 테이블에 섞인다. 매칭 규칙을 고칠 때마다 원본을 다시
--      받아야 하고, "지금 DB 에 있는 게 어느 규칙의 결과인지" 알 수 없다(008 과 같은 교훈).
--   ② 한 구역이 여러 단지를 포함하고(압구정 특별계획구역·목동 단지들) 한 단지가 여러
--      구역에 걸릴 수 있다. 1:1 FK 로는 표현이 안 된다 → 연결 테이블이 필요하다.
--   ③ **`est_extra_cost_krw` 는 채울 수 없는 칸이다.** 추가분담금은 조합 내부 자료라
--      공개 데이터 어디에도 없다. 비워 둔 칸은 언젠가 누가 추정치로 채운다 —
--      그래서 이 마이그레이션은 그 칸에 **"항상 NULL" 제약**을 건다(아래).
--
-- 그래서: 원본은 `redev_project`, 매칭은 `redev_project_complex` 로 나눈다.
-- 001 의 `redevelopment` 는 **건드리지 않고 남겨 두되**(0행) 제약으로 잠근다.
--
-- 출처 (2026-07-27 실호출 확인)
-- -----------------------------
--   서울 472행 : 열린데이터광장 OA-22856 `TbSeoulRedevStatus` (지번주소·단계·단계별 일자·세대수)
--   인천 144행 : 공공데이터포털 15055212 CSV        (위치·사업유형·진행단계 — 일자 없음)
--   경기  미수집: 도 단위 공개 API 없음(시군별로 흩어짐 + 별도 인증키).
--                 국토부 전국 통합데이터는 **지번이 없어** 매칭 규칙을 만족시키지 못한다.
--   ⇒ 경기도 단지는 조회 결과가 0행이고, 그것은 "정비사업 없음"이 아니라 **"미확보"** 다.
--      도메인(app/domain/redevelopment)이 그 둘을 구분해 문구를 낸다.
--
-- 적용: 신규 DB 는 001→…→014 자동. 기존 DB 는 psql -f 로 수동.

BEGIN;

-- ---------------------------------------------------------------------------
-- 정비사업 구역 (원본 사실)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS redev_project (
    id              bigserial PRIMARY KEY,
    source          text NOT NULL,          -- 출처 식별자(app/ingest/redevelopment.py 상수)
    source_key      text NOT NULL,          -- 출처 안에서의 고유키(서울 CODE 등)
    source_url      text,
    sido            text NOT NULL,
    sigungu         text NOT NULL,          -- ⚠️ **출처가 말한 표기 그대로**(옛 이름일 수 있다)
    zone_name       text NOT NULL,

    -- 단계: 원문과 공통 enum 을 **둘 다** 둔다.
    -- 원문만 두면 시도별로 화면이 갈라지고, enum 만 두면 정규화 오류를 사후에 못 찾는다.
    raw_stage       text NOT NULL,
    stage           text NOT NULL DEFAULT 'unknown',
    raw_biz_type    text,
    biz_type        text NOT NULL DEFAULT 'unknown',

    -- 주소 → 대표지번 파싱 결과. 실패한 행도 **지우지 않고** 사유와 함께 남긴다.
    address_jibun_raw text,
    parse_status    text NOT NULL,          -- ok | no_jibun | multi_jibun | …
    parse_detail    text,
    legal_dong_code char(10),
    main_no         int,
    sub_no          int NOT NULL DEFAULT 0,
    is_mountain     boolean NOT NULL DEFAULT false,
    dong_match      text,                   -- exact | admin_stripped
    dong_scope      text,                   -- sigungu | sido_unique

    -- 단계별 일자 (서울 자료에만 있다. 없으면 NULL = **모른다**, '안 밟았다'가 아니다)
    zone_designated_on      date,
    committee_on            date,
    association_on          date,
    design_review_on        date,
    implementation_on       date,
    disposition_on          date,
    relocation_start_on     date,
    relocation_end_on       date,
    construction_start_on   date,

    existing_households int,                -- 기존 가구수(멸실량)
    planned_households  int,                -- 건립 예정 세대수 총합

    as_of           date NOT NULL,          -- 스냅샷 기준일 — 없으면 근거가 아니다
    loaded_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, source_key)
);

-- 매칭 조회는 항상 (법정동코드, 본번, 부번)로 들어온다. 파싱 실패 행은 색인하지 않는다.
CREATE INDEX IF NOT EXISTS redev_project_pnu_idx
    ON redev_project (legal_dong_code, main_no, sub_no)
    WHERE legal_dong_code IS NOT NULL AND main_no IS NOT NULL;

CREATE INDEX IF NOT EXISTS redev_project_source_idx ON redev_project (source, as_of);

-- 오타로 조용히 이상한 값이 들어가는 걸 막는다.
ALTER TABLE redev_project DROP CONSTRAINT IF EXISTS redev_project_stage_chk;
ALTER TABLE redev_project ADD CONSTRAINT redev_project_stage_chk
    CHECK (stage IN ('candidate', 'zone_designated', 'committee', 'association',
                     'design_review', 'implementation', 'disposition', 'relocation',
                     'construction', 'completed', 'unknown'));

ALTER TABLE redev_project DROP CONSTRAINT IF EXISTS redev_project_biz_type_chk;
ALTER TABLE redev_project ADD CONSTRAINT redev_project_biz_type_chk
    CHECK (biz_type IN ('rebuild', 'redevelop', 'env_improve', 'unknown'));

-- 파싱이 성공했다면 지번이 **완전히** 있어야 한다. 반쪽 지번으로는 매칭하지 않는다.
ALTER TABLE redev_project DROP CONSTRAINT IF EXISTS redev_project_parse_pair_chk;
ALTER TABLE redev_project ADD CONSTRAINT redev_project_parse_pair_chk
    CHECK ((parse_status = 'ok') = (legal_dong_code IS NOT NULL AND main_no IS NOT NULL));

COMMENT ON TABLE redev_project IS
    '정비사업 구역 스냅샷(서울 OA-22856 · 인천 15055212). 우리가 가공하지 않은 원본 사실 + '
    '대표지번 파싱 결과. 파싱 실패 행도 사유와 함께 남긴다(조용한 유실 금지).';
COMMENT ON COLUMN redev_project.raw_stage IS
    '출처의 원문 단계명. **절대 지우지 않는다** — stage 정규화가 틀렸을 때 되돌아갈 유일한 근거.';
COMMENT ON COLUMN redev_project.stage IS
    '공통 단계 enum(app/domain/redevelopment/stages.py). ''unknown'' = 정규화 표에 없는 원문 '
    '= 미분류. 버린 것이 아니라 분류하지 못한 것이다.';
COMMENT ON COLUMN redev_project.parse_status IS
    '대표지번 파싱 결과. ok 만 매칭 대상이다. multi_jibun(지번 나열)·road_address_only(도로명만)·'
    'unknown_dong·ambiguous_dong 은 **일부러 매칭하지 않은 것**이며 사유가 parse_detail 에 있다.';
COMMENT ON COLUMN redev_project.sigungu IS
    '출처가 말한 시군구 표기. 2026 인천 행정구역 개편(중구·동구·서구 → 제물포구·영종구·검단구·'
    '서해구) 이전 이름이 실려 있을 수 있어 **region 과 조인하지 않는다** — 조인은 법정동코드로 한다.';

-- ---------------------------------------------------------------------------
-- 구역 ↔ 단지 매칭
--
-- ⚠️ 이 표에 들어오는 유일한 근거는 **대표지번(법정동코드·본번·부번) 정확일치**다.
--    이름 유사도·좌표 근접으로 넣지 않는다. 애매하면 넣지 않고 스크립트가 사유를 센다.
--    (잘못된 매칭 1건은 없는 것보다 훨씬 나쁘다 — 사용자가 그 근거로 수억을 쓴다.)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS redev_project_complex (
    project_id   bigint NOT NULL REFERENCES redev_project(id) ON DELETE CASCADE,
    complex_id   bigint NOT NULL REFERENCES complex(id) ON DELETE CASCADE,
    match_method text NOT NULL,
    matched_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, complex_id)
);

CREATE INDEX IF NOT EXISTS redev_project_complex_complex_idx
    ON redev_project_complex (complex_id);

ALTER TABLE redev_project_complex DROP CONSTRAINT IF EXISTS redev_pc_method_chk;
ALTER TABLE redev_project_complex ADD CONSTRAINT redev_pc_method_chk
    CHECK (match_method IN ('pnu_exact', 'pnu_exact_admin_dong'));

COMMENT ON TABLE redev_project_complex IS
    '정비구역 ↔ 단지 매칭. 근거는 부동산원 필지(reb_complex)의 (법정동코드·본번·부번)가 '
    '구역 대표지번과 **완전히 같다**는 것 하나뿐이다. 이름 유사도 매칭은 하지 않는다.';
COMMENT ON COLUMN redev_project_complex.match_method IS
    'pnu_exact = 원문 주소의 법정동 표기로 맞췄다. pnu_exact_admin_dong = 행정동 표기'
    '(''목2동'')를 법정동(''목동'')으로 되돌려 맞췄다(지번 자체는 법정동 기준이라 값은 같다).';

-- ---------------------------------------------------------------------------
-- 001 의 스케치 테이블 잠그기 — **추가분담금 칸을 못 쓰게 만든다**
--
-- 이 프로젝트에서 가장 위험한 필드다. 값이 없으면 누군가 "대략" 채우고, 화면에는
-- "추가분담금 약 1.2억"이 뜬다. 그 숫자의 출처는 어디에도 없다.
-- 데이터가 아니라 **스키마가** 막게 한다.
-- ---------------------------------------------------------------------------
ALTER TABLE redevelopment DROP CONSTRAINT IF EXISTS redevelopment_no_cost_estimate_chk;
ALTER TABLE redevelopment ADD CONSTRAINT redevelopment_no_cost_estimate_chk
    CHECK (est_extra_cost_krw IS NULL);

COMMENT ON COLUMN redevelopment.est_extra_cost_krw IS
    '⛔ 사용 금지 — 항상 NULL(제약으로 강제). 추가분담금은 조합 내부 자료라 공개 데이터에 '
    '없다. 추정치를 넣으면 사용자가 없는 확신을 근거로 수억 원을 쓴다. '
    '사업성은 세대수 증가율·용적률 같은 **관측 가능한 값**으로만 서술한다.';
COMMENT ON TABLE redevelopment IS
    '⚠️ 001 의 스케치(0행). 실제 정비사업 데이터는 redev_project / redev_project_complex 에 있다.';

COMMIT;
