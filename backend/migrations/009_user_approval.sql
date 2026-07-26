-- 009_user_approval.sql
-- 회원가입 관리자 승인제 — "아무나 가입해서 바로 쓰는" 상태를 끝낸다.
--
-- 왜 필요한가
-- ----------
-- 서비스가 공인 IP 로 이미 공개돼 있고(https://realestate.utilverse.info),
-- 가입은 이메일+비밀번호만으로 끝난다. 이 서비스가 다루는 값은 **보유현금·연소득·
-- 기존대출**이라(security.md §0) 계정 하나가 곧 개인 금융정보 저장소 하나다.
-- 지금까지는 nginx 에서 `/auth/register` 를 403 으로 막아 두는 임시 조치로 버텼다.
-- 이 마이그레이션은 그 임시 조치를 **제품 기능**으로 대체한다.
--
-- 이 마이그레이션이 하는 일
-- -------------------------
--   app_user.status            'pending' | 'approved' | 'rejected'  (기본 pending)
--   app_user.is_admin          관리자 여부. **토큰이 아니라 이 컬럼이 진실이다.**
--   app_user.status_changed_*  현재 상태의 감사 흔적(언제·누가·왜)
--   user_status_event          상태 변경 **이력**(append-only)
--
-- ⚠️ 기존 계정은 전부 'pending' 이 된다 (NOT NULL DEFAULT 'pending' 의 결과다)
-- ------------------------------------------------------------------------
-- 의도한 동작이다. 승인제를 켜면서 기존 계정만 자동 승인하면, 차단 이전에 선점된
-- 계정이 그대로 통과한다. 적용 시점의 운영 DB 에는 계정이 1건 있으며(2026-07-26 실측),
-- **적용 직후 로그인이 막힌다.** 복구는 서버에서:
--     python scripts/manage_users.py --list
--     python scripts/manage_users.py --approve <email>
--     python scripts/manage_users.py --grant-admin <email>
--
-- 첫 관리자를 왜 SQL 로 만들지 않는가
-- ----------------------------------
-- "첫 가입자를 관리자로" 같은 자동 승격은 공개된 사이트에서 **선점 가능**하다.
-- 여기서 특정 이메일을 승격시키는 것도 마이그레이션 파일에 개인 계정을 박는 셈이라
-- 하지 않는다. 관리자 부여는 SSH 가 있어야 실행되는 CLI 로만 한다(scripts/manage_users.py).
--
-- 하지 않는 일 (의도적)
-- ---------------------
--   * 파티션(trade)·자연키(004)·007·008 은 건드리지 않는다.
--   * 비밀번호에 손대지 않는다. 승인은 **접근 권한**이지 자격증명이 아니다.
--
-- ⚠️ 적용 순서: **이 마이그레이션이 코드 배포보다 먼저다.**
-- ----------------------------------------------------------
-- 새 코드는 모든 사용자 조회에서 status·is_admin 컬럼을 읽는다. 컬럼 없이 새 코드를
-- 띄우면 로그인·토큰검증이 전부 500 이 된다(조용히 우회하지 않는다 — 의도한 실패다).
--   docker exec -i realestate-db psql -U realestate -d realestate \
--       -v ON_ERROR_STOP=1 -f - < backend/migrations/009_user_approval.sql
-- 신규 DB 는 001→…→009 가 자동 적용된다.
--
-- 검증 이력: 2026-07-26, 운영 DB 에서 **롤백되는 트랜잭션**으로 두 번 확인했다.
--   (1) 빈 스키마에 001→009 전체 적용  (2) 운영 스키마에 009 단독 적용
--   두 경우 모두 성공 후 ROLLBACK — 운영 데이터·스키마는 변경되지 않았다.

BEGIN;

-- 1) 상태 -------------------------------------------------------------------
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'pending';
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS is_admin boolean NOT NULL DEFAULT false;

-- 감사 흔적: 지금 상태가 **언제·누가·왜** 그렇게 됐는가.
-- 이력 전체는 아래 user_status_event 가 갖는다(이 컬럼들은 최신 1건만 덮어쓴다).
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS status_changed_at timestamptz;
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS status_changed_by bigint;
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS status_reason text;

