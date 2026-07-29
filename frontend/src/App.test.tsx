// @vitest-environment jsdom
/**
 * 핵심 루프의 **입구** 테스트.
 *
 * 자산이 없으면 예산이 없고, 예산이 없으면 "내 조건에 맞는 매물"이 성립하지 않는다.
 * 그래서 프로필이 비어 있을 때 지도를 먼저 보여주면 그건 제품이 아니라 지도 뷰어다.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Authenticated } from "./App";
import {
  ApiException,
  api,
  type AffordabilityResponse,
  type ComplexItem,
  type MapResponse,
  type Preferences,
  type Profile,
  type RecommendationItem,
} from "./api/client";
import { forgetCamera } from "./lib/mapCamera";
import { emptyUserListingList } from "./test/fixtures";
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

// jsdom 은 `scrollIntoView` 를 구현하지 않는다. 목록↔지도 동기화(ComplexCard)가 쓰는
// 브라우저 표준 API 라 컴포넌트에 가드를 넣을 일이 아니고, 테스트 환경에서 채워 준다.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {};
}

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
    expect(await screen.findByRole("button", { name: "내 예산 8.50억 초과 표시" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "2010년 이후 준공" })).toBeTruthy();
  });

  it("예산 칩을 끄면 aria-pressed 가 꺼진다(끄고 켤 수 있다)", async () => {
    vi.spyOn(api, "getProfile").mockResolvedValue(PROFILE);
    vi.spyOn(api, "getPreferences").mockResolvedValue(PREFS);
    vi.spyOn(api, "affordability").mockResolvedValue(AFFORD);
    vi.spyOn(api, "mapComplexes").mockResolvedValue({ level: "complex", items: [], note: "" });

    const user = userEvent.setup();
    render(<Authenticated />);
    const chip = await screen.findByRole("button", { name: "내 예산 8.50억 초과 표시" });
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
    await user.click(await screen.findByRole("button", { name: /내 자금/ }));

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

  /**
   * "이 주변에서 찾기" — 사용자가 지도로 평촌을 보고 있으면 그 자리로 찾을 수 있어야 한다.
   *
   * 여기서 검증의 기준을 **"지도가 조회에 쓴 bbox 와 같은 값"** 으로 잡은 이유:
   * 테스트가 기대값을 스스로 계산하면(±0.05 같은 스텁 규칙을 베끼면) 그건 자기충족 테스트다.
   * 지도 조회(`/map/complexes`)와 추천 요청(`/recommendations`)이 **같은 범위**를 들고 나가는지가
   * 진짜 계약이므로, 서로 독립된 두 경로의 값을 맞대어 본다.
   */
  describe("이 주변에서 찾기", () => {
    /** 지도가 방금 조회에 쓴 bbox — 화면이 새로 계산하지 않았음을 이 값으로 확인한다. */
    const mapBbox = () => vi.mocked(api.mapComplexes).mock.calls.at(-1)![0].bbox;

    function stubJob() {
      const create = vi
        .spyOn(api, "createRecommendation")
        .mockResolvedValue({ job_id: "rec_1", status: "queued" });
      vi.spyOn(api, "recommendation").mockResolvedValue({
        job_id: "rec_1",
        status: "done",
        items: [],
        notes: ["좌표가 없는 단지 5.5%는 지도 범위 검색에서 빠졌습니다."],
      });
      return create;
    }

    async function openAdvice(user: ReturnType<typeof userEvent.setup>) {
      await user.click(await screen.findByRole("tab", { name: "AI 추천" }));
    }

    it("지금 지도 범위를 그대로 추천 요청에 싣는다", async () => {
      const user = mountWith([]);
      const create = stubJob();
      render(<Authenticated />);
      await openAdvice(user);

      await user.click(await screen.findByRole("button", { name: "이 주변에서 찾기" }));
      await user.click(screen.getByRole("button", { name: "AI 추천 실행" }));

      await waitFor(() => expect(create).toHaveBeenCalled());
      const sent = create.mock.calls[0][0];
      expect(sent.bbox).toBe(mapBbox()); // 지도가 보는 범위와 **같은 값**
      expect(sent.bbox!.split(",")).toHaveLength(4); // minLon,minLat,maxLon,maxLat
    });

    it("시군구와 함께 쓰면 둘 다 나간다(서버가 교집합으로 좁힌다)", async () => {
      const user = mountWith([]);
      const create = stubJob();
      render(<Authenticated />);
      await openAdvice(user);

      await user.click(await screen.findByRole("button", { name: "이 주변에서 찾기" }));
      await user.click(screen.getByRole("button", { name: "지역 선택" }));
      await user.click(screen.getByRole("checkbox", { name: /성남시 분당구/ }));
      // 교집합이라는 사실이 화면에도 있어야 한다(칩만 둘이면 합집합으로 읽힌다)
      expect(screen.getByText(/두 조건을 모두 만족하는 단지만 찾습니다/)).toBeTruthy();

      await user.click(screen.getByRole("button", { name: "AI 추천 실행" }));

      await waitFor(() => expect(create).toHaveBeenCalled());
      expect(create.mock.calls[0][0]).toMatchObject({
        region_codes: ["41135"],
        bbox: mapBbox(),
      });
    });

    it("칩을 해제하면 bbox 가 요청에서 빠진다", async () => {
      const user = mountWith([]);
      const create = stubJob();
      render(<Authenticated />);
      await openAdvice(user);

      await user.click(await screen.findByRole("button", { name: "이 주변에서 찾기" }));
      await user.click(screen.getByRole("button", { name: /이 주변 · 지금 지도 범위/ }));
      await user.click(screen.getByRole("button", { name: "AI 추천 실행" }));

      await waitFor(() => expect(create).toHaveBeenCalled());
      const sent = create.mock.calls[0][0];
      expect("bbox" in sent).toBe(false); // null·빈 문자열이 아니라 **키 자체가 없다**
    });

    it("지도가 아직 뜨지 않았으면 비활성 + 이유를 보인다(조용히 죽이지 않는다)", async () => {
      // 카카오 SDK 스텁을 심지 않는다 = 지도가 뜨지 않은 상태(키 없음·로드 실패)
      vi.spyOn(api, "getProfile").mockResolvedValue(PROFILE);
      vi.spyOn(api, "getPreferences").mockResolvedValue(PREFS);
      vi.spyOn(api, "affordability").mockResolvedValue(AFFORD);
      vi.spyOn(api, "mapComplexes").mockResolvedValue({ level: "complex", items: [], note: "" });
      const user = userEvent.setup();
      render(<Authenticated />);
      await openAdvice(user);

      const btn = screen.getByRole("button", { name: /이 주변에서 찾기/ });
      expect((btn as HTMLButtonElement).disabled).toBe(true);
      expect(screen.getByText(/지도가 아직 준비되지 않았습니다/)).toBeTruthy();
    });

    /**
     * 낡은 범위 — 캡처 시점을 "누른 순간"으로 고정했으므로, 지도를 옮겨도 **잡아 둔 범위**로
     * 돌아야 한다. 대신 낡았다는 사실을 화면이 말하고 다시 잡을 길을 준다.
     */
    it("지도를 옮겨도 잡아 둔 범위로 돌고, 낡았다는 사실을 화면이 말한다", async () => {
      const user = mountWith([]);
      const create = stubJob();
      render(<Authenticated />);
      await openAdvice(user);

      await user.click(await screen.findByRole("button", { name: "이 주변에서 찾기" }));
      const captured = mapBbox();

      // 지도를 끌어 다른 동네로 옮긴다
      act(() => kakao!.moveTo([127.2, 37.6]));
      await waitFor(() => expect(mapBbox()).not.toBe(captured));

      expect(screen.getByText(/지도를 옮겼습니다/)).toBeTruthy();
      await user.click(screen.getByRole("button", { name: "AI 추천 실행" }));

      await waitFor(() => expect(create).toHaveBeenCalled());
      // 실행 시점의 지도가 아니라 **누른 순간의 범위**가 나간다
      expect(create.mock.calls[0][0].bbox).toBe(captured);
      expect(create.mock.calls[0][0].bbox).not.toBe(mapBbox());
    });

    it("'지금 지도로 다시 잡기'를 누르면 새 범위로 갱신된다", async () => {
      const user = mountWith([]);
      const create = stubJob();
      render(<Authenticated />);
      await openAdvice(user);

      await user.click(await screen.findByRole("button", { name: "이 주변에서 찾기" }));
      const captured = mapBbox();

      act(() => kakao!.moveTo([127.2, 37.6]));
      await waitFor(() => expect(mapBbox()).not.toBe(captured));

      await user.click(screen.getByRole("button", { name: "지금 지도로 다시 잡기" }));
      expect(screen.queryByText(/지도를 옮겼습니다/)).toBeNull();

      await user.click(screen.getByRole("button", { name: "AI 추천 실행" }));
      await waitFor(() => expect(create).toHaveBeenCalled());
      expect(create.mock.calls[0][0].bbox).toBe(mapBbox());
      expect(create.mock.calls[0][0].bbox).not.toBe(captured);
    });

    it("결과가 나온 뒤 지도를 옮겨도 '어느 범위로 돌았는지'가 남는다", async () => {
      const user = mountWith([]);
      stubJob();
      render(<Authenticated />);
      await openAdvice(user);

      await user.click(await screen.findByRole("button", { name: "이 주변에서 찾기" }));
      await user.click(screen.getByRole("button", { name: "AI 추천 실행" }));
      const scope = await screen.findByText(/이 결과를 찾은 범위/);
      expect(scope.textContent).toMatch(/이 주변\(약 [\d.]+ × [\d.]+km\)/);

      // 결과를 본 뒤 지도를 옮기면 화면과 결과가 어긋난다 — 그 사실을 말해야 한다
      act(() => kakao!.moveTo([127.4, 37.7]));
      expect(screen.getByText(/지금 보고 있는 지도와 다른 범위입니다/)).toBeTruthy();
      // 범위 표기는 사라지지 않는다(칩을 지워도 결과의 출처는 남는다)
      expect(screen.getByText(/이 결과를 찾은 범위/)).toBeTruthy();
    });

    it("좌표 없는 단지가 빠진다는 서버 notes 를 결과에 그대로 보여준다", async () => {
      const user = mountWith([]);
      stubJob();
      render(<Authenticated />);
      await openAdvice(user);

      await user.click(await screen.findByRole("button", { name: "이 주변에서 찾기" }));
      await user.click(screen.getByRole("button", { name: "AI 추천 실행" }));

      expect(
        await screen.findByText(/좌표가 없는 단지 5.5%는 지도 범위 검색에서 빠졌습니다/),
      ).toBeTruthy();
    });
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
 * 희망 매매가 — **저장만 되고 아무 데도 안 쓰이는 값이 되면 안 된다**(PREF-1).
 *
 * 이 프로젝트는 같은 실패를 이미 한 번 했다: `weights` 슬라이더가 DB 에 저장만 되고
 * 점수 계산에 전혀 쓰이지 않았다(api-spec §5.3). 사용자는 슬라이더가 있으니 반영된다고
 * 믿었고, 끝에서 끝까지 옮겨도 결과가 한 건도 바뀌지 않았다.
 * 아래 테스트는 희망가가 **실제로 세 요청에 실려 나가는지**를 고정한다.
 */
describe("희망 매매가가 실제로 요청에 실린다", () => {
  const TARGET = 900_000_000; // 9억 — 한도(8.5억)를 넘긴 값

  const PREFS_WITH_TARGET: Preferences = {
    prefer: { built_after: 2010, target_price_krw: TARGET },
    avoid: {},
    weights: {},
  };

  function mount(prefs: Preferences = PREFS_WITH_TARGET) {
    installKakaoStub();
    vi.spyOn(api, "getProfile").mockResolvedValue(PROFILE);
    vi.spyOn(api, "getPreferences").mockResolvedValue(prefs);
    vi.spyOn(api, "affordability").mockResolvedValue(AFFORD);
    vi.spyOn(api, "mapComplexes").mockResolvedValue({ level: "complex", items: [], note: "" });
    return userEvent.setup();
  }

  afterEach(() => forgetCamera());

  it("`/affordability` 에 target_price_krw 로 나간다", async () => {
    mount();
    render(<Authenticated />);

    await waitFor(() =>
      expect(vi.mocked(api.affordability).mock.calls.at(-1)?.[0]).toMatchObject({
        purpose: "live",
        target_price_krw: TARGET,
      }),
    );
  });

  it("AI 추천에 budget_override_krw 로 나간다", async () => {
    const user = mount();
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
    await user.click(screen.getByRole("button", { name: "AI 추천 실행" }));

    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0][0].budget_override_krw).toBe(TARGET);
  });

  /**
   * 지도도 같은 예산을 쓴다. 다만 **금액을 URL 로 보내지 않는다**(SR32-1) —
   * 플래그만 보내고 상한은 서버가 저장된 희망가로 만든다. 여기서 고정하는 것은
   * "지도 조회가 예산 조건을 달고 나갔다 + 화면이 그 예산을 희망가라고 말한다" 둘이다.
   * (URL 에 금액이 실제로 없는지는 `src/test/urlPrivacy.test.tsx` 가 실물 요청으로 본다.)
   */
  it("지도 조회도 예산 조건을 달고 나간다 — 금액이 아니라 플래그로", async () => {
    mount();
    render(<Authenticated />);

    await waitFor(() =>
      expect(vi.mocked(api.mapComplexes).mock.calls.at(-1)?.[0].budget).toBe("mine"),
    );
    // 화면이 말하는 예산은 한도(8.5억)가 아니라 내가 정한 9억이다
    expect(screen.getByRole("button", { name: "희망가 9.00억 초과 표시" })).toBeTruthy();

    // 그리고 그 금액은 **요청 어디에도 없다** — 서버가 저장된 값으로 만든다.
    const sent = JSON.stringify(vi.mocked(api.mapComplexes).mock.calls.at(-1)?.[0]);
    expect(sent).not.toContain(String(TARGET));
  });

  it("희망가가 없으면 예전대로 — 요청에서 키가 빠지고 한도가 예산이 된다", async () => {
    const user = mount(PREFS);
    const create = vi
      .spyOn(api, "createRecommendation")
      .mockResolvedValue({ job_id: "rec_1", status: "queued" });
    vi.spyOn(api, "recommendation").mockResolvedValue({
      job_id: "rec_1",
      status: "done",
      items: [],
    });
    render(<Authenticated />);

    await waitFor(() => expect(api.affordability).toHaveBeenCalled());
    // null 이나 0 이 아니라 **키 자체가 없다**(서버가 "0원 예산"으로 읽지 않게)
    expect("target_price_krw" in vi.mocked(api.affordability).mock.calls[0][0]!).toBe(false);
    expect(await screen.findByRole("button", { name: "내 예산 8.50억 초과 표시" })).toBeTruthy();

    await user.click(await screen.findByRole("tab", { name: "AI 추천" }));
    await user.click(screen.getByRole("button", { name: "AI 추천 실행" }));
    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0][0].budget_override_krw).toBeNull();
  });

  it("조건 화면에서 바꾼 값이 저장 후 곧바로 다음 요청에 반영된다", async () => {
    const user = mount(PREFS);
    vi.spyOn(api, "putProfile").mockResolvedValue(PROFILE);
    vi.spyOn(api, "putPreferences").mockImplementation(async (body) => body);
    render(<Authenticated />);

    await user.click(await screen.findByRole("button", { name: "조건 수정" }));
    const slider = await screen.findByRole("slider", { name: "희망 매매가" });
    fireEvent.change(slider, { target: { value: String(TARGET) } });
    await user.click(screen.getByRole("button", { name: "저장하고 다시 계산" }));

    // 저장된 선호에 실려 나가고 → 그 값으로 자금계획이 다시 계산된다
    await waitFor(() =>
      expect(vi.mocked(api.putPreferences).mock.calls[0][0].prefer.target_price_krw).toBe(TARGET),
    );
    await waitFor(
      () =>
        expect(vi.mocked(api.affordability).mock.calls.at(-1)?.[0]).toMatchObject({
          target_price_krw: TARGET,
        }),
      { timeout: 3000 },
    );
  });
});

