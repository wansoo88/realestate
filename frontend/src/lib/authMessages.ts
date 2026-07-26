/**
 * 로그인·가입 화면의 문구 결정 — **순수 함수**(뷰 비의존, RN 재사용).
 *
 * 왜 문구를 뷰에서 떼어냈나
 * -------------------------
 * "어떤 실패에 어떤 문구를 보이는가"는 디자인이 아니라 **보안 규약**이다(SR10-1).
 * 컴포넌트 안에 if 로 흩어 두면 다음 사람이 친절하게 세분화하다가 계정 열거 구멍을 연다.
 * 그래서 규칙을 한 파일에 모으고 테스트로 못박는다.
 *
 * 규약
 * ----
 * 1. **401 은 언제나 똑같은 한 문장이다.** 없는 계정·틀린 비밀번호를 구분하지 않는다.
 *    서버가 본문·상태·응답시간까지 동일하게 맞춰 두었는데(api-spec §1.5) 화면이
 *    문구를 갈라 놓으면 그 노력이 통째로 무의미해진다.
 * 2. 403 `PENDING_APPROVAL`/`ACCOUNT_REJECTED` 만 상태를 알려준다. 이 응답은
 *    **비밀번호가 맞았을 때만** 오므로, 그 계정의 비밀번호를 아는 사람에게만 보인다.
 */
import { ApiException, isApprovalCode, type ApprovalCode, type AuthNotice } from "../api/client";

/**
 * 로그인 실패 단일 문구.
 *
 * ⚠️ 이 상수를 상태별로 쪼개지 마라. "가입되지 않은 이메일입니다" 같은 친절한 문구
 * 하나면 로그인 폼이 **가입 여부 조회 API** 가 된다.
 */
export const LOGIN_FAILED_MESSAGE = "이메일 또는 비밀번호가 올바르지 않습니다.";

/** 가입 접수 안내(서버 message 가 비었을 때의 대비값). */
export const REGISTER_PENDING_MESSAGE =
  "가입 신청이 접수되었습니다. 관리자 승인 후 로그인할 수 있습니다.";

/** 서버 문구를 그대로 싣기 전에 길이를 자른다(레이아웃 파괴·과다 노출 방지). */
const MAX_SERVER_TEXT = 200;

function trim(text: string | null | undefined): string {
  const v = (text ?? "").trim();
  return v.length > MAX_SERVER_TEXT ? `${v.slice(0, MAX_SERVER_TEXT)}…` : v;
}

/** 화면에 띄울 안내 한 덩어리. `tone` 은 색이 아니라 **의미**다(색만으로 전달 금지). */
export interface AuthBanner {
  /** pending = 기다리면 되는 상태, rejected = 사용자가 할 수 있는 게 없는 상태 */
  tone: "pending" | "rejected" | "submitted";
  title: string;
  body: string;
}

const APPROVAL_TITLE: Record<ApprovalCode, string> = {
  PENDING_APPROVAL: "승인 대기 중입니다",
  ACCOUNT_REJECTED: "가입이 거부되었습니다",
};

const APPROVAL_BODY: Record<ApprovalCode, string> = {
  PENDING_APPROVAL:
    "가입 신청은 접수되었습니다. 관리자가 승인하면 같은 계정으로 로그인할 수 있습니다.",
  ACCOUNT_REJECTED: "이 계정으로는 로그인할 수 없습니다. 관리자에게 문의해 주세요.",
};

/**
 * 승인 상태 403 → 안내 배너.
 *
 * `reason` 은 **서버가 줄 때만** 덧붙인다. 현재 계약상 로그인 응답에는 사유가 실리지
 * 않지만(감사 기록 전용), 나중에 실리면 사용자가 바로 이해할 수 있게 자리를 비워 둔다.
 */
export function approvalBanner(code: ApprovalCode, reason?: string | null): AuthBanner {
  const extra = trim(reason);
  return {
    tone: code === "ACCOUNT_REJECTED" ? "rejected" : "pending",
    title: APPROVAL_TITLE[code],
    body: extra ? `${APPROVAL_BODY[code]} (사유: ${extra})` : APPROVAL_BODY[code],
  };
}

/** 세션 도중 승인이 회수돼 client 가 남긴 안내 → 배너. */
export function bannerFromNotice(notice: AuthNotice | null): AuthBanner | null {
  return notice ? approvalBanner(notice.code, notice.reason) : null;
}

export type AuthFeedback =
  | { kind: "error"; message: string }
  | { kind: "banner"; banner: AuthBanner };

/**
 * 로그인 실패 → 화면 피드백.
 *
 * 순서가 중요하다: **401 을 가장 먼저** 잡아 단일 문구로 끝낸다. 뒤에 어떤 분기를
 * 추가하더라도 401 은 그 분기들에 닿지 못한다.
 */
export function loginFeedback(err: unknown): AuthFeedback {
  if (err instanceof ApiException) {
    // ── 계정 열거 방지선 ── (서버 code·message 를 **보지 않는다**)
    if (err.status === 401) return { kind: "error", message: LOGIN_FAILED_MESSAGE };

    if (err.status === 403 && isApprovalCode(err.error.code)) {
      return { kind: "banner", banner: approvalBanner(err.error.code, err.error.reason) };
    }
    if (err.status === 429) {
      return { kind: "error", message: "시도가 많습니다. 잠시 후 다시 시도해 주세요." };
    }
    if (err.status === 422 || err.error.code === "INVALID_PARAM") {
      return { kind: "error", message: "입력값을 확인해 주세요." };
    }
    return { kind: "error", message: trim(err.error.message) || "요청을 처리하지 못했습니다." };
  }
  return { kind: "error", message: "로그인에 실패했습니다. 네트워크를 확인해 주세요." };
}

/** 가입 실패 → 문구. 가입은 `409 EMAIL_TAKEN` 을 알려주는 기존 계약을 유지한다. */
export function registerErrorMessage(err: unknown): string {
  if (err instanceof ApiException) {
    if (err.error.code === "EMAIL_TAKEN") {
      return "이미 신청되었거나 가입된 이메일입니다. 승인 여부는 관리자에게 문의해 주세요.";
    }
    if (err.status === 422 || err.error.code === "INVALID_PARAM") {
      return "입력값을 확인해 주세요. 비밀번호는 12자 이상이어야 합니다.";
    }
    if (err.status === 429) return "시도가 많습니다. 잠시 후 다시 시도해 주세요.";
    return trim(err.error.message) || "가입 신청을 처리하지 못했습니다.";
  }
  return "가입에 실패했습니다. 네트워크를 확인해 주세요.";
}

/** 가입 접수 배너. 서버 문구가 있으면 그대로 쓰되(계약이 정한 안내), 없으면 대비값. */
export function registerSubmittedBanner(serverMessage?: string | null): AuthBanner {
  return {
    tone: "submitted",
    title: "가입 신청이 접수되었습니다",
    body: trim(serverMessage) || REGISTER_PENDING_MESSAGE,
  };
}
