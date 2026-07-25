-- 004_trade_natural_key.sql
-- ORDER 2026-07-25-26-arch (re-domain·re-data 핸드오프)
--
-- trade 자연키 유니크 인덱스 (re-data 권장 · INGEST-2)
--    국토부 실거래가에는 **거래 고유 ID 가 없다.** 매일 배치가 같은 기간을 다시
--    받아오면 같은 거래가 계속 쌓인다. 그러면 시세 통계의 표본 수가 부풀고
--    (MIN_SAMPLE 을 가짜로 넘긴다) 중위가가 왜곡된다 — 숫자가 조용히 틀리는 최악의 형태다.
--    자연키에 유니크를 걸어 `ON CONFLICT DO UPDATE` 로 **멱등 적재**가 되게 한다.
--
-- 적용: 신규 DB 는 001→…→004 자동. 기존 DB 는 psql -f 로 수동.

BEGIN;

-- 파티션 테이블의 유니크 제약에는 **파티션 키(contract_date)가 반드시 포함**돼야 한다.
-- 자연키에 이미 들어 있으므로 그대로 성립한다.
--
-- ⛔⛔ `is_cancelled` 를 자연키에 넣지 말 것 (INGEST-2 · 해제거래 시세조작 방어)
--   넣으면 같은 거래의 '정상' 행과 '해제' 행이 **서로 다른 키**가 되어 둘 다 유니크를
--   통과한다. 그러면 해제된 거래가 지워지지 않고 정상 행 옆에 남는다.
--   실제 공격: 높은 가격에 계약 → 신고 → 해제. 해제 신고가 별도 행으로 들어오면
--   원래의 허위 고가 행이 그대로 살아 있어 **시세가 위로 조작된다.**
--   자연키에서 빼야 `ON CONFLICT DO UPDATE` 가 **기존 행의 is_cancelled 를 갱신**하고,
--   통계 계층이 그 한 행을 해제로 보고 제외할 수 있다.
--   → 나중에 "해제도 이력으로 남기자"며 이 컬럼을 키에 추가하면 방어가 조용히 깨진다.
--
-- NULLS NOT DISTINCT 를 쓰는 이유 (PostgreSQL 15+):
--   기본 동작에서는 NULL 끼리 서로 다른 값으로 취급돼 유니크가 걸리지 않는다.
--   실거래 원본에는 floor·area_m2 가 비는 행이 있고, 그 행들이 바로
--   **중복 적재가 가장 많이 생기는 자리**다. 기본값으로 두면 막으려던 걸 못 막는다.
--
-- 면적은 `area_m2`(원본 값)를 쓰고 `unit_type_id` 는 쓰지 않는다:
--   unit_type_id 는 면적으로 되찾는 파생값이라 NULL 이 될 수 있고(매칭 실패),
--   unit_type 이 나중에 적재되면 같은 거래의 키가 **바뀐다.** 키는 흔들리면 안 된다.
ALTER TABLE trade
    ADD CONSTRAINT trade_natural_key
    UNIQUE NULLS NOT DISTINCT (complex_id, contract_date, price_krw, area_m2, floor);

COMMENT ON CONSTRAINT trade_natural_key ON trade IS
    '실거래 자연키. 원본에 거래 ID 가 없어 이 조합으로 중복 적재를 막는다. '
    'is_cancelled 는 **의도적으로 제외** — 포함하면 해제행이 별도 행으로 남아 '
    '허위 고가 거래가 시세에 계속 반영된다(INGEST-2). '
    '적재는 ON CONFLICT DO UPDATE SET is_cancelled=EXCLUDED.is_cancelled 로.';

COMMIT;
