/**
 * 관리자 목록의 순수 로직 테스트.
 *
 * 핵심은 하나: **허용 목록 밖의 값은 화면 모델에 들어오지 못한다.**
 * 백엔드가 실수로 자산을 실어 보내도 프론트가 그것을 렌더할 수 없어야 한다.
 */
import { describe, expect, it } from "vitest";
import { ApiException } from "../api/client";
import {
  SENSITIVE_KEYS,
  adminActionErrorMessage,
  applyUserUpdate,
  formatDay,
  hasSensitiveKeys,
  pendingCount,
  sanitizeAdminUser,
  sanitizeAdminUsers,
  type AdminUserSummary,
} from "./adminUsers";

const RAW = {
  id: 12,
  email: "me@example.com",
  status: "pending",
  is_admin: false,
  created_at: "2026-07-26T04:14:36Z",
  status_changed_at: null,
  status_changed_by: null,
  status_reason: null,
};

function user(over: Partial<AdminUserSummary> = {}): AdminUserSummary {
  return {
    id: 1,
    email: "a@example.com",
    status: "pending",
    is_admin: false,
    created_at: null,
    status_changed_at: null,
    status_reason: null,
    ...over,
  };
}

describe("정제 — 허용 목록", () => {
  it("계약대로 온 사용자는 그대로 통과한다", () => {
    expect(sanitizeAdminUser(RAW)).toEqual({
      id: 12,
      email: "me@example.com",
      status: "pending",
      is_admin: false,
      created_at: "2026-07-26T04:14:36Z",
      status_changed_at: null,
      status_reason: null,
    });
  });

  it("자산·소득·해시가 섞여 와도 화면 모델에 남지 않는다", () => {
    const leaked = {
      ...RAW,
      cash_krw: 300_000_000,
      income_krw: 90_000_000,
      existing_loan_krw: 50_000_000,
      password_hash: "$argon2id$v=19$...",
      refresh_token: "eyJ...",
    };

    const clean = sanitizeAdminUser(leaked);

    expect(clean).not.toBeNull();
    const keys = Object.keys(clean ?? {});
    for (const sensitive of SENSITIVE_KEYS) expect(keys).not.toContain(sensitive);
    expect(JSON.stringify(clean)).not.toContain("300000000");
    expect(JSON.stringify(clean)).not.toContain("argon2");
  });

  it("민감 필드가 섞여 온 사실 자체는 알린다(조용히 삼키지 않는다)", () => {
    expect(hasSensitiveKeys({ ...RAW, cash_krw: 1 })).toBe(true);
    expect(hasSensitiveKeys(RAW)).toBe(false);

    const out = sanitizeAdminUsers([{ ...RAW, income_krw: 1 }]);
    expect(out.droppedSensitive).toBe(true);
    expect(out.users).toHaveLength(1);
  });

  it("id·email 이 없는 행은 통째로 버린다", () => {
    expect(sanitizeAdminUser({ email: "a@b.c" })).toBeNull();
    expect(sanitizeAdminUser({ id: 1 })).toBeNull();
    expect(sanitizeAdminUser({ id: "1", email: "a@b.c" })).toBeNull();
    expect(sanitizeAdminUser(null)).toBeNull();
    expect(sanitizeAdminUsers("not an array").users).toEqual([]);
  });

  it("모르는 status 는 지어내지 않고 unknown 으로 둔다", () => {
    expect(sanitizeAdminUser({ ...RAW, status: "banned" })?.status).toBe("unknown");
  });

  it("문자열이 아닌 값은 렌더하지 않는다([object Object] 방지)", () => {
    const clean = sanitizeAdminUser({ ...RAW, status_reason: { evil: 1 }, created_at: 12345 });
    expect(clean?.status_reason).toBeNull();
    expect(clean?.created_at).toBeNull();
  });

  it("is_admin 은 truthy 가 아니라 정확히 true 일 때만 관리자다", () => {
    expect(sanitizeAdminUser({ ...RAW, is_admin: "yes" })?.is_admin).toBe(false);
    expect(sanitizeAdminUser({ ...RAW, is_admin: true })?.is_admin).toBe(true);
  });
});

describe("목록 반영", () => {
  const list = [user({ id: 1 }), user({ id: 2, email: "b@example.com" })];

  it("대기 목록에서 승인하면 그 자리에서 사라진다", () => {
    const next = applyUserUpdate(list, user({ id: 1, status: "approved" }), "pending");
    expect(next.map((u) => u.id)).toEqual([2]);
  });

  it("전체 목록에서는 사라지지 않고 상태만 바뀐다", () => {
    const next = applyUserUpdate(list, user({ id: 1, status: "rejected" }), "all");
    expect(next).toHaveLength(2);
    expect(next[0].status).toBe("rejected");
  });

  it("같은 필터에 남는 변경은 제자리에서 갱신된다", () => {
    const next = applyUserUpdate(list, user({ id: 2, email: "b2@example.com" }), "pending");
    expect(next).toHaveLength(2);
    expect(next[1].email).toBe("b2@example.com");
  });

  it("대기 건수는 pending 만 센다", () => {
    expect(pendingCount([user(), user({ id: 2, status: "approved" })])).toBe(1);
  });
});

describe("실패 문구", () => {
  it("409 LAST_ADMIN 은 왜 안 되는지 설명한다(뭉개지 않는다)", () => {
    const msg = adminActionErrorMessage(
      new ApiException(409, { code: "LAST_ADMIN", message: "마지막 관리자" }),
    );
    expect(msg).toContain("마지막 관리자");
    expect(msg).toContain("승인할 수 없");
  });

  it("404 는 권한 상실일 수도 있어 단정하지 않고 재조회로 안내한다", () => {
    const msg = adminActionErrorMessage(new ApiException(404, { code: "UNKNOWN", message: "" }));
    expect(msg).toContain("다시 불러옵니다");
    expect(msg).not.toContain("권한");
  });

  it("네트워크 오류는 서버 응답과 구분한다", () => {
    expect(adminActionErrorMessage(new Error("down"))).toContain("네트워크");
  });
});

describe("날짜", () => {
  it("ISO 시각을 날짜로 줄이고, 형식이 다르면 지어내지 않는다", () => {
    expect(formatDay("2026-07-26T04:14:36Z")).toBe("2026년 7월 26일");
    expect(formatDay(null)).toBe("—");
    expect(formatDay("어제")).toBe("어제");
  });
});