-- 오타로 조용히 이상한 상태가 들어가는 걸 막는다. 여기 없는 값은 애플리케이션이
-- 'approved 아님'으로 보므로 **잘못 들어가면 잠기는 쪽**으로 실패한다(안전한 방향).
ALTER TABLE app_user DROP CONSTRAINT IF EXISTS app_user_status_chk;
ALTER TABLE app_user ADD CONSTRAINT app_user_status_chk
    CHECK (status IN ('pending', 'approved', 'rejected'));

-- 승인자는 다른 사용자다(자기참조). 승인자 계정이 지워져도 피승인자 행은 남아야 하므로
-- SET NULL — 감사 흔적이 사라지지만 계정이 함께 사라지는 것보다 낫다.
-- (이력 테이블에는 그 시점의 actor 종류가 그대로 남는다.)
ALTER TABLE app_user DROP CONSTRAINT IF EXISTS app_user_status_changed_by_fkey;
ALTER TABLE app_user ADD CONSTRAINT app_user_status_changed_by_fkey
    FOREIGN KEY (status_changed_by) REFERENCES app_user(id) ON DELETE SET NULL;

COMMENT ON COLUMN app_user.status IS
    '가입 승인 상태. pending=관리자 검토 대기(기본), approved=로그인 가능, rejected=거부. '
    'approved 가 아니면 로그인·토큰 갱신·API 접근이 모두 막힌다.';
COMMENT ON COLUMN app_user.is_admin IS
    '관리자 여부. 관리자 API 인가의 **유일한 진실 소스**다 — JWT 에 admin 클레임을 넣지 않는다'
    '(클라이언트가 주장하게 만들면 위조된다).';
COMMENT ON COLUMN app_user.status_changed_by IS
    '상태를 바꾼 관리자 id. CLI(scripts/manage_users.py)로 바꾸면 NULL 이고, '
    'user_status_event.actor = ''cli'' 로 구분된다.';

-- 대기 목록 조회용. 전체가 아니라 '검토해야 하는 쪽'만 색인한다.
CREATE INDEX IF NOT EXISTS idx_app_user_pending
    ON app_user (created_at) WHERE status = 'pending';
-- 마지막 관리자 보호(관리자 수 세기)가 매 변경마다 도는 조회.
CREATE INDEX IF NOT EXISTS idx_app_user_admin
    ON app_user (id) WHERE is_admin;

-- 2) 상태 변경 이력 (append-only) --------------------------------------------
-- app_user 의 status_changed_* 는 덮어쓰기라 "언제 거부됐다가 언제 승인됐는지"를
-- 못 남긴다. 승인제의 요점이 "누가 이 계정을 들여보냈는가"라 이력을 따로 남긴다.
CREATE TABLE IF NOT EXISTS user_status_event (
    id            bigserial PRIMARY KEY,
    user_id       bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    -- 상태 3종 + 가입 + 관리자 권한 변경. 상태값(pending/approved/rejected)을 그대로
    -- 이벤트명으로 쓴다 — 상태를 되돌리는 변경도 이력에 남길 수 있어야 한다.
    event         text NOT NULL CHECK (event IN (
                      'registered', 'pending', 'approved', 'rejected',
                      'admin_granted', 'admin_revoked')),
    reason        text,
    -- 누가 했나: 관리자 API 인가, 서버에서 실행한 CLI 인가.
    actor         text NOT NULL CHECK (actor IN ('admin_api', 'cli', 'self')),
    actor_user_id bigint REFERENCES app_user(id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_user_status_event_user
    ON user_status_event (user_id, created_at DESC);

COMMENT ON TABLE user_status_event IS
    '가입 승인 상태 변경 이력(append-only). 지우거나 UPDATE 하지 않는다 — '
    '"누가 언제 이 계정을 들여보냈는가"에 답하는 유일한 기록이다.';
COMMENT ON COLUMN user_status_event.actor IS
    'admin_api=로그인한 관리자가 API 로, cli=서버에서 scripts/manage_users.py 로, '
    'self=본인 가입 신청.';

COMMIT;