/**
 * 단지 클릭 → 그 단지 가격으로 자금계획.
 * 그 가격은 `recent_price_krw`(**실거래 기반 추정**)이지 호가가 아니다 — 화면이 그렇게 말해야 한다.
 */
describe("단지를 고르면 그 단지 가격으로 계산한다", () => {
  const AFFORD_WITH_PLAN: AffordabilityResponse = {
    ...AFFORD,
    plan: {
      target_price_krw: 1_000_000_000,
      total_needed_krw: 1_035_000_000,
      cost_breakdown: { tax: 29_000_000, brokerage: 5_000_000, etc: 1_000_000 },
      own_cash_krw: 300_000_000,
      shortfall_krw: 735_000_000,
      required_loan_krw: 735_000_000,
      loan_feasible: false,
      loan_limit_krw: 550_000_000,
      over_limit_krw: 185_000_000,
      binding_constraint: "DSR",
      monthly_payment_krw: 3_508_000,
      total_interest_krw: 528_000_000,
      terms: { annual_rate_pct: 4.0, years: 30 },
    },
  };

  function complexItem(over: Partial<ComplexItem> & { id: number; name: string }): ComplexItem {
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

  function mount(items: ComplexItem[]) {
    installKakaoStub();
    vi.spyOn(api, "getProfile").mockResolvedValue(PROFILE);
    vi.spyOn(api, "getPreferences").mockResolvedValue(PREFS);
    vi.spyOn(api, "affordability").mockResolvedValue(AFFORD_WITH_PLAN);
    vi.spyOn(api, "mapComplexes").mockResolvedValue({ level: "complex", items, note: "" });
    return userEvent.setup();
  }

  afterEach(() => forgetCamera());

  /**
   * CR35-4 — **금액이 아니라 단지 id 를 보낸다.**
   *
   * 예전에는 지도의 `recent_price_krw`(최근 체결 1건)를 그대로 실어 보냈다. 추천 카드는
   * 같은 단지를 "창 중위를 기준월로 환산한 추정가"로 말하므로 두 화면이 다른 금액으로
   * 섰고, 실측 부족액 차이가 최대 3.19억이었다. 이제 서버가 **추천과 같은 함수**로 정한다.
   */
  it("고른 단지의 **id** 가 `/affordability` 로 나간다 — 금액은 화면이 정하지 않는다", async () => {
    const user = mount([complexItem({ id: 7, name: "가나아파트", price_area_m2: 84.97 })]);
    render(<Authenticated />);

    await user.click(await screen.findByText("가나아파트"));

    await waitFor(
      () =>
        expect(vi.mocked(api.affordability).mock.calls.at(-1)?.[0]).toMatchObject({
          complex_id: 7,
          // 기준가는 면적별 값이라 면적도 함께 — 지도에 보인 체결가와 같은 면적이다
          area_m2: 84.97,
        }),
      { timeout: 3000 },
    );
    // 지도 값을 몰래 실어 보내면 서버가 그걸 그대로 쓴다(client_supplied) — 그러면 안 된다
    expect(
      "target_price_krw" in (vi.mocked(api.affordability).mock.calls.at(-1)?.[0] ?? {}),
    ).toBe(false);
  });

  it("단지를 빠르게 훑어도 요청은 **마지막 하나만** 나간다(디바운스)", async () => {
    const user = mount([
      complexItem({ id: 1, name: "가나아파트", recent_price_krw: 900_000_000 }),
      complexItem({ id: 2, name: "다라아파트", recent_price_krw: 1_100_000_000 }),
    ]);
    render(<Authenticated />);
    await screen.findByText("가나아파트");
    const before = vi.mocked(api.affordability).mock.calls.length;

    await user.click(screen.getByText("가나아파트"));
    await user.click(screen.getByText("다라아파트"));

    await waitFor(
      () =>
        expect(vi.mocked(api.affordability).mock.calls.at(-1)?.[0]).toMatchObject({
          complex_id: 2,
        }),
      { timeout: 3000 },
    );
    // 클릭 2회에 요청 2회가 아니라 1회 — 중간 단지(#1)는 요청되지 않는다
    const sent = vi.mocked(api.affordability).mock.calls.slice(before);
    expect(sent).toHaveLength(1);
  });

  it("자금 탭에 단지명과 **추정 표기**가 함께 뜬다(호가로 읽히면 안 된다)", async () => {
    const user = mount([complexItem({ id: 7, name: "가나아파트" })]);
    render(<Authenticated />);

    await user.click(await screen.findByText("가나아파트"));
    await user.click(screen.getByRole("button", { name: /내 자금/ }));

    const plan = await screen.findByRole("region", { name: "자금계획" });
    expect(plan.textContent).toContain("가나아파트");
    // 배지를 **정확히** 찾는다 — 본문 어딘가에 "추정"이라는 글자가 있는 것으로는 부족하다
    // (그러면 아래 고지 문장 하나가 배지 누락을 가려 준다).
    expect(within(plan).getByText("추정").className).toContain("badge--estimated");
    expect(plan.textContent).toContain("최근 실거래 기준 추정가");
    expect(plan.textContent).toContain("지금 살 수 있는 호가가 아니라");
    // 한도를 넘어도 숫자와 사유가 함께 보인다
    expect(plan.textContent).toContain("한도 초과");
    expect(plan.textContent).toContain("총부채원리금상환비율(DSR)");
    expect(plan.textContent).toContain("350.8만원");
    expect(plan.textContent).toContain("금리 4% · 30년");
  });

  /**
   * 표본이 모자라면 서버는 **계획을 만들지 않고 사유를 준다**(`target_price.krw === null`).
   * 화면은 그 자리를 0 이나 다른 값으로 채우지 않고 사유를 그대로 보인다.
   */
  it("서버가 기준가를 못 만들면 계획을 지어내지 않고 **사유**를 보인다", async () => {
    const user = mount([
      complexItem({
        id: 9,
        name: "미상아파트",
        recent_price_krw: null,
        price_confidence: "unknown",
      }),
    ]);
    vi.mocked(api.affordability).mockResolvedValue({
      ...AFFORD,
      plan: null,
      target_price: {
        krw: null,
        basis: null,
        as_of_ym: null,
        sample_size: 0,
        period_months: null,
        reason: "이 단지의 실거래 자료가 없습니다",
      },
    });
    render(<Authenticated />);

    await user.click(await screen.findByText("미상아파트"));
    await user.click(screen.getByRole("button", { name: /내 자금/ }));

    const plan = await screen.findByRole("region", { name: "자금계획" });
    await waitFor(() => expect(plan.textContent).toContain("자금계획을 세우지 못했습니다"));
    expect(plan.textContent).toContain("이 단지의 실거래 자료가 없습니다");
    // 사유를 알고 있는데 "포함되지 않았습니다"로 뭉뚱그리지 않는다
    expect(plan.textContent).not.toContain("이 응답에는 자금계획이 포함되지 않았습니다");
  });
});

/**
 * 우측 패널 정리 — 목록 둘(주변 단지 · AI 추천)만 남기고, 내 자금은 **내 조건**의 버튼으로.
 * 그리고 목록 위의 예산 토글 · 특성 칩.
 */
describe("우측 패널 · 목록 필터", () => {
  function complexItem(over: Partial<ComplexItem> & { id: number; name: string }): ComplexItem {
    return {
      point: [127, 37.5],
      households: 500,
      built_year: 2005,
      recent_price_krw: 700_000_000,
      price_as_of: "2026-06-30",
      price_confidence: "estimated",
      active_listings: 1,
      over_budget: false,
      ...over,
    };
  }

  /**
   * 예산(8.5억) 안팎 · 세대수 있음/없음이 섞인 현실적인 목록.
   *
   * ⚠️ `over_budget` 은 **서버가 말한 판정**이다(CR38-1) — 화면은 이 값을 그대로 쓴다.
   *    그래서 목도 서버가 실제로 줄 값으로 적는다(1.2억 > 한도 8.5억 → `true`).
   */
  const ITEMS: ComplexItem[] = [
    complexItem({ id: 1, name: "대단지아파트", households: 1500, recent_price_krw: 700_000_000 }),
    complexItem({
      id: 2,
      name: "비싼아파트",
      households: 800,
      recent_price_krw: 1_200_000_000,
      over_budget: true,
    }),
    complexItem({ id: 3, name: "미상아파트", households: null, recent_price_krw: 600_000_000 }),
  ];

  function mount(items: ComplexItem[] = ITEMS) {
    installKakaoStub();
    vi.spyOn(api, "getProfile").mockResolvedValue(PROFILE);
    vi.spyOn(api, "getPreferences").mockResolvedValue(PREFS);
    vi.spyOn(api, "affordability").mockResolvedValue(AFFORD);
    vi.spyOn(api, "mapComplexes").mockResolvedValue({ level: "complex", items, note: "" });
    return userEvent.setup();
  }

  afterEach(() => forgetCamera());

  it("탭은 주변 단지 · AI 추천 둘뿐이다(내 자금은 탭이 아니다)", async () => {
    mount();
    render(<Authenticated />);

    await screen.findByRole("tab", { name: "주변 단지" });
    expect(screen.getByRole("tab", { name: "AI 추천" })).toBeTruthy();
    expect(screen.getAllByRole("tab")).toHaveLength(2);
    expect(screen.queryByRole("tab", { name: "내 자금" })).toBeNull();
  });

  it("내 조건의 '내 자금' 버튼으로 자금계획을 열고, 목록으로 되돌아온다", async () => {
    const user = mount();
    render(<Authenticated />);

    // 한도를 버튼에 함께 적는다 — 누르기 전에도 정보가 있어야 한다
    const btn = await screen.findByRole("button", { name: /내 자금/ });
    expect(btn.textContent).toContain("8.50억");

    await user.click(btn);
    expect(await screen.findByText("최대 실구매 가능 금액")).toBeTruthy();
    // 자금 화면에서는 목록 탭을 감춘다(지금 어디인지 분명하게)
    expect(screen.queryByRole("tab")).toBeNull();

    await user.click(screen.getByRole("button", { name: "← 목록으로" }));
    expect(await screen.findByRole("tab", { name: "주변 단지" })).toBeTruthy();
  });

  it("특성이 확인된 단지에만 배지가 붙는다(모르는 단지엔 안 붙는다)", async () => {
    mount();
    render(<Authenticated />);

    const big = (await screen.findByText("대단지아파트")).closest("article") as HTMLElement;
    // 단지명에도 "대단지"가 들어 있으므로 배지 요소를 직접 확인한다
    expect(big.querySelector(".tag--large_complex")?.textContent).toContain("대단지");

    const unknown = screen.getByText("미상아파트").closest("article") as HTMLElement;
    expect(unknown.querySelector(".tags")).toBeNull();
    // 세대수를 모른다는 사실은 캡션에 남는다(빈칸으로 두면 '작은 단지'로 읽힌다)
    expect(unknown.textContent).toContain("세대수 미상");
  });

  /**
   * CR32-5 — `GET /map/complexes` 가 이제 `nearest_station`·`redevelopment` 를 실제로
   * 싣는다(client.ts 주석 정정). 그 값이 "주변 단지" 목록의 배지로 실제로 이어지는지,
   * 그리고 `available:false` 를 "재건축 아님"으로 접지 않는지를 여기서 고정한다.
   *
   * `available:false` 를 `no` 로 접는 회귀가 생기면: ① 아래 칩을 눌렀을 때 판정 불가
   * 안내가 "2건"이 아니라 "1건"(필드 자체가 없는 단지만)으로 줄고, ② "판정 불가 항목도
   * 보기"를 눌러도 `available:false` 단지가 영영 돌아오지 않는다(matchTags 가 `no` 를
   * 즉시 배제하고 `unknown` 목록에 넣지 않기 때문 — lib/listFilter.ts).
   */
  it("지도 응답의 nearest_station · redevelopment 로 배지가 붙고, available:false 는 미확인으로 남는다", async () => {
    const user = mount([
      complexItem({
        id: 20,
        name: "역세권재건축단지",
        nearest_station: { name: "가나역", distance_m: 300, basis: "straight_line" },
        redevelopment: { available: true, stage: "조합설립인가" },
      }),
      complexItem({
        id: 21,
        name: "미확인재건축A",
        nearest_station: { distance_m: 900, basis: "straight_line" }, // 500m 밖 — 역세권 아님
        redevelopment: { available: false }, // ⚠️ "없음"이 아니라 "미확인"
      }),
      complexItem({ id: 22, name: "미확인재건축B" }), // 필드 자체가 없는 경우도 미확인
    ]);
    render(<Authenticated />);

    // ① 확인된 사실에는 실제로 배지가 붙는다.
    const confirmed = (await screen.findByText("역세권재건축단지")).closest(
      "article",
    ) as HTMLElement;
    expect(confirmed.querySelector(".tag--near_station")?.textContent).toContain("역세권");
    expect(confirmed.querySelector(".tag--redevelopment")?.textContent).toContain("재건축");

    // ② 500m 밖이라 역세권은 확실히 "아니다" — 배지 없음(오탐이 아니라 정상 미해당).
    const unknownA = screen.getByText("미확인재건축A").closest("article") as HTMLElement;
    expect(unknownA.querySelector(".tag--near_station")).toBeNull();
    // ③ available:false 는 "재건축 아님"이 아니라 "미확인" — 기본 화면엔 배지가 없다.
    expect(unknownA.querySelector(".tag--redevelopment")).toBeNull();

    // ④ 재건축 칩을 누르면 확실한 1건만 남고, 미확인 2건은 "제외"로 집계된다
    //    (필드가 없는 단지와 available:false 인 단지가 **같은 취급**을 받아야 한다).
    await user.click(screen.getByRole("button", { name: /재건축 1건/ }));
    expect(screen.queryByText("미확인재건축A")).toBeNull();
    expect(screen.queryByText("미확인재건축B")).toBeNull();
    expect(
      screen.getByText(/정비사업 확인 정보가 없어 판정할 수 없는 2건은 제외했습니다/),
    ).toBeTruthy();

    // ⑤ "판정 불가 항목도 보기"를 누르면 두 단지 모두 되살아나고, "아님"이 아니라
    //    "판정 불가"라고 스스로 밝힌다.
    await user.click(screen.getByRole("button", { name: "판정 불가 항목도 보기" }));
    const revivedA = (await screen.findByText("미확인재건축A")).closest("article") as HTMLElement;
    expect(within(revivedA).getByText(/재건축 판정 불가/)).toBeTruthy();
    const revivedB = screen.getByText("미확인재건축B").closest("article") as HTMLElement;
    expect(within(revivedB).getByText(/재건축 판정 불가/)).toBeTruthy();
  });

  it("예산 내 토글을 켜면 초과 단지가 빠지고 **몇 건 숨겼는지** 말한다", async () => {
    const user = mount();
    render(<Authenticated />);

    await screen.findByText("비싼아파트");
    await user.click(screen.getByRole("switch", { name: /예산 내/ }));

    expect(screen.queryByText("비싼아파트")).toBeNull();
    expect(screen.getByText(/예산 초과 1건 숨김/)).toBeTruthy();
    expect(screen.getByText("대단지아파트")).toBeTruthy();
  });

  it("대단지 칩을 눌러도 세대수 미상 단지가 조용히 사라지지 않는다", async () => {
    const user = mount();
    render(<Authenticated />);

    await screen.findByText("미상아파트");
    await user.click(screen.getByRole("button", { name: /대단지 1건/ }));

    // 확실히 아닌 단지(800세대)는 그냥 빠지지만, **모르는 단지는 숫자로 남는다**
    expect(screen.queryByText("미상아파트")).toBeNull();
    expect(screen.getByText(/세대수 정보가 없어 판정할 수 없는 1건은 제외했습니다/)).toBeTruthy();

    // 그리고 볼 수 있는 길이 있다
    await user.click(screen.getByRole("button", { name: "판정 불가 항목도 보기" }));
    expect(screen.getByText("미상아파트")).toBeTruthy();
    // 되살아난 항목은 '대단지'인 척하지 않는다
    const revived = screen.getByText("미상아파트").closest("article") as HTMLElement;
    expect(within(revived).getByText(/대단지 판정 불가/)).toBeTruthy();
  });

  it("필터로 전부 가려지면 '단지가 없다'가 아니라 '가려졌다'고 말한다", async () => {
    const user = mount([
      complexItem({
        id: 2,
        name: "비싼아파트",
        recent_price_krw: 1_200_000_000,
        over_budget: true,
      }),
    ]);
    render(<Authenticated />);

    await screen.findByText("비싼아파트");
    await user.click(screen.getByRole("switch", { name: /예산 내/ }));

    expect(screen.getByText(/필터에 걸려 1건이 모두 가려졌습니다/)).toBeTruthy();
  });

  /**
   * CR35-4 — 지도 금액이 **어느 면적의 체결가인지**.
   * 서울 단지 절반이 조건 밖 면적을 보여주고 있었고 평균 22.2% 어긋났다. 서버가 이제
   * 조건 안에서 고르지만, 화면이 면적을 말하지 않으면 사용자는 자기가 보는 평형의
   * 값으로 읽는다.
   */
  it("금액 옆에 그 금액이 나온 전용면적을 적는다", async () => {
    mount([complexItem({ id: 1, name: "면적아파트", price_area_m2: 59.94 })]);
    render(<Authenticated />);

    const card = (await screen.findByText("면적아파트")).closest("article") as HTMLElement;
    expect(within(card).getByText("전용 59.94㎡")).toBeTruthy();
  });

  it("서버가 면적을 안 주면 **아무 말도 하지 않는다**(지어내지 않는다)", async () => {
    mount([complexItem({ id: 1, name: "면적미상아파트" })]);
    render(<Authenticated />);

    const card = (await screen.findByText("면적미상아파트")).closest("article") as HTMLElement;
    expect(card.querySelector(".card__pricearea")).toBeNull();
  });
});

/**
 * 예산 칩 — **껐을 때 화면이 실제로 달라지는가** (CR37-7).
 *
 * 예전 칩은 켜도 꺼도 화면이 똑같았다. 라벨은 "희망가 9.00억 **이하**"라고 걸러진다는
 * 말을 했지만 지도·목록은 거르지 않았고(의도된 설계 — `ux/README §4`), `listBudgetKrw`
 * 는 칩 상태를 보지도 않았다. 즉 **거짓 라벨 + 죽은 스위치**가 한자리에 있었다.
 *
 * 이제 역할을 둘로 나눴다. 이 describe 가 그 경계를 고정한다.
 *   · 예산 칩(내 조건)  = 초과를 **표시할지**  — 아무것도 숨기지 않는다
 *   · `예산 내` 토글    = 초과를 **숨길지**    — 몇 건 숨겼는지 말한다
 *
 * ⚠️ 이 검사가 화면(DOM)에 있어야 하는 이유: 순수 함수는 `applyScreenBudget` 이 null 을
 *    돌려준다까지만 보장한다. 그 null 이 **배지·마커·문장까지 도달하는가**는 DOM 을
 *    봐야 안다. 예전 결함이 정확히 "계산은 바뀌는데 화면은 그대로"였다.
 *
 * ⚠️ CR38-1 이후: 판정은 **서버**가 하고 칩은 그 표시를 켜고 끈다. 그래서 이 describe 는
 *    "칩을 끄면 화면이 **재조회를 기다리지 않고** 배지를 비우는가"까지 함께 고정한다 —
 *    목은 칩 상태와 무관하게 같은 응답을 주므로, 화면이 비우지 않으면 배지가 남는다.
 */
describe("예산 칩은 초과 표시를 켜고 끈다 (거르지 않는다)", () => {
  function complexItem(over: Partial<ComplexItem> & { id: number; name: string }): ComplexItem {
    return {
      point: [127, 37.5],
      households: 500,
      built_year: 2005,
      recent_price_krw: 700_000_000,
      price_as_of: "2026-06-30",
      price_confidence: "estimated",
      active_listings: 1,
      over_budget: false, // 서버 판정(한도 8.5억 안)
      ...over,
    };
  }

  /** 한도 8.5억 기준: 하나는 안, 하나는 밖 — **서버가 그렇게 판정해 보냈다.** */
  const ITEMS: ComplexItem[] = [
    complexItem({ id: 1, name: "싼아파트", recent_price_krw: 700_000_000, over_budget: false }),
    complexItem({ id: 2, name: "비싼아파트", recent_price_krw: 1_200_000_000, over_budget: true }),
  ];

  let kakao: KakaoStubHandle | null = null;

  function mount() {
    kakao = installKakaoStub();
    vi.spyOn(api, "getProfile").mockResolvedValue(PROFILE);
    vi.spyOn(api, "getPreferences").mockResolvedValue(PREFS);
    vi.spyOn(api, "affordability").mockResolvedValue(AFFORD);
    vi.spyOn(api, "mapComplexes").mockResolvedValue({
      level: "complex",
      items: ITEMS,
      note: "",
    });
    return userEvent.setup();
  }

  afterEach(() => {
    kakao?.restore();
    kakao = null;
    forgetCamera();
  });

  const chip = () => screen.getByRole("button", { name: "내 예산 8.50억 초과 표시" });
  const card = (name: string) =>
    (screen.getByText(name).closest("article") as HTMLElement) ?? null;
  const pillOf = (name: string) =>
    kakao!.overlays
      .map((o) => o.opts.content as HTMLElement)
      .find((el) => (el.getAttribute("aria-label") ?? "").includes(name));

  it("켜져 있으면 초과 단지에 배지·마커 표시가 붙는다(기준선)", async () => {
    mount();
    render(<Authenticated />);
    await screen.findByText("비싼아파트");
    await waitFor(() => expect(kakao!.overlays.length).toBeGreaterThan(0));

    expect(chip().getAttribute("aria-pressed")).toBe("true");
    expect(within(card("비싼아파트")).getByText("예산 초과")).toBeTruthy();
    expect(pillOf("비싼아파트")!.className).toContain("map-pill--over");
    expect(pillOf("비싼아파트")!.getAttribute("aria-label")).toContain("예산 초과");
    // 예산 안 단지에는 애초에 아무 표시가 없다(그래서 null 과 false 가 구분 안 된다)
    expect(within(card("싼아파트")).queryByText("예산 초과")).toBeNull();
  });

  it("끄면 **배지·마커 표시가 사라지고**, 껐다는 사실을 말한다", async () => {
    const user = mount();
    render(<Authenticated />);
    await screen.findByText("비싼아파트");
    await waitFor(() => expect(kakao!.overlays.length).toBeGreaterThan(0));

    await user.click(chip());

    expect(chip().getAttribute("aria-pressed")).toBe("false");
    // ① 카드 배지
    expect(within(card("비싼아파트")).queryByText("예산 초과")).toBeNull();
    // ② 지도 마커(클래스와 보조기기 라벨 양쪽)
    await waitFor(() => expect(pillOf("비싼아파트")!.className).not.toContain("map-pill--over"));
    expect(pillOf("비싼아파트")!.getAttribute("aria-label")).not.toContain("예산 초과");
    // ③ 화면이 그 사실을 말한다 — "판정이 없다"가 아니라 "껐다"
    expect(screen.getByText(/예산 초과 표시를 꺼 두었습니다/)).toBeTruthy();
    expect(screen.queryByText(/예산 판정이 된 항목이 없어/)).toBeNull();
    expect(screen.queryByText(/예산 초과 1건도 함께 보는 중/)).toBeNull();
  });

  it("꺼도 **단지는 그대로 보인다** — 표시를 끄는 것이지 거르는 게 아니다", async () => {
    const user = mount();
    render(<Authenticated />);
    await screen.findByText("비싼아파트");

    await user.click(chip());

    // 예산 밖 단지를 지우면 "얼마나 모자란가"가 사라진다(ux §4). 그래서 남는다.
    expect(screen.getByText("비싼아파트")).toBeTruthy();
    expect(screen.getByText("싼아파트")).toBeTruthy();
  });

  it("표시를 끄면 `예산 내` 토글은 **잠긴다** — 숨길 근거 자체가 없어졌기 때문이다", async () => {
    const user = mount();
    render(<Authenticated />);
    await screen.findByText("비싼아파트");

    const sw = screen.getByRole("switch", { name: /예산 내/ }) as HTMLButtonElement;
    expect(sw.disabled).toBe(false); // 켜져 있을 때는 쓸 수 있다

    await user.click(chip());

    const off = screen.getByRole("switch", { name: /예산 내/ }) as HTMLButtonElement;
    expect(off.disabled).toBe(true);
    // 왜 못 누르는지가 스위치에 붙어 있다(비활성 버튼은 초점을 못 받는다)
    const note = screen.getByText(/예산 초과 표시를 꺼 두었습니다/);
    expect(off.getAttribute("aria-describedby")).toBe(note.id);
  });

  it("다시 켜면 되돌아온다 — 되돌릴 수 없으면 스위치가 아니다", async () => {
    const user = mount();
    render(<Authenticated />);
    await screen.findByText("비싼아파트");

    await user.click(chip());
    await user.click(chip());

    expect(within(card("비싼아파트")).getByText("예산 초과")).toBeTruthy();
    await waitFor(() => expect(pillOf("비싼아파트")!.className).toContain("map-pill--over"));
    expect(screen.queryByText(/예산 초과 표시를 꺼 두었습니다/)).toBeNull();
  });

  it("`예산 내` 토글은 여전히 **숨기는** 일을 한다(칩과 역할이 겹치지 않는다)", async () => {
    const user = mount();
    render(<Authenticated />);
    await screen.findByText("비싼아파트");

    await user.click(screen.getByRole("switch", { name: /예산 내/ }));

    // 칩은 켜 둔 채다 — 표시는 켜져 있고, 토글이 초과분을 숨긴다(그리고 건수를 말한다)
    expect(chip().getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByText("비싼아파트")).toBeNull();
    expect(screen.getByText(/예산 초과 1건 숨김/)).toBeTruthy();
  });
});

/**
 * ⛔ CR38-1 — **면적이 섞인 지도에서, 배지가 그 단지의 자금계획과 같은 말을 하는가.**
 *
 * 무엇이 결함이었나
 * -----------------
 * 실구매 가능 금액은 **하나의 숫자가 아니다.** 취득세율이 85㎡ 에서 갈리므로(농특세
 * 0.2% 가산) 같은 자산이라도 상한이 면적별로 다르다 — 실측 차이 198만원.
 * 서버는 항목마다 그 항목 거래의 면적으로 상한을 세우는데, 화면은 `/affordability` 가
 * 준 **한 숫자**(선택 단지의 면적, 없으면 84㎡)로 지도 전체를 판정했다.
 * 그래서 120㎡ 단지의 배지가 84㎡ 한도로 서 있었다.
 *
 * 왜 이 세 상태인가 (리뷰어 지정)
 * -------------------------------
 *   ① 단지 미선택   — **로그인 직후 지도를 처음 여는 기본 경로**(서버 기본 84㎡)
 *   ② 85㎡ 이하 선택 — 화면 한도가 작은 쪽으로 굳는다
 *   ③ 85㎡ 초과 선택 — 화면 한도가 큰 쪽으로 굳는다
 * 세 상태 전부에서 화면의 한 숫자와 서버의 항목별 숫자가 갈렸다(각 conflicts=2).
 *
 * 이 검사가 잡는 변이
 * -------------------
 * 배지를 화면 판정으로 되돌리면 — 어느 상태에서든 4개 단지가 **전부 같은 판정**이 된다
 * (가격이 같으므로). 그러면 아래 표와 어긋나 죽는다. 순수 함수 층에서는 이걸 볼 수 없다:
 * 면적별 상한을 화면이 아예 모르기 때문에 "무엇이 옳은지"를 서버 값 없이는 못 적는다.
 */
describe("면적이 섞인 지도 — 배지는 항목마다 그 면적의 한도로 선다 (CR38-1)", () => {
  /** 운영 세율 기준 실측값(리뷰어 재현). 두 상한 **사이**의 가격을 쓴다. */
  const CAP_UNDER_85 = 1_026_560_000;
  const CAP_OVER_85 = 1_024_580_000;
  const PRICE = 1_025_570_000; // CAP_OVER_85 < PRICE < CAP_UNDER_85

  /**
   * 서버가 항목마다 내리는 판정. **이 표가 정답지다** —
   * 85㎡ 이하는 예산 안, 초과는 예산 밖(같은 가격인데도).
   */
  const ROWS: Array<{ id: number; name: string; area: number; over: boolean }> = [
    { id: 1, name: "오구단지", area: 59.9, over: PRICE > CAP_UNDER_85 },
    { id: 2, name: "팔사단지", area: 84.0, over: PRICE > CAP_UNDER_85 },
    { id: 3, name: "일일사단지", area: 114.5, over: PRICE > CAP_OVER_85 },
    { id: 4, name: "일이공단지", area: 120.0, over: PRICE > CAP_OVER_85 },
  ];

  const ITEMS: ComplexItem[] = ROWS.map((r) => ({
    id: r.id,
    name: r.name,
    point: [127 + r.id * 0.001, 37.5],
    households: 500,
    built_year: 2005,
    recent_price_krw: PRICE,
    price_area_m2: r.area,
    price_as_of: "2026-06-30",
    price_confidence: "estimated",
    active_listings: 1,
    over_budget: r.over,
  }));

  let kakao: KakaoStubHandle | null = null;

  /**
   * `/affordability` 는 **면적을 받아 그 면적의 한도**를 준다(서버가 실제로 그렇다).
   * 화면이 이 한 숫자로 지도를 판정하면 상태마다 다른 답이 나온다 — 그게 결함이었다.
   */
  function mount() {
    kakao = installKakaoStub();
    vi.spyOn(api, "getProfile").mockResolvedValue(PROFILE);
    vi.spyOn(api, "getPreferences").mockResolvedValue(PREFS);
    vi.spyOn(api, "affordability").mockImplementation(async (body) => ({
      ...AFFORD,
      max_purchase_krw: (body?.area_m2 ?? 84) > 85 ? CAP_OVER_85 : CAP_UNDER_85,
    }));
    vi.spyOn(api, "mapComplexes").mockResolvedValue({
      level: "complex",
      items: ITEMS,
      note: "",
      budget: { applied: true, basis: "max_purchase", reason: null },
    });
    return userEvent.setup();
  }

  afterEach(() => {
    kakao?.restore();
    kakao = null;
    forgetCamera();
  });

  const cardOf = (name: string) => screen.getByText(name).closest("article") as HTMLElement;
  const pillOf = (name: string) =>
    kakao!.overlays
      .map((o) => o.opts.content as HTMLElement)
      .find((el) => (el.getAttribute("aria-label") ?? "").includes(name));

  /** 카드·마커 **양쪽**이 서버 판정과 같은 말을 하는가. */
  async function expectMatchesServer() {
    await waitFor(() => expect(kakao!.overlays.length).toBeGreaterThanOrEqual(ROWS.length));
    for (const r of ROWS) {
      const badge = within(cardOf(r.name)).queryByText("예산 초과");
      expect(badge === null, `${r.name}(${r.area}㎡) 카드 배지가 서버 판정과 다르다`).toBe(!r.over);

      const label = pillOf(r.name)!.getAttribute("aria-label") ?? "";
      expect(
        label.includes("예산 초과"),
        `${r.name}(${r.area}㎡) 마커 라벨이 서버 판정과 다르다`,
      ).toBe(r.over);
    }
  }

  it("① 단지 미선택(로그인 직후 기본 경로) — 서버 판정 그대로", async () => {
    mount();
    render(<Authenticated />);
    await screen.findByText("일이공단지");

    // 화면이 아는 한도는 84㎡ 기준 하나뿐이다(선택한 단지가 없다).
    await waitFor(() => expect(api.affordability).toHaveBeenCalled());
    expect(vi.mocked(api.affordability).mock.calls.at(-1)![0]?.area_m2).toBeUndefined();

    await expectMatchesServer();
  });

  it("② 85㎡ **이하** 단지를 고른 상태 — 화면 한도가 커져도 배지는 그대로", async () => {
    const user = mount();
    render(<Authenticated />);
    await screen.findByText("오구단지");

    await user.click(screen.getByText("오구단지"));
    // 선택이 자금계획까지 닿았는지 먼저 확인한다(안 닿았으면 이 상태를 밟은 게 아니다)
    await waitFor(() =>
      expect(vi.mocked(api.affordability).mock.calls.at(-1)![0]?.area_m2).toBe(59.9),
    );

    await expectMatchesServer();
  });

  it("③ 85㎡ **초과** 단지를 고른 상태 — 화면 한도가 작아져도 배지는 그대로", async () => {
    const user = mount();
    render(<Authenticated />);
    await screen.findByText("일일사단지");

    await user.click(screen.getByText("일일사단지"));
    await waitFor(() =>
      expect(vi.mocked(api.affordability).mock.calls.at(-1)![0]?.area_m2).toBe(114.5),
    );

    await expectMatchesServer();
  });

  /**
   * 세 상태를 밟는 것만으로는 부족하다 — **경계가 실재하는지** 먼저 단언한다.
   * 두 상한이 같아지는 날(세율이 통일되면) 위 세 검사는 조용히 빈 검사가 된다.
   */
  it("이 검사가 밟는 경계가 실재한다 — 두 상한이 다르고 가격이 그 사이에 있다", () => {
    expect(CAP_OVER_85).toBeLessThan(CAP_UNDER_85);
    expect(PRICE).toBeGreaterThan(CAP_OVER_85);
    expect(PRICE).toBeLessThan(CAP_UNDER_85);
    // 정답지가 실제로 갈린다(전부 같은 답이면 어떤 판정이든 통과해 버린다)
    expect(new Set(ROWS.map((r) => r.over)).size).toBe(2);
  });

  /**
   * `예산 내` 토글의 **숨김 건수**도 같은 판정을 쓰는가.
   * 배지만 고치고 집계를 놓치면 "배지는 2건인데 2건 숨김이라고 안 하는" 화면이 된다.
   */
  it("`예산 내` 토글도 항목별 판정으로 센다 — 85㎡ 초과 2건만 숨긴다", async () => {
    const user = mount();
    render(<Authenticated />);
    await screen.findByText("일이공단지");

    await user.click(screen.getByRole("switch", { name: /예산 내/ }));

    expect(screen.getByText(/예산 초과 2건 숨김/)).toBeTruthy();
    expect(screen.getByText("오구단지")).toBeTruthy();
    expect(screen.getByText("팔사단지")).toBeTruthy();
    expect(screen.queryByText("일일사단지")).toBeNull();
    expect(screen.queryByText("일이공단지")).toBeNull();
  });
});

/**
 * CR35-2 — **없는 화면으로 안내하던 문제**.
 *
 * 추천 결과는 "'내 매물'에서 직접 입력하시면 가격 축이 반영됩니다"라고 말하는데
 * 그런 화면이 없었다. 여기서는 그 화면으로 가는 **길**이 실제로 있는지를 고정한다
 * (화면 내부 동작은 MyListingsScreen.test.tsx 가 본다).
 */
describe("내 매물 진입 동선", () => {
  function complexItem(over: Partial<ComplexItem> & { id: number; name: string }): ComplexItem {
    return {
      point: [127, 37.5],
      households: 500,
      built_year: 2005,
      recent_price_krw: 700_000_000,
      price_as_of: "2026-06-30",
      price_confidence: "estimated",
      active_listings: 0,
      over_budget: false,
      ...over,
    };
  }

  function mount(items: ComplexItem[]) {
    installKakaoStub();
    vi.spyOn(api, "getProfile").mockResolvedValue(PROFILE);
    vi.spyOn(api, "getPreferences").mockResolvedValue(PREFS);
    vi.spyOn(api, "affordability").mockResolvedValue(AFFORD);
    vi.spyOn(api, "mapComplexes").mockResolvedValue({ level: "complex", items, note: "" });
    // 목은 `src/test/fixtures.ts` 에서만 만든다(계약 대조 테스트가 그 목을 지킨다)
    vi.spyOn(api, "listMyListings").mockResolvedValue(emptyUserListingList());
    return userEvent.setup();
  }

  afterEach(() => forgetCamera());

  it("내 조건 옆의 '내 매물' 버튼으로 열고, 목록으로 되돌아온다", async () => {
    const user = mount([]);
    render(<Authenticated />);

    // 열기 전에는 요청도 나가지 않는다(지도만 보는 사용자에게 요청을 얹지 않는다)
    await screen.findByRole("button", { name: "내 매물" });
    expect(api.listMyListings).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "내 매물" }));

    expect(await screen.findByText(/아직 입력한 호가가 없습니다/)).toBeTruthy();
    await waitFor(() => expect(api.listMyListings).toHaveBeenCalled());
    // 자금 화면과 같은 규칙: 지금 어디인지 분명하게(탭 감춤) + 돌아갈 길
    expect(screen.queryByRole("tab")).toBeNull();

    await user.click(screen.getByRole("button", { name: "← 목록으로" }));
    expect(await screen.findByRole("tab", { name: "주변 단지" })).toBeTruthy();
  });

  it("단지를 고르면 그 단지로 좁혀 열리고 입력 폼이 함께 뜬다", async () => {
    const user = mount([complexItem({ id: 7, name: "가나아파트" })]);
    render(<Authenticated />);

    await user.click(await screen.findByText("가나아파트"));
    await user.click(await screen.findByRole("button", { name: "가나아파트 호가 입력" }));

    // 목록 조회도 그 단지로 좁혀 나간다
    await waitFor(() => expect(api.listMyListings).toHaveBeenCalledWith(7));
    // 폼은 어느 단지의 호가인지 말한다
    const form = await screen.findByRole("form", { name: "이 단지에서 본 호가 적기" });
    expect(within(form).getByText("가나아파트")).toBeTruthy();
    // 확인 날짜는 비어 있다(오늘로 미리 채우지 않는다)
    expect((within(form).getByLabelText("이 호가를 확인한 날짜") as HTMLInputElement).value).toBe(
      "",
    );
  });
});

