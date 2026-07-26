// @vitest-environment jsdom
/**
 * 핵심 루프의 **입구** 테스트.
 *
 * 자산이 없으면 예산이 없고, 예산이 없으면 "내 조건에 맞는 매물"이 성립하지 않는다.
 * 그래서 프로필이 비어 있을 때 지도를 먼저 보여주면 그건 제품이 아니라 지도 뷰어다.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Authenticated } from "./App";
import { ApiException, api, type AffordabilityResponse, type Preferences, type Profile } from "./api/client";

const PROFILE: Profile = {
  cash_krw: 300_000_000,
  income_krw: 90_000_000,
  existing_loan_krw: 0,
  owned_houses: 0,
  household_size: 3,
};

const PREFS: Preferences = { prefer: { built_after: 2010 }, avoid: {}, weights: {} };

const AFFORD: AffordabilityResponse = {
  max_purchase_krw: 850_000_000,
  breakdown: {
    own_cash_krw: 300_000_000,
    max_loan_krw: 550_000_000,
    binding_constraint: "DSR",
  },
  acquisition_cost_krw: { tax: 9_350_000, brokerage: 5_100_000, registration: 1_000_000, total: 15_450_000 },
  assumptions: ["기존 대출 상환액 미입력 — 0으로 계산했습니다"],
  evidence: [{ claim: "취득세율 1.1%", source: "지방세법 §11", as_of: "2026-07-24" }],
  warnings: [],
  disclaimer: "실제 한도는 금융기관 심사에 따라 달라집니다.",
};

/** 관리자가 아닌 사용자에게 서버가 주는 응답 — 403 이 아니라 **404** 다(api-spec §6.2). */
const NOT_ADMIN = new ApiException(404, { code: "UNKNOWN", message: "요청이 실패했습니다 (404)" });

beforeEach(() => {
  // 기본값은 "관리자 아님". 관리자 케이스만 테스트가 따로 덮어쓴다.
  vi.spyOn(api, "adminListUsers").mockRejectedValue(NOT_ADMIN);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("프로필이 없을 때", () => {
  it("지도가 아니라 내 조건 화면으로 보낸다", async () => {
    vi.spyOn(api, "getProfile").mockRejectedValue(
      new ApiException(404, { code: "NOT_FOUND", message: "자산 정보가 아직 없습니다" }),
    );
    vi.spyOn(api, "getPreferences").mockResolvedValue(PREFS);
    const affordSpy = vi.spyOn(api, "affordability").mockResolvedValue(AFFORD);

    render(<Authenticated />);

    expect(await screen.findByRole("heading", { name: "내 조건", level: 1 })).toBeTruthy();
    expect(screen.getByRole("button", { name: "저장하고 시작" })).toBeTruthy();
    // 되돌아갈 지도가 없으므로 취소도 없다
    expect(screen.queryByRole("button", { name: "취소" })).toBeNull();
    // 예산 계산은 자산 없이는 의미가 없다 — 부르지 않는다
    expect(affordSpy).not.toHaveBeenCalled();
  });

  it("저장하면 지도 화면으로 넘어간다", async () => {
    vi.spyOn(api, "getProfile").mockRejectedValue(
      new ApiException(404, { code: "NOT_FOUND", message: "없음" }),
    );
    vi.spyOn(api, "getPreferences").mockResolvedValue(PREFS);
    vi.spyOn(api, "affordability").mockResolvedValue(AFFORD);
    const putProfile = vi.spyOn(api, "putProfile").mockResolvedValue(PROFILE);
    const putPrefs = vi.spyOn(api, "putPreferences").mockResolvedValue(PREFS);
    vi.spyOn(api, "mapComplexes").mockResolvedValue({ level: "complex", items: [], note: "" });

    const user = userEvent.setup();
    render(<Authenticated />);
    await screen.findByRole("heading", { name: "내 조건", level: 1 });

    // 화면은 만원, 서버는 원 — 3억을 넣으면 30000(만원)을 친다
    await user.type(screen.getByLabelText("보유 현금"), "30000");
    await user.type(screen.getByLabelText("연 소득 (세전)"), "9000");
    await user.click(screen.getByRole("button", { name: "저장하고 시작" }));

    await waitFor(() => expect(putProfile).toHaveBeenCalled());
    expect(putProfile.mock.calls[0][0]).toMatchObject({
      cash_krw: 300_000_000, // 만원 → 원 변환이 여기서 깨지면 한도가 1만분의 1이 된다
      income_krw: 90_000_000,
      household_size: 1,
    });
    expect(putPrefs).toHaveBeenCalled();

    expect(await screen.findByRole("tab", { name: "AI 추천" })).toBeTruthy();
  });
});

describe("프로필이 있을 때", () => {
  it("지도 화면을 보여주고, 예산을 계산해 필터 칩으로 노출한다", async () => {
    vi.spyOn(api, "getProfile").mockResolvedValue(PROFILE);
    vi.spyOn(api, "getPreferences").mockResolvedValue(PREFS);
    vi.spyOn(api, "affordability").mockResolvedValue(AFFORD);
    vi.spyOn(api, "mapComplexes").mockResolvedValue({ level: "complex", items: [], note: "" });

    render(<Authenticated />);

    // 조용히 걸린 필터는 "왜 안 보이지?"가 된다 → 무엇이 걸렸는지 화면에 있어야 한다
    expect(await screen.findByRole("button", { name: "내 예산 8.50억 기준" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "2010년 이후 준공" })).toBeTruthy();
  });

  it("예산 칩을 끄면 aria-pressed 가 꺼진다(끄고 켤 수 있다)", async () => {
    vi.spyOn(api, "getProfile").mockResolvedValue(PROFILE);
    vi.spyOn(api, "getPreferences").mockResolvedValue(PREFS);
    vi.spyOn(api, "affordability").mockResolvedValue(AFFORD);
    vi.spyOn(api, "mapComplexes").mockResolvedValue({ level: "complex", items: [], note: "" });

    const user = userEvent.setup();
    render(<Authenticated />);
    const chip = await screen.findByRole("button", { name: "내 예산 8.50억 기준" });
    expect(chip.getAttribute("aria-pressed")).toBe("true");

    await user.click(chip);
    expect(chip.getAttribute("aria-pressed")).toBe("false");
  });

  it("관리자 진입점은 없다 — 일반 사용자에게는 존재 자체를 알리지 않는다", async () => {
    vi.spyOn(api, "getProfile").mockResolvedValue(PROFILE);
    vi.spyOn(api, "getPreferences").mockResolvedValue(PREFS);
    vi.spyOn(api, "affordability").mockResolvedValue(AFFORD);
    vi.spyOn(api, "mapComplexes").mockResolvedValue({ level: "complex", items: [], note: "" });

    const { container } = render(<Authenticated />);
    await screen.findByRole("button", { name: "로그아웃" });

    // 404 를 받고 나서도(응답이 온 뒤에도) 진입점이 생기지 않아야 한다
    await waitFor(() => expect(api.adminListUsers).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /가입 승인/ })).toBeNull();
    expect(container.textContent).not.toContain("가입 승인");
    // 404 를 "권한 없음" 오류로 번역하지도 않는다
    expect(screen.queryByText(/권한/)).toBeNull();
  });

  it("자금 탭에서 한도를 묶은 제약과 근거 출처를 함께 보여준다", async () => {
    vi.spyOn(api, "getProfile").mockResolvedValue(PROFILE);
    vi.spyOn(api, "getPreferences").mockResolvedValue(PREFS);
    vi.spyOn(api, "affordability").mockResolvedValue(AFFORD);
    vi.spyOn(api, "mapComplexes").mockResolvedValue({ level: "complex", items: [], note: "" });

    const user = userEvent.setup();
    render(<Authenticated />);
    await user.click(await screen.findByRole("tab", { name: "내 자금" }));

    expect(screen.getByText("8억 5,000만")).toBeTruthy();
    expect(screen.getByText(/한도를 결정한 건 총부채원리금상환비율\(DSR\)/)).toBeTruthy();
    // 근거는 출처·기준일과 함께 (G2)
    expect(screen.getByText("취득세율 1.1%")).toBeTruthy();
    expect(screen.getByText(/지방세법 §11/)).toBeTruthy();
  });
});

