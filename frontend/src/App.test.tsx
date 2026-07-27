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

  it("지도 조회 상한도 희망가다 — 추천에만 반영되면 두 화면이 다른 예산을 말한다", async () => {
    mount();
    render(<Authenticated />);

    await waitFor(() =>
      expect(vi.mocked(api.mapComplexes).mock.calls.at(-1)?.[0].max_price_krw).toBe(TARGET),
    );
    // 칩도 같은 사실을 말한다(한도 8.5억이 아니라 내가 정한 9억)
    expect(screen.getByRole("button", { name: "희망가 9.00억 이하" })).toBeTruthy();
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
    expect(await screen.findByRole("button", { name: "내 예산 8.50억 기준" })).toBeTruthy();

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

  it("고른 단지의 가격이 `/affordability` 로 나간다", async () => {
    const user = mount([complexItem({ id: 7, name: "가나아파트" })]);
    render(<Authenticated />);

    await user.click(await screen.findByText("가나아파트"));

    await waitFor(
      () =>
        expect(vi.mocked(api.affordability).mock.calls.at(-1)?.[0]).toMatchObject({
          target_price_krw: 1_000_000_000,
        }),
      { timeout: 3000 },
    );
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
          target_price_krw: 1_100_000_000,
        }),
      { timeout: 3000 },
    );
    // 클릭 2회에 요청 2회가 아니라 1회 — 중간 값(9억)은 요청되지 않는다
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

  it("시세를 모르는 단지는 계산하지 않고 그 사실을 말한다", async () => {
    const user = mount([
      complexItem({
        id: 9,
        name: "미상아파트",
        recent_price_krw: null,
        price_confidence: "unknown",
      }),
    ]);
    render(<Authenticated />);

    await user.click(await screen.findByText("미상아파트"));
    await user.click(screen.getByRole("button", { name: /내 자금/ }));

    expect(await screen.findByText(/최근 실거래 근거가 없어/)).toBeTruthy();
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

  /** 예산(8.5억) 안팎 · 세대수 있음/없음이 섞인 현실적인 목록 */
  const ITEMS: ComplexItem[] = [
    complexItem({ id: 1, name: "대단지아파트", households: 1500, recent_price_krw: 700_000_000 }),
    complexItem({ id: 2, name: "비싼아파트", households: 800, recent_price_krw: 1_200_000_000 }),
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
      complexItem({ id: 2, name: "비싼아파트", recent_price_krw: 1_200_000_000 }),
    ]);
    render(<Authenticated />);

    await screen.findByText("비싼아파트");
    await user.click(screen.getByRole("switch", { name: /예산 내/ }));

    expect(screen.getByText(/필터에 걸려 1건이 모두 가려졌습니다/)).toBeTruthy();
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