/**
 * CR36-1 — **배선이 끊겨도 아무도 모르는 문제.**
 *
 * `RecommendPanel`·`ReportCard` 의 동선 prop 은 전부 **선택(optional)** 이고, 화면은
 * "죽은 버튼 금지" 원칙에 따라 *prop 이 없으면 버튼을 아예 그리지 않는다.* 좋은 규칙인데,
 * 부작용이 있다: App 에서 `onAddListing={openListings}` 한 줄을 지워도 **타입도 통과하고
 * 테스트도 전부 통과한다.** 버튼만 조용히 사라진다 — CR35-2 가 막으려던 상태
 * (안내는 있는데 갈 수 없음)가 그대로 되살아난다.
 *
 * 컴포넌트 단위 테스트로는 못 잡는다. 그쪽은 prop 을 **직접 넘겨서** 검사하므로
 * "App 이 실제로 넘기는가"는 검사 범위 밖이다. 그래서 여기서 화면 끝에서 끝까지 누른다.
 *
 * 아래 4건은 `RecommendPanel` 이 가진 **선택 prop 전수**에 대응한다:
 *   onAddListing · onShowOnMap · onBudgetOnlyChange · onEditConditions
 * (`onCancel`·`onStart` 는 필수 prop 이라 빠뜨리면 tsc 가 잡는다.)
 */
