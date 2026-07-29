-- 016_user_entered_listing.sql
-- 관심 단지 호가 **수동 입력** — 사용자가 직접 보고 옮겨 적은 매도 희망가 (2026-07-29)
--
-- 왜 이 마이그레이션이 필요한가
-- =============================
-- 운영 DB 실측(2026-07-29): `listing` **0행**. trade 611,518행 · complex 16,462행.
-- 호가가 없으면 추천 가중치의 48%(가격 31% + 리스크 17%)가 구조적으로 죽는다
-- (`app/agents/scoring.py::AXIS_PRICE.coverage_gap` 이 그 사실을 이미 적어 두고 있다).
--
-- 호가를 얻는 길은 지금까지 전부 닫혔다:
--   · 포털 자동수집 — 약관·확정판결(특허법원 2025.12.24)로 **하지 않는다**
--   · 미등기 최근 실거래 — 실측 기각(계약일의 함수일 뿐 · 선택편향 +0.5~2.2%, 015 참조)
--   · 시점 보정(015) — 밴드의 *수준*은 고쳤지만 **호가를 만들지는 못한다**
-- 남은 길은 **사람이 손으로 옮겨 적는 것**뿐이다. 자동화가 아니므로 약관 문제가 없고,
-- 관심 단지 5~10곳이면 수십 건이라 실제로 감당 가능한 양이다.
--
-- 설계 원칙 — 이 파일이 강제하는 것
-- =================================
-- (1) **출처를 섞지 않는다.** `source='user_entered'` ⟺ `created_by_user_id IS NOT NULL`
--     을 CHECK 로 못박는다. 한쪽만 채워진 행은 **DB 가 거절**한다. 애플리케이션 코드에만
--     두면 언젠가 스크립트가 그 규칙을 비켜가고, 그 순간 공공 데이터와 사용자 입력이
--     한 통에 섞여 "무엇이 근거였나"에 영원히 답할 수 없게 된다(G2).
-- (2) **입력 시점(`as_of`)은 필수다.** 호가는 빨리 낡는다. 사용자 입력 행에 as_of 가
--     없으면 그 값이 언제의 값인지 말할 수 없고, 말할 수 없는 값은 계산에 넣으면 안 된다.
--     `collected_at`(서버가 찍는 저장 시각)과 **다른 값**이다 — 3개월 전에 본 매물을
--     오늘 입력할 수 있고, 그 둘을 같게 보면 낡은 호가가 새 호가로 둔갑한다.
-- (3) **소유자 스코프.** 사용자 입력은 그 사용자만 본다. `app_user` FK + ON DELETE CASCADE.
-- (4) **말도 안 되는 값을 조용히 받지 않는다.** 아래 CHECK 는 **사용자 입력 행에만** 건다
--     (`created_by_user_id IS NULL OR ...`). 수집 경로의 계약을 건드리지 않으면서
--     손으로 치는 경로에만 그물을 치는 형태다 — API 검증(schemas.UserListingIn)과
--     **같은 숫자**를 쓴다. 두 곳이 갈라지면 API 를 우회하는 경로가 곧 구멍이 된다.
--
-- ⛔ 하지 않는 것
-- ===============
-- · `trust_score` 를 채우지 않는다(NULL 로 남긴다). 허위·미끼 탐지는 **여러 중개사의
--   중복 등록**을 세는 신호인데, 사용자가 자기 손으로 적은 한 건에는 그런 축이 없다.
--   숫자를 채우면 "매물 신뢰도 87점" 이라는 의미 없는 값이 리스크 축에 들어간다.
-- · `duplicate_of` 로 수집 행과 잇지 않는다(수집 행이 0이고, 서로 다른 신뢰도의 데이터다).
--
-- 적용: 신규 DB 는 001→…→016 자동. 기존 DB 는 psql -f 로 수동.
--       적용 시점 `listing` 0행이라 백필 대상이 없다(있었다면 전부 created_by_user_id
--       NULL = 수집분이 되고, CHECK 도 그대로 만족한다).

BEGIN;

-- --------------------------------------------------------------------------
-- 컬럼
-- --------------------------------------------------------------------------

ALTER TABLE listing
    ADD COLUMN IF NOT EXISTS created_by_user_id bigint
        REFERENCES app_user(id) ON DELETE CASCADE,
    -- 사용자가 이 호가를 **직접 확인한 날짜**. collected_at(저장 시각)과 다르다.
    ADD COLUMN IF NOT EXISTS as_of date,
    -- 동(棟) 원본 표기. `trade.apt_dong`(006)과 **같은 이름·같은 의미**로 둔다 —
    -- '101동' · '101' · '청담(103)' 이 섞여 들어온다. 파싱은 상위 계층에서.
    -- `building_id` 를 쓰지 않는 이유: building 테이블은 거의 비어 있어서 매칭이
    -- 실패하고, 실패한 매칭을 NULL 로 접으면 사용자가 적은 동 정보가 통째로 사라진다.
    ADD COLUMN IF NOT EXISTS apt_dong text,
    -- 사용자 메모(어느 중개사·무슨 조건). 근거 문자열에 그대로 나갈 수 있으므로 짧게.
    ADD COLUMN IF NOT EXISTS note text,
    ADD COLUMN IF NOT EXISTS updated_at timestamptz;

COMMENT ON COLUMN listing.created_by_user_id IS
    '이 호가를 손으로 입력한 사용자. NULL = 수집(공공/기관) 출처. '
    'source=''user_entered'' 와 반드시 짝을 이룬다(listing_user_source_pair CHECK).';
