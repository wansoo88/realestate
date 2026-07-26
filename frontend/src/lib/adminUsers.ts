/**
 * 관리자 화면의 **순수 로직** — 정제·라벨·목록 반영 (뷰 비의존, RN 재사용).
 *
 * 이 파일의 존재 이유는 하나다: **관리자에게도 남의 금융정보를 보여주지 않는다.**
 * 서버(`AdminUserOut`)가 이미 자산·소득·비밀번호 해시를 빼고 주지만, 그 보장은
 * 백엔드 스키마 한 줄이 바뀌면 사라진다. 화면 쪽에도 문을 하나 더 둔다 —
 * **허용 목록(allowlist)** 이라 새 필드는 기본이 "안 보임"이다.
 * (api-spec §6.3 / security.md §3.1: 관리자는 가입 승인만 한다)
 */
import { ApiException } from "../api/client";

export type UserStatus = "pending" | "approved" | "rejected";
export type StatusFilter = UserStatus | "all";

/** 화면이 렌더해도 되는 필드 **전부**. 여기 없는 값은 존재하지 않는 것처럼 다룬다. */
export interface AdminUserSummary {
  id: number;
  email: string;
  status: UserStatus | "unknown";
  is_admin: boolean;
  created_at: string | null;
  status_changed_at: string | null;
  status_reason: string | null;
}

/**
 * 절대 화면에 닿으면 안 되는 키. 허용 목록만으로도 걸러지지만,
 * **들어왔다는 사실 자체가 백엔드 회귀**라 화면에 경고를 띄우려고 따로 센다.
 */
export const SENSITIVE_KEYS = [
  "cash_krw",
  "income_krw",
  "existing_loan_krw",
  "existing_annual_repayment_krw",
  "existing_annual_interest_krw",
  "owned_houses",
  "household_size",
  "password",
  "password_hash",
  "access_token",
  "refresh_token",
] as const;

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function asStatus(v: unknown): UserStatus | "unknown" {
  return v === "pending" || v === "approved" || v === "rejected" ? v : "unknown";
}

/** 문자열만 통과. 숫자·객체가 오면 렌더하지 않는다(문자열 강제변환으로 [object Object] 를 만들지 않는다). */
function asText(v: unknown): string | null {
  return typeof v === "string" && v.trim() !== "" ? v : null;
}

export function hasSensitiveKeys(raw: unknown): boolean {
  if (!isRecord(raw)) return false;
  return SENSITIVE_KEYS.some((k) => k in raw);
}

/**
 * 원본 → 화면용. 허용 목록 밖의 값은 **전부 버린다.**
 * id·email 이 없으면 정체를 알 수 없는 행이므로 통째로 버린다(null).
 */
export function sanitizeAdminUser(raw: unknown): AdminUserSummary | null {
  if (!isRecord(raw)) return null;
  const id = raw.id;
  const email = asText(raw.email);
  if (typeof id !== "number" || !Number.isFinite(id) || email === null) return null;

  return {
    id,
    email,
    status: asStatus(raw.status),
    is_admin: raw.is_admin === true,
    created_at: asText(raw.created_at),
    status_changed_at: asText(raw.status_changed_at),
    status_reason: asText(raw.status_reason),
  };
}

export interface SanitizedUsers {
  users: AdminUserSummary[];
  /** 민감 필드가 섞여 왔는가 — 화면이 조용히 삼키지 않고 알리기 위한 신호. */
  droppedSensitive: boolean;
}

export function sanitizeAdminUsers(items: unknown): SanitizedUsers {
  if (!Array.isArray(items)) return { users: [], droppedSensitive: false };
  const users: AdminUserSummary[] = [];
  let droppedSensitive = false;
  for (const raw of items) {
    if (hasSensitiveKeys(raw)) droppedSensitive = true;
    const user = sanitizeAdminUser(raw);
    if (user) users.push(user);
  }
  return { users, droppedSensitive };
}

export const STATUS_LABEL: Record<AdminUserSummary["status"], string> = {
  pending: "승인 대기",
  approved: "승인됨",
  rejected: "거부됨",
  unknown: "알 수 없음",
};

/**
 * 승인·거부 결과를 목록에 반영한다.
 *
 * 목록을 다시 불러오지 않고 그 자리에서 고치는 이유: 승인 버튼을 눌렀는데 화면이
 * 그대로면 사용자는 한 번 더 누른다. 지금 보고 있는 필터에서 벗어난 항목은 **사라져야**
 * 맞다(대기 목록에서 승인한 사람은 더 이상 대기자가 아니다).
 */
export function applyUserUpdate(
  users: AdminUserSummary[],
  updated: AdminUserSummary,
  filter: StatusFilter,
): AdminUserSummary[] {
  if (filter !== "all" && updated.status !== filter) {
    return users.filter((u) => u.id !== updated.id);
  }
  const known = users.some((u) => u.id === updated.id);
  return known ? users.map((u) => (u.id === updated.id ? updated : u)) : [...users, updated];
}

export function pendingCount(users: AdminUserSummary[]): number {
  return users.filter((u) => u.status === "pending").length;
}

/** "2026-07-26T04:14:36Z" → "2026년 7월 26일". 형식이 다르면 지어내지 않고 원문을 준다. */
export function formatDay(iso: string | null): string {
  if (!iso) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[1]}년 ${Number(m[2])}월 ${Number(m[3])}일` : iso;
}

/**
 * 승인·거부 실패 문구.
 *
 * - **409 `LAST_ADMIN`**: 숨길 정보가 아니라 **왜 안 되는지 알려줘야 하는** 상황이다.
 *   여기서 "실패했습니다"로 뭉개면 사용자는 버튼을 계속 누른다.
 * - **404**: 대상이 없거나 **내 관리자 권한이 사라졌거나** 둘 중 하나다(서버는 구분하지 않는다).
 *   그래서 문구도 단정하지 않고 "목록을 다시 불러온다"로 안내한다.
 */
export function adminActionErrorMessage(err: unknown): string {
  if (err instanceof ApiException) {
    if (err.status === 409 && err.error.code === "LAST_ADMIN") {
      return "마지막 관리자는 거부·강등할 수 없습니다. 관리자가 0명이 되면 어떤 가입도 승인할 수 없어 서버에서 직접 복구해야 합니다.";
    }
    if (err.status === 404) {
      return "처리하지 못했습니다. 대상이 이미 변경되었을 수 있어 목록을 다시 불러옵니다.";
    }
    if (err.status === 422 || err.error.code === "INVALID_PARAM") {
      return "입력값을 확인해 주세요. 사유는 500자 이내입니다.";
    }
    return err.error.message || "처리하지 못했습니다.";
  }
  return "네트워크 오류로 처리하지 못했습니다.";
}

/** 거부 사유 입력 제한 — 서버 `RejectIn.reason` 의 `max_length=500` 과 같은 값. */
export const REJECT_REASON_MAX = 500;