describe("추천 결과의 동선이 App 에 실제로 연결돼 있다", () => {
  function complexItem(over: Partial<ComplexItem> & { id: number; name: string }): ComplexItem {
    return {
      point: [127, 37.5],
      households: 500,
      built_year: 2005,
      recent_price_krw: 700_000_000,
      price_as_of: "2026-06-30",
      price_confidence: "estimated",
      active_listings: 0,
      over_budget: false,
      ...over,
    };
  }

  /** 호가가 없는(공공API만 있는) 현실의 기본 케이스 — 가격 축이 통째로 빠져 있는 후보. */
  function recItem(
    complex: { id: number; name: string },
    over: Partial<RecommendationItem> = {},
  ): RecommendationItem {
    return {
      rank: 1,
      complex,
      unit_type: { area_m2: 84.97 },
      building: null,
      dong_valuation: null,
      price_basis: "trade",
      ask_price_krw: null,
      est_price_krw: 700_000_000,
      price_estimated: true,
      price_note: "현재 등록된 매물이 없습니다 — 최근 실거래 기준 추정가입니다.",
      ask_gap_pct: null,
      price_band: null,
      total_score: null,
      score_basis: null,
      timing_signal: "unknown",
      headline: "후보입니다.",
      why: [],
      why_not: [],
      next_actions: [],
      findings: [],
      ...over,
    };
  }

  function mount(items: ComplexItem[], recItems: RecommendationItem[]) {
    installKakaoStub();
    vi.spyOn(api, "getProfile").mockResolvedValue(PROFILE);
    vi.spyOn(api, "getPreferences").mockResolvedValue(PREFS);
    vi.spyOn(api, "affordability").mockResolvedValue(AFFORD);
    vi.spyOn(api, "mapComplexes").mockResolvedValue({ level: "complex", items, note: "" });
    vi.spyOn(api, "listMyListings").mockResolvedValue(emptyUserListingList());
    vi.spyOn(api, "createRecommendation").mockResolvedValue({ job_id: "rec_1", status: "queued" });
    vi.spyOn(api, "recommendation").mockResolvedValue({
      job_id: "rec_1",
      status: "done",
      items: recItems,
    });
    return userEvent.setup();
  }

  afterEach(() => forgetCamera());

  /** AI 추천 탭으로 가서 결과가 나올 때까지. */
  async function runRecommendation(user: ReturnType<typeof userEvent.setup>) {
    await user.click(await screen.findByRole("tab", { name: "AI 추천" }));
    await user.click(screen.getByRole("button", { name: "AI 추천 실행" }));
  }

  it("'이 단지 호가 입력'이 실제로 내 매물 화면을 연다 (CR36-1 · onAddListing)", async () => {
    const user = mount(
      [complexItem({ id: 1024, name: "○○아파트" })],
      [recItem({ id: 1024, name: "○○아파트" })],
    );
    render(<Authenticated />);
    await runRecommendation(user);

    // 결과 카드가 "'내 매물'에서 입력하면 가격 축이 반영됩니다"라고 말하는 바로 그 자리
    await user.click(await screen.findByRole("button", { name: "이 단지 호가 입력" }));

    // 그 화면이 **그 단지로 좁혀** 열려야 한다 — 배선이 끊기면 버튼부터 없다
    await waitFor(() => expect(api.listMyListings).toHaveBeenCalledWith(1024));
    const form = await screen.findByRole("form", { name: "이 단지에서 본 호가 적기" });
    expect(within(form).getByText("○○아파트")).toBeTruthy();
  });

  it("'지도에서 보기'가 실제로 지도 탭에서 그 단지를 고른다 (onShowOnMap)", async () => {
    const user = mount(
      [complexItem({ id: 1024, name: "○○아파트" })],
      [recItem({ id: 1024, name: "○○아파트" })],
    );
    render(<Authenticated />);
    await runRecommendation(user);

    await user.click(await screen.findByRole("button", { name: "지도에서 보기" }));

    // 탭이 바뀌고(주변 단지) **선택까지** 이어져야 한다 — 선택되면 자금계획 진입점이 생긴다
    expect(screen.getByRole("tab", { name: "주변 단지" }).getAttribute("aria-selected")).toBe(
      "true",
    );
    expect(await screen.findByRole("button", { name: "○○아파트 자금계획 보기" })).toBeTruthy();
  });

  /**
   * ⚠️ 이 스위치는 **끊겨도 사라지지 않는다** — `onBudgetOnlyChange ?? (() => {})` 라
   *    배선이 없으면 버튼은 멀쩡히 뜨고 눌러도 아무 일이 없다. 사라지는 버튼보다 나쁘다.
   */
  it("AI 추천 탭의 예산 스위치가 실제로 목록을 바꾼다 (onBudgetOnlyChange)", async () => {
    const user = mount(
      [],
      [
        recItem({ id: 1, name: "예산내아파트" }, { est_price_krw: 700_000_000 }),
        recItem({ id: 2, name: "예산초과아파트" }, { rank: 2, est_price_krw: 1_200_000_000 }),
      ],
    );
    render(<Authenticated />);
    await runRecommendation(user);

    expect(await screen.findByText("예산초과아파트")).toBeTruthy();
    await user.click(screen.getByRole("switch", { name: /예산 내/ }));

    expect(screen.queryByText("예산초과아파트")).toBeNull();
    expect(screen.getByText("예산내아파트")).toBeTruthy();
  });

  it("후보가 0건일 때 '조건 넓히기'가 조건 화면을 연다 (onEditConditions)", async () => {
    const user = mount([], []);
    render(<Authenticated />);
    await runRecommendation(user);

    await user.click(await screen.findByRole("button", { name: "조건 넓히기" }));

    expect(await screen.findByRole("heading", { name: "내 조건", level: 1 })).toBeTruthy();
  });
});