COMMENT ON COLUMN listing.as_of IS
    '사용자가 이 호가를 직접 확인한 날짜. collected_at(서버 저장 시각)과 다르다 — '
    '오래된 호가를 현재 호가처럼 쓰지 않기 위한 유일한 근거이며, 사용자 입력 행에는 필수.';
COMMENT ON COLUMN listing.apt_dong IS
    '동(棟) 원본 표기. trade.apt_dong(006)과 같은 규약. 사용자가 적은 그대로 보존한다.';
COMMENT ON COLUMN listing.note IS
    '사용자 메모(중개사·특이조건). 근거 문자열에 노출될 수 있어 200자로 제한한다.';

-- --------------------------------------------------------------------------
-- 무결성 — **출처 구분과 시점을 DB 가 강제한다**
-- --------------------------------------------------------------------------

-- ① 출처 짝맞춤. 이 제약이 이 마이그레이션의 핵심이다.
--    'user_entered' 인데 소유자가 없거나(고아 사용자 데이터),
--    소유자가 있는데 source 가 수집 출처인(공공 데이터로 위장된 사용자 입력) 행을 막는다.
ALTER TABLE listing DROP CONSTRAINT IF EXISTS listing_user_source_pair;
ALTER TABLE listing ADD CONSTRAINT listing_user_source_pair
    CHECK ((source = 'user_entered') = (created_by_user_id IS NOT NULL));

-- ② 사용자 입력에는 as_of 가 반드시 있다(시점 없는 호가는 계산에 못 넣는다).
--    now() 같은 비-IMMUTABLE 함수는 CHECK 에 쓰지 않는다 — "미래 날짜"·"너무 낡음"
--    판정은 앱 계층(schemas·repositories.base)이 하고, 여기서는 존재와 하한만 본다.
ALTER TABLE listing DROP CONSTRAINT IF EXISTS listing_user_as_of;
ALTER TABLE listing ADD CONSTRAINT listing_user_as_of
    CHECK (created_by_user_id IS NULL
           OR (as_of IS NOT NULL AND as_of >= DATE '2000-01-01'));

-- ③ 손으로 치는 값의 범위. **API 검증(schemas.UserListingIn)과 같은 숫자**다.
--    1천만원 미만 → '15'(억)·'150000'(만원) 같은 단위 실수.
--    1,000억 초과 → 슬라이더 오조작·자릿수 실수. affordability 의 target_price_krw
--    상한과 같은 값으로 맞춘다(같은 성격의 금액을 두 기준으로 검사하지 않는다).
ALTER TABLE listing DROP CONSTRAINT IF EXISTS listing_user_price_range;
ALTER TABLE listing ADD CONSTRAINT listing_user_price_range
    CHECK (created_by_user_id IS NULL
           OR ask_price_krw BETWEEN 10000000 AND 100000000000);

-- ④ 전용면적. 0·NULL 을 조용히 받으면 면적 조건 필터와 ₩/㎡ 계산이 통째로 무의미해진다.
--    상한 1000㎡ 는 AffordabilityIn.area_m2 와 같은 값이다.
ALTER TABLE listing DROP CONSTRAINT IF EXISTS listing_user_area_range;
ALTER TABLE listing ADD CONSTRAINT listing_user_area_range
    CHECK (created_by_user_id IS NULL
           OR (area_m2 IS NOT NULL AND area_m2 > 0 AND area_m2 <= 1000));

-- ⑤ 층. 지하(-5)~200층. smallint 범위(-32768~32767)만으로는 '9999층'을 막지 못한다.
ALTER TABLE listing DROP CONSTRAINT IF EXISTS listing_user_floor_range;
ALTER TABLE listing ADD CONSTRAINT listing_user_floor_range
    CHECK (created_by_user_id IS NULL OR floor IS NULL OR floor BETWEEN -5 AND 200);

-- ⑥ 메모 길이. 스키마와 같은 200자.
ALTER TABLE listing DROP CONSTRAINT IF EXISTS listing_user_note_len;
ALTER TABLE listing ADD CONSTRAINT listing_user_note_len
    CHECK (note IS NULL OR length(note) <= 200);

-- ⑦ 동 표기 길이(원본 보존이되 무한정은 아니다).
ALTER TABLE listing DROP CONSTRAINT IF EXISTS listing_user_dong_len;
ALTER TABLE listing ADD CONSTRAINT listing_user_dong_len
    CHECK (apt_dong IS NULL OR length(apt_dong) <= 20);

-- --------------------------------------------------------------------------
-- 인덱스
-- --------------------------------------------------------------------------

-- 내 매물 목록(`GET /me/listings`) · 소유자 스코프 조회.
-- 부분 인덱스라 수집 행(대다수가 될 예정)은 색인에 들어가지 않는다.
CREATE INDEX IF NOT EXISTS idx_listing_user
    ON listing (created_by_user_id, complex_id, as_of DESC)
    WHERE created_by_user_id IS NOT NULL;

-- 추천 읽기 경로: (단지, 활성, 소유자). 기존 `idx_listing_active` 는 complex_id 만
-- 보므로, 사용자 행이 늘어나면 같은 단지 안에서 남의 행까지 훑게 된다.
CREATE INDEX IF NOT EXISTS idx_listing_user_active
    ON listing (complex_id, created_by_user_id, as_of DESC)
    WHERE status = 'active' AND created_by_user_id IS NOT NULL;

COMMIT;