/**
 * 관리자 여부는 **서버만 안다**(토큰에 권한 클레임이 없다).
 * 그래서 진입점은 `/admin/users` 가 200 을 준 경우에만 생긴다.
 */
describe("관리자일 때", () => {
  function asAdmin(pending = 1) {
    vi.spyOn(api, "adminListUsers").mockResolvedValue({
      items: Array.from({ length: pending }, (_, i) => ({
        id: 100 + i,
        email: `wait${i}@example.com`,
        status: "pending",
        is_admin: false,
        created_at: "2026-07-26T04:14:36Z",
        status_changed_at: null,
        status_reason: null,
      })),
      active_admins: 2,
    });
  }

  it("지도 화면 하단에 대기 건수와 함께 진입점이 생긴다", async () => {
    asAdmin(2);
    vi.spyOn(api, "getProfile").mockResolvedValue(PROFILE);
    vi.spyOn(api, "getPreferences").mockResolvedValue(PREFS);
    vi.spyOn(api, "affordability").mockResolvedValue(AFFORD);
    vi.spyOn(api, "mapComplexes").mockResolvedValue({ level: "complex", items: [], note: "" });

    render(<Authenticated />);

    const entry = await screen.findByRole("button", { name: /가입 승인/ });
    expect(entry.textContent).toContain("2");
  });

  it("자산을 아직 안 넣은 관리자도 승인 화면에 들어갈 수 있다", async () => {
    asAdmin(1);
    vi.spyOn(api, "getProfile").mockRejectedValue(
      new ApiException(404, { code: "NOT_FOUND", message: "없음" }),
    );
    vi.spyOn(api, "getPreferences").mockResolvedValue(PREFS);

    const user = userEvent.setup();
    render(<Authenticated />);

    // 최초 입력 화면(조건)에 있으면서도 승인 화면으로 갈 수 있어야 한다
    await screen.findByRole("heading", { name: "내 조건", level: 1 });
    await user.click(await screen.findByRole("button", { name: /가입 승인/ }));

    expect(await screen.findByRole("heading", { name: "가입 승인", level: 1 })).toBeTruthy();
    expect(screen.getByText("wait0@example.com")).toBeTruthy();
  });
});
