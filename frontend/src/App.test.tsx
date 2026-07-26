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
import {
  ApiException,
  api,
  type AffordabilityResponse,
  type ComplexItem,
  type Preferences,
  type Profile,
} from "./api/client";
import { forgetCamera } from "./lib/mapCamera";
import { installKakaoStub, type KakaoStubHandle } from "./test/kakaoStub";

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
 * 지도 화면의 조작 — 사용자가 실사용 후 지적한 부분들.
 *  ① "내 조건을 지도에서 언제든지 설정할 수 있나" → 상시 진입점
 *  ② 목록에 위계가 없다 → 정렬. 단, **모르는 값을 0 으로 줄 세우지 않는다**.
 */
describe("지도 화면", () => {
  function complex(over: Partial<ComplexItem> & { id: number; name: string }): ComplexItem {
    return {
      point: [127, 37.5],
      households: 500,
      built_year: 2005,
      recent_price_krw: 1_000_000_000,
      price_as_of: "2026-06-30",
      price_confidence: "estimated",
      active_listings: 1,
      over_budget: false,
      ...over,
    };
  }

  let kakao: KakaoStubHandle | null = null;

  afterEach(() => {
    kakao?.restore();
    kakao = null;
    forgetCamera(); // 테스트끼리 지도 위치를 물려주지 않는다
  });

  function mountWith(items: ComplexItem[]) {
    // 목록은 지도가 만든다(idle → bbox → 조회). SDK 가 없으면 목록도 없다.
    kakao = installKakaoStub();
    vi.spyOn(api, "getProfile").mockResolvedValue(PROFILE);
    vi.spyOn(api, "getPreferences").mockResolvedValue(PREFS);
    vi.spyOn(api, "affordability").mockResolvedValue(AFFORD);
    vi.spyOn(api, "mapComplexes").mockResolvedValue({ level: "complex", items, note: "" });
    return userEvent.setup();
  }

  const names = () =>
    screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);

  it("지도를 보는 중에도 조건 진입점이 항상 있다(요청: 지도에서 언제든 설정)", async () => {
    const user = mountWith([]);
    render(<Authenticated />);

    const edit = await screen.findByRole("button", { name: "조건 수정" });
    await user.click(edit);

    expect(await screen.findByRole("heading", { name: "내 조건", level: 1 })).toBeTruthy();
  });

  it("정렬을 바꾸면 목록 순서가 바뀐다 — 범위는 '지금 보이는 지도'라고 밝힌다", async () => {
    const user = mountWith([
      complex({ id: 1, name: "가나아파트", recent_price_krw: 1_400_000_000 }),
      complex({ id: 2, name: "다라아파트", recent_price_krw: 700_000_000 }),
    ]);
    render(<Authenticated />);

    await screen.findByText("가나아파트");
    expect(names()).toEqual(["가나아파트", "다라아파트"]); // 서버 순서 그대로
    expect(screen.getByText("지금 보이는 지도 범위 기준")).toBeTruthy();

    await user.selectOptions(screen.getByLabelText("목록 정렬"), "price_asc");

    expect(names()).toEqual(["다라아파트", "가나아파트"]);
  });

  it("시세를 모르는 단지는 '가격 낮은 순'에서도 맨 뒤다(0 원이 아니다)", async () => {
    const user = mountWith([
      complex({ id: 1, name: "가나아파트", recent_price_krw: 1_400_000_000 }),
      complex({
        id: 2,
        name: "미상아파트",
        recent_price_krw: null,
        price_confidence: "unknown",
      }),
      complex({ id: 3, name: "다라아파트", recent_price_krw: 700_000_000 }),
    ]);
    render(<Authenticated />);
    await screen.findByText("미상아파트");

    await user.selectOptions(screen.getByLabelText("목록 정렬"), "price_asc");

    expect(names()).toEqual(["다라아파트", "가나아파트", "미상아파트"]);
    // 값을 지어내지 않는다 — 목록에도 '데이터 없음'으로 남는다
    expect(screen.getByText("데이터 없음")).toBeTruthy();
  });

  it("보여줄 단지가 없으면 정렬 컨트롤도 없다(누를 게 없는 조작을 두지 않는다)", async () => {
    mountWith([]);
    render(<Authenticated />);

    await screen.findByRole("button", { name: "조건 수정" });
    expect(screen.queryByLabelText("목록 정렬")).toBeNull();
  });

  /**
   * 분석 지역 — 예전엔 `region_codes` 를 **한 번도 보내지 않아** 늘 수도권 전체(단지 1.6만)에서
   * 상한 50개만 보고 추천했다. 사용자가 평촌·분당을 지정할 방법이 없었던 원인이다.
   */
  it("고른 시군구가 실제로 추천 요청에 실려 나간다", async () => {
    const user = mountWith([]);
    const create = vi
      .spyOn(api, "createRecommendation")
      .mockResolvedValue({ job_id: "rec_1", status: "queued" });
    vi.spyOn(api, "recommendation").mockResolvedValue({
      job_id: "rec_1",
      status: "done",
      items: [],
    });
    render(<Authenticated />);

    await user.click(await screen.findByRole("tab", { name: "AI 추천" }));
    await user.click(screen.getByRole("button", { name: "지역 선택" }));
    await user.click(screen.getByRole("checkbox", { name: /성남시 분당구/ }));
    await user.click(screen.getByRole("button", { name: "AI 추천 실행" }));

    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0][0]).toMatchObject({ region_codes: ["41135"] });
  });

  it("지역을 안 고르면 빈 배열을 보내고, 전체에서 찾는다는 사실을 화면에 적는다", async () => {
    const user = mountWith([]);
    const create = vi
      .spyOn(api, "createRecommendation")
      .mockResolvedValue({ job_id: "rec_1", status: "queued" });
    vi.spyOn(api, "recommendation").mockResolvedValue({
      job_id: "rec_1",
      status: "done",
      items: [],
    });
    render(<Authenticated />);

    await user.click(await screen.findByRole("tab", { name: "AI 추천" }));
    expect(screen.getByText(/수도권 전체에서 찾습니다/)).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "AI 추천 실행" }));

    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0][0].region_codes).toEqual([]);
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