/**
 * 같은 형태(선택 prop = 배선이 끊기면 조용히 사라지는 길)의 나머지 두 곳.
 * 전수 점검에서 **아무 테스트도 잡지 못하던** 자리라 여기에 고정한다.
 */
describe("나머지 동선도 App 에 연결돼 있다", () => {
  function complexItem(over: Partial<ComplexItem> & { id: number; name: string }): ComplexItem {
    return {
      point: [126.978, 37.5665],
      households: 500,
      built_year: 2005,
      recent_price_krw: 700_000_000,
      price_as_of: "2026-06-30",
      price_confidence: "estimated",
      active_listings: 0,
      over_budget: false,
      ...over,
    };
  }

  let kakao: KakaoStubHandle | null = null;

  /** "단지 기준 해제"는 **계획이 실제로 서 있을 때만** 뜬다(빈 화면에는 되돌릴 것도 없다). */
  const AFFORD_WITH_PLAN: AffordabilityResponse = {
    ...AFFORD,
    plan: {
      target_price_krw: 700_000_000,
      total_needed_krw: 725_000_000,
      cost_breakdown: { tax: 19_000_000, brokerage: 5_000_000, etc: 1_000_000 },
      own_cash_krw: 300_000_000,
      shortfall_krw: 425_000_000,
      required_loan_krw: 425_000_000,
      loan_feasible: true,
      loan_limit_krw: 550_000_000,
      binding_constraint: "DSR",
      monthly_payment_krw: 2_029_000,
      total_interest_krw: 305_000_000,
      terms: { annual_rate_pct: 4.0, years: 30 },
    },
  };

  function mount(items: ComplexItem[]) {
    kakao = installKakaoStub();
    vi.spyOn(api, "getProfile").mockResolvedValue(PROFILE);
    vi.spyOn(api, "getPreferences").mockResolvedValue(PREFS);
    vi.spyOn(api, "affordability").mockResolvedValue(AFFORD_WITH_PLAN);
    vi.spyOn(api, "mapComplexes").mockResolvedValue({ level: "complex", items, note: "" });
    return userEvent.setup();
  }

  afterEach(() => {
    kakao?.restore();
    kakao = null;
    forgetCamera();
  });

  /**
   * 단지 기준으로 세운 자금계획에서 **되돌아오는 길**(AffordabilityPanel.onClearComplex).
   * 배선이 끊기면 버튼만 사라지고, 사용자는 단지 기준 계획에 갇힌다.
   */
  it("자금계획에서 '단지 기준 해제'로 되돌아올 수 있다 (onClearComplex)", async () => {
    const user = mount([complexItem({ id: 7, name: "가나아파트" })]);
    render(<Authenticated />);

    await user.click(await screen.findByText("가나아파트"));
    await user.click(screen.getByRole("button", { name: /내 자금/ }));

    const plan = await screen.findByRole("region", { name: "자금계획" });
    await waitFor(() => expect(plan.textContent).toContain("가나아파트"));

    await user.click(await screen.findByRole("button", { name: "단지 기준 해제" }));

    // 단지 기준이 풀리면 계획은 다시 "한도만" 보는 상태로 돌아간다
    await waitFor(() => expect(plan.textContent).not.toContain("가나아파트"));
  });

  /**
   * 마커·카드의 "예산 초과"는 **서버 판정**이다 (CR38-1).
   *
   * 서버는 항목마다 **그 항목 면적의 한도**로 판정한다. 화면이 아는 한도는 하나뿐이라
   * (선택 단지 면적, 없으면 84㎡) 화면이 다시 판정하면 면적이 섞인 지도에서 틀린다.
   *
   * 이 검사는 그 되돌림을 **가격 하나로** 잡는다: 화면 한도(8.5억)로는 초과인 가격에
   * 서버가 `false` 를 줬을 때, 화면 판정이 되살아나면 배지가 붙어 여기서 죽는다.
   */
  it("서버가 over_budget:false 라고 하면 마커에 초과 표시가 **붙지 않는다**", async () => {
    mount([
      complexItem({
        id: 9,
        name: "비싼아파트",
        recent_price_krw: 1_200_000_000, // 화면이 아는 한도(8.5억)로는 초과
        over_budget: false, // ← 서버는 '예산 내'라고 판정했다
      }),
    ]);
    render(<Authenticated />);
    await screen.findByText("비싼아파트");

    await waitFor(() => expect(kakao!.overlays.length).toBeGreaterThan(0));
    const pill = kakao!.overlays
      .map((o) => o.opts.content as HTMLElement)
      .find((el) => (el.getAttribute("aria-label") ?? "").includes("비싼아파트"));
    expect(pill!.className).not.toContain("map-pill--over");
    expect(pill!.getAttribute("aria-label")).not.toContain("예산 초과");
    // 카드도 같은 값을 쓴다 — 마커와 카드가 다른 말을 하면 안 된다
    const card = screen.getByText("비싼아파트").closest("article") as HTMLElement;
    expect(within(card).queryByText("예산 초과")).toBeNull();
  });

  /**
   * 서버가 `over_budget: null`(판정 못 함)을 줬을 때.
   * **`false` 로 접어도 · 화면이 대신 판정해도** 겉보기가 달라지므로 양쪽을 다 본다.
   */
  it("over_budget:null 이면 배지가 없다 — 화면이 대신 판정하지 않는다", async () => {
    mount([
      complexItem({
        id: 9,
        name: "비싼아파트",
        recent_price_krw: 1_200_000_000,
        over_budget: null, // 서버가 이 단지를 판정하지 못했다(면적 미상 등)
      }),
    ]);
    render(<Authenticated />);
    await screen.findByText("비싼아파트");

    await waitFor(() => expect(kakao!.overlays.length).toBeGreaterThan(0));
    const pill = kakao!.overlays
      .map((o) => o.opts.content as HTMLElement)
      .find((el) => (el.getAttribute("aria-label") ?? "").includes("비싼아파트"));
    expect(pill!.getAttribute("aria-label")).not.toContain("예산 초과");
    // 판정이 없으니 '예산 내' 토글도 켤 수 없다(켜면 이 단지가 통째로 사라진다)
    const sw = screen.getByRole("switch", { name: /예산 내/ }) as HTMLButtonElement;
    expect(sw.disabled).toBe(true);
    expect(screen.getByText(/예산 판정이 된 항목이 없어/)).toBeTruthy();
  });

  /**
   * 지도 마커 탭 → 선택 (MapView.onSelect).
   * ⚠️ 이건 사라지는 버튼이 아니라 **죽은 마커**다 — 마커는 그대로 있고 눌러도 아무 일이
   *    없다. 그래서 더 늦게 발견된다. 마커 DOM(오버레이 content)을 직접 눌러 확인한다.
   */
  it("지도 마커를 누르면 그 단지가 선택된다 (MapView.onSelect)", async () => {
    mount([complexItem({ id: 7, name: "가나아파트" })]);
    render(<Authenticated />);
    await screen.findByText("가나아파트");

    await waitFor(() => expect(kakao!.overlays.length).toBeGreaterThan(0));
    const pill = kakao!.overlays
      .map((o) => o.opts.content as HTMLElement)
      .find((el) => (el.getAttribute("aria-label") ?? "").includes("가나아파트"));
    expect(pill, "마커가 그려지지 않았다").toBeTruthy();

    fireEvent.click(pill!);

    // 선택되면 그 단지의 자금계획 진입점이 생긴다(= onSelect 가 App 까지 닿았다)
    expect(
      await screen.findByRole("button", { name: "가나아파트 자금계획 보기" }),
    ).toBeTruthy();
  });
});

