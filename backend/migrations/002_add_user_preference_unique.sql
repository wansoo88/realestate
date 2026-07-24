-- 002_add_user_preference_unique.sql
-- 사용자당 선호 조건은 **1세트**다 (요구사항 · API 는 단일 upsert: PUT /me/preferences).
-- 001 에는 UNIQUE 가 없어 ON CONFLICT 를 쓸 수 없었고, 동시에 저장하면 행이 둘 생겼다.
-- 승인: re-pm (2026-07-25, ORDER 2026-07-25-03-arch 회신)
--
-- 적용
--   신규 DB : docker-entrypoint-initdb.d 가 001 → 002 순서로 자동 적용한다.
--   기존 DB : psql -f 로 수동 적용. 아래 DELETE 가 **중복 행을 지운다**.

BEGIN;

-- 제약을 걸기 전에 이미 생긴 중복을 정리한다.
-- 남기는 기준은 **가장 오래된 행(작은 id)** — 002 이전의 get_preferences 가
-- `ORDER BY id LIMIT 1` 로 읽던 바로 그 행이다. 사용자가 보던 값이 바뀌지 않는다.
DELETE FROM user_preference a
      USING user_preference b
      WHERE a.user_id = b.user_id
        AND a.id > b.id;

ALTER TABLE user_preference
      ADD CONSTRAINT user_preference_user_id_key UNIQUE (user_id);

COMMIT;
