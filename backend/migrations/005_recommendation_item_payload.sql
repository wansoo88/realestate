-- 005_recommendation_item_payload.sql
-- 승인: re-pm (2026-07-25, ORDER 2026-07-25-26-arch 회신)
--   "headline·why·why_not·next_actions·판단보류사유가 응답에서 사라지면 추천이 반쪽이다."
--
-- 왜 별도 컬럼이 필요한가
-- -----------------------
-- 파이프라인이 만든 추천 항목에는 사용자가 실제로 읽는 것들이 들어 있다:
--   headline · why · why_not · next_actions
--   그리고 각 finding 의 risks · missing(판단 보류 사유)
--
-- 그런데 `recommendation_item` 의 컬럼은 rank·total_score·est_price_krw·timing_signal
-- 뿐이라 **이 본문을 담을 자리가 없다.** 정규화 컬럼만으로 되살리면 사용자는
-- 순위와 점수만 보고 "왜 이 단지인지"를 못 본다 — 이 제품의 유일한 가치가 근거인데.
--
-- 더해 `agent_finding` 은 `CHECK (jsonb_array_length(evidence) > 0)` 이라
-- **근거 없는 '판단 보류' finding 을 저장할 수 없다.** 이건 의도된 설계(G2)이고
-- 그대로 둔다 — 다만 그러면 "왜 판단을 보류했는지"까지 사라지므로 여기 남긴다.
--
-- 역할 분담
--   payload            → **보여줄 것** (API 응답 본문 복원)
--   정규화 컬럼·agent_finding → **따질 것** (집계·정렬·근거 감사)
-- 둘은 대체재가 아니라 용도가 다르다. 정규화 컬럼은 그대로 유지한다.
--
-- 적용: 신규 DB 는 001→…→005 자동. 기존 DB 는 psql -f 로 수동.
--       기존 행은 payload 가 NULL 이고, 그 경우 정규화 컬럼으로 최소 복원한다
--       (app/repositories/postgis.py `_item_to_dict`).

BEGIN;

ALTER TABLE recommendation_item
    ADD COLUMN IF NOT EXISTS payload jsonb;

COMMENT ON COLUMN recommendation_item.payload IS
    '파이프라인 항목 원본 JSON. API 응답 본문(headline·why·why_not·next_actions)과 '
    '근거 없는 판단보류 finding 의 사유를 보존한다. '
    '집계·정렬·근거 감사는 정규화 컬럼과 agent_finding 을 쓴다.';

COMMIT;
