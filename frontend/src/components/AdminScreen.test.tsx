// @vitest-environment jsdom
/**
 * 관리자 화면 테스트 — **실제 훅(useAdminUsers)을 그대로 태운다.**
 *
 * 훅을 가짜로 바꾸면 이 화면에서 정작 중요한 것(404 를 조용히 숨기는가,
 * 승인 결과가 목록에 반영되는가)이 검증되지 않는다. api 만 스파이로 대체한다.
 */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiException, api } from "../api/client";
import { useAdminUsers } from "../hooks/useAdminUsers";
import { AdminScreen } from "./AdminScreen";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** App 이 하는 판단(관리자일 때만 화면이 존재한다)을 그대로 흉내 낸 껍데기. */
function Harness() {
  const admin = useAdminUsers(true);
  if (admin.availability !== "available") return <p>관리 화면 없음</p>;
  return <AdminScreen admin={admin} onClose={() => {}} />;
}

const PENDING_USER = {
  id: 12,
  email: "wait@example.com",
  status: "pending",
  is_admin: false,
  created_at: "2026-07-26T04:14:36Z",
  status_changed_at: null,
  status_changed_by: null,
  status_reason: null,
};

function listOnce(items: unknown[], activeAdmins = 2) {
  return vi
    .spyOn(api, "adminListUsers")
    .mockResolvedValue({ items, active_admins: activeAdmins });
}

