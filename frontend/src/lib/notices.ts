/**
 * 고지 문구 — **한 곳에서만 관리한다**.
 *
 * 화면마다 다르게 쓰면 고지가 아니라 장식이 된다(components.md §3.4).
 * 서버 응답(`note`)에 의존하면 응답에 없는 화면에서는 고지가 사라진다(audit F-12).
 */

/** 시세가 하나라도 보이는 화면이면 **항상** 붙인다 (ux/README.md §7). */
export const NOTICE_TRADE_DELAY =
  "실거래는 신고까지 최대 30일이 걸립니다. 최근 거래가 반영되지 않았을 수 있습니다.";

/** 이 서비스는 투자 자문이 아니다 (CHARTER §5-4). */
export const NOTICE_NOT_ADVICE = "투자 권유가 아니며 개인 판단을 돕는 참고 자료입니다.";

/**
 * 민감 정보를 요구하는 화면의 신뢰 문구 (components.md §3.6).
 *
 * ⚠️ 이 문장은 **구현이 실제로 그럴 때만** 쓸 수 있다. 근거:
 * - 암호화 저장: `backend/app/core/crypto.py` (AES-256-GCM 필드 암호화)
 * - 외부 AI 미전송: `backend/app/agents/orchestrator.py` `assert_no_secrets` tripwire
 *   + finding 이 파생값만 싣는 구조 (security.md §6)
 */
export const NOTICE_TRUST =
  "자산·소득 정보는 암호화해 저장하며, 외부 AI에는 금액이 전송되지 않습니다.";
