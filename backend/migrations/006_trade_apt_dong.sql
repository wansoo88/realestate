-- 006_trade_apt_dong.sql
-- ORDER 2026-07-25-molit (PM 직접 수정 · herdr 우회)
--
-- trade.apt_dong 추가 — 설계 가정(erd §0 "동 정보 없음") 정정
--   운영 MOLIT API(RTMSDataSvcAptTrade)는 aptDong 을 **77~93% 제공**한다
--   (강남87·분당93·인천91·종로77%, 2026-07-25 발급키 실측). 설계 초안은 개발용
--   엔드포인트만 보고 "동 없음"으로 판단했으나, 운영 응답에는 존재한다.
--   → F4(동별 가치 차이)를 좌표 추정이 아니라 **실거래 기반 실측**으로 할 수 있다.
--
-- ⛔ apt_dong 을 자연키(trade_natural_key, 004)에 추가하지 말 것
--   결측이 10~23% 있어, 키에 넣으면 NULL 이 섞여 같은 거래가 여러 행으로 흩어진다
--   (004 가 unit_type_id 를 키에서 뺀 것과 동일한 논리 — "키는 흔들리면 안 된다").
--   apt_dong 은 **부가 컬럼으로만** 저장하고, 적재 시 COALESCE 로 기존 값을
--   덮어쓰지 않게 채운다(loader._upsert_trade). 결측분은 F4 에서 좌표추정 폴백.
--
-- 원본 표기 보존: '410'·'114'(동번호)와 '청담(103)'(이름+번호)이 혼재해 온다.
--   정규화는 strip + 빈값/'-'/'0' → NULL 까지만(molit.normalize_apt_dong).
--   숫자/이름 파싱은 F4 매칭 계층에서 building.name 과 대조하며 처리한다.
--
-- 적용: 신규 DB 는 001→…→006 자동. 기존 DB 는 psql -f 로 수동.
-- 파티션 부모(trade)에 ADD COLUMN 하면 모든 연도 파티션에 전파된다(무중단, NULL 기본).

BEGIN;

ALTER TABLE trade ADD COLUMN IF NOT EXISTS apt_dong text;

COMMENT ON COLUMN trade.apt_dong IS
    '실거래 동(棟). 운영 MOLIT API 가 77~93% 제공(2026-07-25 실측). '
    '원본 표기 보존(410 / 청담(103) 혼재). 자연키 아님 — 결측 있어 키 흔들림 방지(004 논리). '
    'F4 동별 실측용, 결측분은 좌표추정 폴백.';

-- F4 동별 집계 조회용 부분 인덱스. 결측(NULL)은 좌표추정으로 가므로 색인 대상이 아니다.
-- 파티션 부모에 만들면 각 연도 파티션에 대응 인덱스가 자동 생성된다.
CREATE INDEX IF NOT EXISTS trade_complex_apt_dong_idx
    ON trade (complex_id, apt_dong)
    WHERE apt_dong IS NOT NULL;

COMMIT;