describe("존재 자체를 숨긴다", () => {
  it("404(관리자 아님)면 오류가 아니라 '화면 없음'으로 조용히 끝난다", async () => {
    vi.spyOn(api, "adminListUsers").mockRejectedValue(
      new ApiException(404, { code: "UNKNOWN", message: "요청이 실패했습니다 (404)" }),
    );

    render(<Harness />);

    expect(await screen.findByText("관리 화면 없음")).toBeTruthy();
    // "권한이 없습니다" 를 띄우면 서버가 404 로 숨긴 것을 화면이 도로 알려준다
    expect(screen.queryByText(/권한/)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("대기 목록", () => {
  it("대기 사용자를 이메일·상태·신청일과 함께 보여준다", async () => {
    listOnce([PENDING_USER]);

    render(<Harness />);

    expect(await screen.findByText("wait@example.com")).toBeTruthy();
    // 필터 버튼에도 같은 글자가 있으므로 목록 안에서만 찾는다
    const list = within(screen.getByRole("list"));
    expect(list.getByText("승인 대기")).toBeTruthy();
    expect(list.getByText(/2026년 7월 26일/)).toBeTruthy();
    expect(api.adminListUsers).toHaveBeenCalledWith({ status: "pending", limit: 200 });
  });

  it("자산·소득이 섞여 와도 화면에 렌더하지 않고, 그 사실을 알린다", async () => {
    listOnce([{ ...PENDING_USER, cash_krw: 300_000_000, income_krw: 90_000_000 }]);

    const { container } = render(<Harness />);
    await screen.findByText("wait@example.com");

    const text = container.textContent ?? "";
    expect(text).not.toContain("300000000");
    expect(text).not.toContain("3억");
    expect(text).not.toContain("90000000");
    expect(screen.getByRole("alert").textContent).toContain("표시하면 안 되는 항목");
  });

  it("대기자가 없으면 빈 상태를 말한다", async () => {
    listOnce([]);
    render(<Harness />);
    expect(await screen.findByText("승인 대기 중인 신청이 없습니다.")).toBeTruthy();
  });
});

describe("승인 · 거부", () => {
  it("승인하면 목록에서 빠지고 결과를 알린다", async () => {
    listOnce([PENDING_USER, { ...PENDING_USER, id: 13, email: "other@example.com" }]);
    const approve = vi
      .spyOn(api, "adminApproveUser")
      .mockResolvedValue({ ...PENDING_USER, status: "approved" });

    const user = userEvent.setup();
    render(<Harness />);
    await user.click(await screen.findByRole("button", { name: "wait@example.com 승인" }));

    expect(approve).toHaveBeenCalledWith(12);
    await waitFor(() => expect(screen.queryByText("wait@example.com")).toBeNull());
    expect(screen.getByRole("status").textContent).toContain("승인했습니다");
    // 다른 대기자는 그대로 남는다(목록 전체를 날리지 않는다)
    expect(screen.getByText("other@example.com")).toBeTruthy();
  });

  it("거부는 사유를 입력받아 보내고, 목록에서 뺀다", async () => {
    listOnce([PENDING_USER]);
    const reject = vi
      .spyOn(api, "adminRejectUser")
      .mockResolvedValue({ ...PENDING_USER, status: "rejected", status_reason: "본인 확인 불가" });

    const user = userEvent.setup();
    render(<Harness />);
    await user.click(await screen.findByRole("button", { name: "wait@example.com 거부" }));

    await user.type(screen.getByLabelText(/사유/), "본인 확인 불가");
    await user.click(screen.getByRole("button", { name: "wait@example.com 거부 확정" }));

    expect(reject).toHaveBeenCalledWith(12, "본인 확인 불가");
    await waitFor(() => expect(screen.queryByText("wait@example.com")).toBeNull());
  });

  it("사유를 비우면 null 로 보낸다(빈 문자열을 감사기록에 남기지 않는다)", async () => {
    listOnce([PENDING_USER]);
    const reject = vi
      .spyOn(api, "adminRejectUser")
      .mockResolvedValue({ ...PENDING_USER, status: "rejected" });

    const user = userEvent.setup();
    render(<Harness />);
    await user.click(await screen.findByRole("button", { name: "wait@example.com 거부" }));
    await user.click(screen.getByRole("button", { name: "wait@example.com 거부 확정" }));

    expect(reject).toHaveBeenCalledWith(12, null);
  });

  it("이미 승인된 관리자에게는 '승인 회수'로 보인다(같은 API, 다른 의미)", async () => {
    listOnce([{ ...PENDING_USER, status: "approved", is_admin: true }]);

    render(<Harness />);

    expect(await screen.findByRole("button", { name: "wait@example.com 승인 회수" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "wait@example.com 승인" })).toBeNull();
    expect(screen.getByText("관리자")).toBeTruthy();
  });

  it("409 LAST_ADMIN 은 왜 막혔는지 설명한다", async () => {
    listOnce([{ ...PENDING_USER, status: "approved", is_admin: true }], 1);
    vi.spyOn(api, "adminRejectUser").mockRejectedValue(
      new ApiException(409, {
        code: "LAST_ADMIN",
        message: "마지막 관리자는 거부할 수 없습니다",
      }),
    );

    const user = userEvent.setup();
    render(<Harness />);
    await user.click(await screen.findByRole("button", { name: "wait@example.com 승인 회수" }));
    await user.click(screen.getByRole("button", { name: "wait@example.com 승인 회수 확정" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("마지막 관리자");
    expect(alert.textContent).toContain("서버에서 직접 복구");
    // 관리자가 1명뿐이라는 사실을 누르기 전에도 알려준다
    expect(screen.getByText(/승인된 관리자/).textContent).toContain("마지막 관리자");
  });

  it("처리 중 권한이 사라지면(404) 화면이 스스로 닫힌다", async () => {
    const list = vi
      .spyOn(api, "adminListUsers")
      .mockResolvedValueOnce({ items: [PENDING_USER], active_admins: 2 })
      .mockRejectedValueOnce(new ApiException(404, { code: "UNKNOWN", message: "" }));
    vi.spyOn(api, "adminApproveUser").mockRejectedValue(
      new ApiException(404, { code: "UNKNOWN", message: "" }),
    );

    const user = userEvent.setup();
    render(<Harness />);
    await user.click(await screen.findByRole("button", { name: "wait@example.com 승인" }));

    expect(await screen.findByText("관리 화면 없음")).toBeTruthy();
    expect(list).toHaveBeenCalledTimes(2); // 실패 후 서버에 다시 물어봤다
  });
});