/**
 * 지도 예산 계약 (api-spec §4 · 2026-07-29) — **켰는데 아무 일도 안 일어나면 말한다.**
 *
 * 서버는 `budget=mine` 을 받아도 예산 기준을 못 세울 수 있다(자산 미입력·복호화 실패·
 * 설정 오류). 그때 응답은 `budget.applied:false` + `reason` 이다. 화면이 그걸 삼키면
 * 사용자는 조건이 걸린 줄 알고 예산 밖 단지를 보게 된다 — 실패가 실패로 보이지 않는
 * 형태라 이 저장소가 가장 경계하는 종류다.
 */
describe("지도 예산 기준 — 서버가 뭐라고 했는지 화면이 말한다", () => {
  function complexItem(over: Partial<ComplexItem> & { id: number; name: string }): ComplexItem {
    return {
      point: [126.978, 37.5665],
      households: 500,
      built_year: 2005,
      recent_price_krw: 700_000_000,
      price_as_of: "2026-06-30",
      price_confidence: "estimated",
      active_listings: 0,
      over_budget: null,
      ...over,
    };
  }

  let kakao: KakaoStubHandle | null = null;

  /** 서버 원문(`routes.py::_BUDGET_NO_PROFILE`). 화면은 이 문장을 지어내지 않는다. */
  const NO_PROFILE_REASON =
    "자산 정보가 없어 예산 기준을 세우지 못했습니다 — 내 정보에서 보유 현금·연소득을 " +
    "입력하거나 희망 매매가를 정하면 예산 초과 여부를 표시합니다.";

  function mount(res: MapResponse) {
    kakao = installKakaoStub();
    vi.spyOn(api, "getProfile").mockResolvedValue(PROFILE);
    vi.spyOn(api, "getPreferences").mockResolvedValue(PREFS);
    vi.spyOn(api, "affordability").mockResolvedValue(AFFORD);
    return vi.spyOn(api, "mapComplexes").mockResolvedValue(res);
  }

  afterEach(() => {
    kakao?.restore();
    kakao = null;
    forgetCamera();
  });

  it("`applied:false` 로 오면 **서버가 준 사유를 그대로** 보여준다", async () => {
    mount({
      level: "complex",
      items: [complexItem({ id: 1, name: "가나아파트" })],
      note: "",
      budget: { applied: false, basis: null, reason: NO_PROFILE_REASON },
    });
    render(<Authenticated />);
    await screen.findByText("가나아파트");

    // 사유를 요약하거나 "오류가 발생했습니다"로 바꾸지 않는다
    expect(await screen.findByText(/자산 정보가 없어 예산 기준을 세우지 못했습니다/)).toBeTruthy();
    // 그리고 **그동안 배지가 안 뜬다는 사실**까지 말한다 (CR38-1).
    // 판정은 서버가 하므로, 못 세운 동안에는 초과 표시가 아예 없다 — 말하지 않으면
    // 사용자는 "예산 안이라서 안 뜨는구나"로 읽는다.
    expect(screen.getByText(/예산 초과 표시가 뜨지 않습니다/)).toBeTruthy();
  });

  it("군집(줌아웃) 응답에서도 같은 안내가 뜬다 — 조건이 사라진 게 아니다", async () => {
    mount({
      level: "cluster",
      items: [
        { region_code: "1168000000", count: 342, center: [127.047, 37.517], median_price_krw: null },
      ],
      budget: { applied: false, basis: null, reason: NO_PROFILE_REASON },
    });
    render(<Authenticated />);

    expect(await screen.findByText(/자산 정보가 없어 예산 기준을 세우지 못했습니다/)).toBeTruthy();
  });

  it("**희망가로 걸릴 줄 알았는데 한도로 걸렸으면** 알려준다 (basis 불일치)", async () => {
    vi.spyOn(api, "getPreferences").mockResolvedValue({
      ...PREFS,
      prefer: { ...PREFS.prefer, target_price_krw: 700_000_000 },
    });
    kakao = installKakaoStub();
    vi.spyOn(api, "getProfile").mockResolvedValue(PROFILE);
    vi.spyOn(api, "affordability").mockResolvedValue(AFFORD);
    vi.spyOn(api, "mapComplexes").mockResolvedValue({
      level: "complex",
      items: [complexItem({ id: 1, name: "가나아파트" })],
      note: "",
      // 화면은 희망가 7억으로 표시하는데 서버는 한도(8.5억)로 판정했다
      budget: { applied: true, basis: "max_purchase", reason: null },
    });

    render(<Authenticated />);
    await screen.findByText("가나아파트");

    expect(await screen.findByText(/자산으로 계산한 한도 기준으로 판정했고/)).toBeTruthy();
    expect(screen.getByText(/다시 저장/)).toBeTruthy();
  });

  it("기준이 같으면 아무 말도 하지 않는다(늘 뜨는 안내는 아무도 안 읽는다)", async () => {
    mount({
      level: "complex",
      items: [complexItem({ id: 1, name: "가나아파트" })],
      note: "",
      budget: { applied: true, basis: "max_purchase", reason: null },
    });
    render(<Authenticated />);
    await screen.findByText("가나아파트");

    expect(screen.queryByText(/예산 초과 표시가 적용되지 않았습니다/)).toBeNull();
    expect(screen.queryByText(/기준으로 판정했고/)).toBeNull();
  });

  it("서버가 `budget` 블록을 안 주면(구버전) **아무 주장도 하지 않는다**", async () => {
    mount({
      level: "complex",
      items: [complexItem({ id: 1, name: "가나아파트" })],
      note: "",
    });
    render(<Authenticated />);
    await screen.findByText("가나아파트");

    // "적용 안 됨"이라고 말하지 않는다 — 서버가 말하지 않은 것과 못 세운 것은 다르다
    expect(screen.queryByText(/적용되지 않았습니다/)).toBeNull();
  });

  /**
   * `purpose` — 지도와 자금계획이 **같은 가정**을 쓰는가.
   * 안 보내면 서버는 live 로 계산하는데 자금 패널이 invest 로 계산하고 있으면
   * 같은 단지가 "지도: 초과 / 자금: 가능"이 된다(한도 자체가 다르다).
   */
  it("지도 조회에 `purpose` 를 싣고, 자금계획과 **같은 값**을 쓴다", async () => {
    const mapSpy = mount({
      level: "complex",
      items: [complexItem({ id: 1, name: "가나아파트" })],
      note: "",
      budget: { applied: true, basis: "max_purchase", reason: null },
    });
    render(<Authenticated />);
    await screen.findByText("가나아파트");

    expect(mapSpy).toHaveBeenCalled();
    const mapArgs = mapSpy.mock.calls.at(-1)![0];
    expect(mapArgs.purpose).toBe("live");

    // 그리고 자금계획이 쓴 값과 같아야 한다 — 두 화면이 다른 한도로 서면 안 된다
    const affordSpy = vi.mocked(api.affordability);
    await waitFor(() => expect(affordSpy).toHaveBeenCalled());
    expect(affordSpy.mock.calls.at(-1)![0]?.purpose).toBe(mapArgs.purpose);
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

/**
 * FE-4 — 지도 칩과 추천이 **같은 조건**으로 돌아야 한다.
 *
 * 서버는 조건 필드가 없으면 저장된 내 조건을 폴백으로 쓴다. 그래서 "안 보냄"은
 * "끔"이 아니다 — 칩을 껐다는 사실을 명시적으로 보내지 않으면 지도만 풀리고
 * 추천은 계속 걸러진다. 아래 테스트가 그 배선을 고정한다.
 */
describe("조건 칩이 추천까지 닿는다", () => {
  const PREFS_AREA: Preferences = {
    prefer: { area_min_m2: 59, area_max_m2: 84, target_price_krw: 900_000_000 },
    avoid: {},
    weights: {},
  };

  function mount(prefs: Preferences = PREFS_AREA) {
    installKakaoStub();
    vi.spyOn(api, "getProfile").mockResolvedValue(PROFILE);
    vi.spyOn(api, "getPreferences").mockResolvedValue(prefs);
    vi.spyOn(api, "affordability").mockResolvedValue(AFFORD);
    vi.spyOn(api, "mapComplexes").mockResolvedValue({ level: "complex", items: [], note: "" });
    vi.spyOn(api, "recommendation").mockResolvedValue({
      job_id: "rec_1",
      status: "done",
      items: [],
    });
    return {
      user: userEvent.setup(),
      create: vi
        .spyOn(api, "createRecommendation")
        .mockResolvedValue({ job_id: "rec_1", status: "queued" }),
    };
  }

  afterEach(() => forgetCamera());

  it("칩이 켜져 있으면 use_saved_conditions 를 보내지 않는다(저장본 폴백 = 예전 동작)", async () => {
    const { user, create } = mount();
    render(<Authenticated />);

    await user.click(await screen.findByRole("tab", { name: "AI 추천" }));
    await user.click(screen.getByRole("button", { name: "AI 추천 실행" }));

    await waitFor(() => expect(create).toHaveBeenCalled());
    expect("use_saved_conditions" in create.mock.calls[0][0]).toBe(false);
  });

  it("면적 칩을 끄면 use_saved_conditions:false 가 나간다 — 안 보내면 추천만 계속 걸러진다", async () => {
    const { user, create } = mount();
    render(<Authenticated />);

    // 지도 칩을 끈다(면적·연식은 같은 스위치다)
    await user.click(await screen.findByRole("button", { name: "면적 59~84㎡" }));
    await user.click(screen.getByRole("tab", { name: "AI 추천" }));
    await user.click(screen.getByRole("button", { name: "AI 추천 실행" }));

    await waitFor(() => expect(create).toHaveBeenCalled());
    // null·생략이 아니라 **명시적 false** 여야 서버가 저장본을 무시한다
    expect(create.mock.calls[0][0].use_saved_conditions).toBe(false);
  });

  it("칩을 꺼도 희망 매매가는 살아 있다 — 예산까지 조용히 바뀌면 더 나쁜 사고다", async () => {
    // use_saved_conditions:false 는 저장된 target_price_krw 폴백도 죽인다.
    // 그래서 희망가는 요청에 **명시적으로** 실려야 한다.
    const { user, create } = mount();
    render(<Authenticated />);

    await user.click(await screen.findByRole("button", { name: "면적 59~84㎡" }));
    await user.click(screen.getByRole("tab", { name: "AI 추천" }));
    await user.click(screen.getByRole("button", { name: "AI 추천 실행" }));

    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0][0].budget_override_krw).toBe(900_000_000);
  });

  it("칩이 없는 조건(최소 세대수)은 칩을 꺼도 함께 죽지 않는다", async () => {
    const { user, create } = mount({
      prefer: { area_min_m2: 59, min_households: 1000 },
      avoid: {},
      weights: {},
    });
    render(<Authenticated />);

    await user.click(await screen.findByRole("button", { name: "면적 59㎡ 이상" }));
    await user.click(screen.getByRole("tab", { name: "AI 추천" }));
    await user.click(screen.getByRole("button", { name: "AI 추천 실행" }));

    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0][0]).toMatchObject({
      use_saved_conditions: false,
      min_households: 1000,
    });
  });

  it("결과 옆에 '어떤 조건으로 돌았는지'가 남는다 — 껐다는 사실까지", async () => {
    const { user } = mount();
    render(<Authenticated />);

    await user.click(await screen.findByRole("button", { name: "면적 59~84㎡" }));
    await user.click(screen.getByRole("tab", { name: "AI 추천" }));
    await user.click(screen.getByRole("button", { name: "AI 추천 실행" }));

    expect(await screen.findByText("이 결과에 적용된 조건")).toBeTruthy();
    expect(screen.getByText("꺼 둔 조건")).toBeTruthy();
    expect(screen.getByText(/전용 59~84㎡ — 지도와 추천 모두 적용하지 않았습니다/)).toBeTruthy();
  });
});
