// @vitest-environment jsdom
/**
 * 내 매물 화면 — **없던 화면**(CR35-2). 추천 결과가 "‘내 매물’에서 직접 입력하시면 가격
 * 축이 반영됩니다"라고 안내하는데 그 화면이 없었다. 여기서 고정하는 것은 그 화면이
 * *존재한다*가 아니라, **거짓말을 만들지 않는다**는 성질 넷이다.
 *
 *  ① `problems` 를 보여준다 — 저장 성공(201)에도 실린다. 안 보이면 단위 실수가 그대로 통과한다.
 *  ② 출처 배지는 **서버 문자열 그대로** — 프론트가 만들면 어느 화면에선가 빠진다.
 *  ③ stale 은 "제외됨"이라고 말한다 — 반영된 것처럼 보이면 사용자는 왜 추천이 그대로인지 모른다.
 *  ④ 가격을 바꾸면 날짜도 함께 보낸다 — 안 그러면 옛 날짜에 새 가격이 붙는다.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiException, api, type UserListing, type UserListingList } from "../api/client";
import { useMyListings } from "../hooks/useMyListings";
// 목은 `src/test/fixtures.ts` 한 곳에서만 만든다 — 여기서 손으로 적으면 계약이 바뀌어도
// 이 파일만 초록으로 남는다(그게 2026-07-29 사고였다).
import {
  LISTING_ELIGIBILITY_NOTE,
  daysAgo,
  userListing,
  userListingItem,
  userListingList,
} from "../test/fixtures";
import { MyListingsScreen } from "./MyListingsScreen";

const COMPLEX = { id: 1234, name: "○○아파트" };

function listing(over: Partial<UserListing> = {}): UserListing {
  return userListing({ note: null, ...over });
}

function listResponse(items: UserListing[], over: Partial<UserListingList> = {}): UserListingList {
  return userListingList(items, over);
}

/** 훅 + 화면을 함께 건다 — 요청이 실제로 나가는지까지가 이 화면의 계약이다. */
function Host({ complex = COMPLEX }: { complex?: { id: number; name: string } | null }) {
  const listings = useMyListings(true, complex?.id ?? null);
  return <MyListingsScreen listings={listings} complex={complex} onClose={() => {}} />;
}

function mountList(items: UserListing[], over: Partial<UserListingList> = {}) {
  vi.spyOn(api, "listMyListings").mockResolvedValue(listResponse(items, over));
  return userEvent.setup();
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("빈 목록", () => {
  it("호가가 없으면 **가격 축이 빠진다**는 사실을 말한다", async () => {
    mountList([]);
    render(<Host />);

    expect(await screen.findByText(/아직 입력한 호가가 없습니다/)).toBeTruthy();
    expect(screen.getByText(/가격 축/)).toBeTruthy();
  });

  it("서버 고지(공공 데이터가 아니다)를 원문 그대로 싣는다", async () => {
    mountList([]);
    render(<Host />);

    expect(await screen.findByText(/공공 데이터가 아닙니다/)).toBeTruthy();
  });

  it("단지 문맥이 없으면 입력 폼을 열지 않고 가는 길을 알려 준다", async () => {
    mountList([]);
    render(<Host complex={null} />);

    expect(await screen.findByText(/먼저 단지를 고르세요/)).toBeTruthy();
    expect(screen.queryByRole("form", { name: /호가 적기/ })).toBeNull();
  });
});

describe("출처 — 서버 라벨을 그대로 쓴다", () => {
  it("`source_label` 문자열이 금액 옆에 그대로 붙는다", async () => {
    mountList([listing()]);
    const { container } = render(<Host />);

    const price = await waitFor(() => {
      const el = container.querySelector(".mlist__price");
      if (!el) throw new Error("금액이 아직 없다");
      return el as HTMLElement;
    });
    expect(price.textContent).toContain("14억 8,000");
    expect(within(price).getByText("사용자 입력")).toBeTruthy();
  });

  it("서버가 라벨을 바꾸면 화면도 바뀐다 — 프론트가 문자열을 만들지 않는다", async () => {
    mountList([listing({ source_label: "직접 입력(2026)" })]);
    const { container } = render(<Host />);

    await screen.findByText("직접 입력(2026)");
    // 프론트가 자체 라벨을 덧붙이지 않았는지: 서버 라벨 외의 출처 표기가 없어야 한다
    expect(container.textContent).not.toContain("사용자 입력");
  });

  it("공공 데이터(ComplexCard·Price)와 **같은 모양으로 그리지 않는다**", async () => {
    mountList([listing()]);
    const { container } = render(<Host />);

    await screen.findByText("사용자 입력");
    // 공공 시세가 쓰는 금액 클래스를 이 화면의 금액에 쓰지 않는다
    expect(container.querySelector(".card__price")).toBeNull();
    expect(container.querySelector(".price__value")).toBeNull();
    // 점선 테두리 = 색을 지워도 남는 "내가 적은 값" 단서
    expect(container.querySelector(".mlist__item")).not.toBeNull();
  });
});

describe("낡음 — 계산에서 빠졌다는 사실이 보여야 한다", () => {
  it("stale 은 '반영 제외'와 사유·갱신 동선을 함께 보인다", async () => {
    mountList([
      listing({
        staleness: "stale",
        age_days: 120,
        as_of: daysAgo(120),
        eligible_for_recommendation: false,
      }),
    ]);
    render(<Host />);

    expect(await screen.findByText(/낡아서 추천에서 제외됨/)).toBeTruthy();
    expect(screen.getByText("반영 제외")).toBeTruthy();
    expect(screen.getByText("120일 전 확인", { exact: false })).toBeTruthy();
    // 고치라고 보여주는 화면이다 — 갱신 버튼이 있어야 한다
    expect(screen.getByRole("button", { name: "갱신하기" })).toBeTruthy();
  });

  /** CR35-7 — 자격을 결과로 말하지 않는다. */
  it("fresh 는 '반영 가능'까지만 말하고, 남은 조건을 서버 고지로 함께 보인다", async () => {
    mountList([listing()]);
    const { container } = render(<Host />);

    expect(await screen.findByText("반영 가능")).toBeTruthy();
    expect(screen.getByText(/반영될 수 있습니다/)).toBeTruthy();
    // "반영됐습니다"라고 단정하는 문구가 화면 어디에도 없어야 한다
    expect(container.textContent).not.toContain("추천에 반영됨");
    // 자격이 답하지 못하는 절반은 서버 고지가 상시로 말한다
    expect(screen.getByText(LISTING_ELIGIBILITY_NOTE)).toBeTruthy();
  });

  /**
   * ★ 필드명이 바뀌었을 때의 실제 사고 모양. 서버가 값을 안 주면 화면은
   * "전부 반영 안 됨"이 아니라 **"모른다"** 라고 말해야 한다.
   */
  it("서버가 자격을 안 주면 '반영 여부 미상'이라고 말한다", async () => {
    const noField = { ...listing() } as Partial<UserListing>;
    delete noField.eligible_for_recommendation;
    mountList([noField as UserListing]);
    const { container } = render(<Host />);

    expect(await screen.findByText("반영 여부 미상")).toBeTruthy();
    expect(container.textContent).not.toContain("추천에서 제외됨");
  });

  it("요약이 '다 넣었는데 왜 추천이 안 바뀌지'의 절반에 답한다", async () => {
    mountList([
      listing({ id: 1 }),
      listing({ id: 2, staleness: "stale", eligible_for_recommendation: false }),
    ]);
    render(<Host />);

    expect(await screen.findByText(/총 2건 · 반영 가능 1건 · 낡음 1건/)).toBeTruthy();
  });
});

describe("등록 — problems 는 성공해도 보여준다", () => {
  it("201 과 함께 온 problems 를 화면에 싣는다", async () => {
    const user = mountList([]);
    const create = vi.spyOn(api, "createMyListing").mockResolvedValue(
      userListingItem(listing(), [
        "㎡당 174,179원입니다 — 금액 단위(억·만원)를 다시 확인해 주세요.",
        "같은 단지·면적·층·동으로 이미 1건 등록돼 있습니다(#12).",
      ]),
    );
    render(<Host />);

    await screen.findByLabelText("호가");
    await user.type(screen.getByLabelText("호가"), "148000");
    await user.type(screen.getByLabelText("전용면적 (㎡)"), "84.97");
    fireEvent.change(screen.getByLabelText("이 호가를 확인한 날짜"), {
      target: { value: daysAgo(1) },
    });
    await user.click(screen.getByRole("button", { name: "호가 추가" }));

    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0][0]).toMatchObject({
      complex_id: 1234,
      ask_price_krw: 1_480_000_000,
      area_m2: 84.97,
      as_of: daysAgo(1),
    });
    // 저장은 됐지만 조용히 넘기지 않는다
    expect(await screen.findByText(/저장했습니다 — 다만 확인해 주세요/)).toBeTruthy();
    expect(screen.getByText(/금액 단위\(억·만원\)를 다시 확인/)).toBeTruthy();
    expect(screen.getByText(/이미 1건 등록돼 있습니다/)).toBeTruthy();
  });

  it("확인 날짜는 **비어 있고**, 비운 채로는 저장되지 않는다", async () => {
    const user = mountList([]);
    const create = vi.spyOn(api, "createMyListing");
    render(<Host />);

    const asOf = (await screen.findByLabelText("이 호가를 확인한 날짜")) as HTMLInputElement;
    // 오늘 날짜를 미리 채우면 3주 전 호가가 오늘 값이 된다
    expect(asOf.value).toBe("");

    await user.type(screen.getByLabelText("호가"), "148000");
    await user.type(screen.getByLabelText("전용면적 (㎡)"), "84.97");
    await user.click(screen.getByRole("button", { name: "호가 추가" }));

    expect(create).not.toHaveBeenCalled();
    expect(await screen.findByText(/직접 확인한 날짜/)).toBeTruthy();
  });

  it("422 는 서버 문장을 그대로 보여준다", async () => {
    const user = mountList([]);
    vi.spyOn(api, "createMyListing").mockRejectedValue(
      new ApiException(422, {
        code: "INVALID_PARAM",
        message: "365일이 넘은 호가는 등록할 수 없습니다",
      }),
    );
    render(<Host />);

    await screen.findByLabelText("호가");
    await user.type(screen.getByLabelText("호가"), "148000");
    await user.type(screen.getByLabelText("전용면적 (㎡)"), "84.97");
    fireEvent.change(screen.getByLabelText("이 호가를 확인한 날짜"), {
      target: { value: daysAgo(2) },
    });
    await user.click(screen.getByRole("button", { name: "호가 추가" }));

    expect(await screen.findByText(/365일이 넘은 호가는 등록할 수 없습니다/)).toBeTruthy();
  });

  it("404(없는 단지·남의 매물)는 '권한 없음'으로 번역하지 않는다", async () => {
    const user = mountList([]);
    vi.spyOn(api, "createMyListing").mockRejectedValue(
      new ApiException(404, { code: "NOT_FOUND", message: "단지를 찾을 수 없습니다" }),
    );
    render(<Host />);

    await screen.findByLabelText("호가");
    await user.type(screen.getByLabelText("호가"), "148000");
    await user.type(screen.getByLabelText("전용면적 (㎡)"), "84.97");
    fireEvent.change(screen.getByLabelText("이 호가를 확인한 날짜"), {
      target: { value: daysAgo(1) },
    });
    await user.click(screen.getByRole("button", { name: "호가 추가" }));

    expect(await screen.findByText("단지를 찾을 수 없습니다")).toBeTruthy();
    expect(screen.queryByText(/권한/)).toBeNull();
  });
});

describe("수정 — 가격과 날짜는 분리될 수 없다", () => {
  it("가격을 바꾸면 날짜 칸이 비워지고, 그대로는 저장되지 않는다", async () => {
    const user = mountList([listing()]);
    const update = vi.spyOn(api, "updateMyListing");
    render(<Host />);

    await user.click(await screen.findByRole("button", { name: "수정" }));

    const asOf = (await screen.findByLabelText("이 호가를 확인한 날짜")) as HTMLInputElement;
    expect(asOf.value).toBe(listing().as_of); // 처음엔 저장된 날짜 그대로

    const price = screen.getByLabelText("호가");
    await user.clear(price);
    await user.type(price, "150000");

    // 가격을 건드리는 순간 날짜가 비워지고 이유를 말한다
    expect(asOf.value).toBe("");
    expect(screen.getByText(/가격을 바꾸셨습니다/)).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "수정 저장" }));
    expect(update).not.toHaveBeenCalled();
  });

  it("가격과 날짜를 함께 주면 PATCH 에 **둘 다** 실린다", async () => {
    const user = mountList([listing()]);
    const update = vi
      .spyOn(api, "updateMyListing")
      .mockResolvedValue(userListingItem(listing({ ask_price_krw: 1_500_000_000 })));
    render(<Host />);

    await user.click(await screen.findByRole("button", { name: "수정" }));
    const price = screen.getByLabelText("호가");
    await user.clear(price);
    await user.type(price, "150000");
    fireEvent.change(screen.getByLabelText("이 호가를 확인한 날짜"), {
      target: { value: daysAgo(0) },
    });
    await user.click(screen.getByRole("button", { name: "수정 저장" }));

    await waitFor(() => expect(update).toHaveBeenCalled());
    expect(update.mock.calls[0][1]).toEqual({
      ask_price_krw: 1_500_000_000,
      as_of: daysAgo(0),
    });
  });

  it("안 건드린 항목은 PATCH 에 키 자체가 없다(생략 = 안 건드림)", async () => {
    const user = mountList([listing()]);
    const update = vi
      .spyOn(api, "updateMyListing")
      .mockResolvedValue(userListingItem(listing({ apt_dong: null })));
    render(<Host />);

    await user.click(await screen.findByRole("button", { name: "수정" }));
    await user.clear(screen.getByLabelText(/^동/));
    await user.click(screen.getByRole("button", { name: "수정 저장" }));

    await waitFor(() => expect(update).toHaveBeenCalled());
    // 비운 것은 null(비우기), 안 건드린 것은 아예 없음
    expect(update.mock.calls[0][1]).toEqual({ apt_dong: null });
  });
});

describe("삭제 vs 추천에서만 빼기", () => {
  it("삭제는 한 번 더 묻는다 — 첫 클릭으로는 지워지지 않는다", async () => {
    const user = mountList([listing()]);
    const del = vi.spyOn(api, "deleteMyListing").mockResolvedValue(undefined);
    render(<Host />);

    await user.click(await screen.findByRole("button", { name: "삭제" }));
    expect(del).not.toHaveBeenCalled();
    // 되돌릴 수 없다는 사실과 **대안**을 같은 자리에서 말한다
    expect(screen.getByText(/되돌릴 수 없습니다/)).toBeTruthy();
    expect(screen.getByText(/추천에서만 빠집니다/)).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "영구 삭제" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith(7));
  });

  it("'거래됨'은 지우지 않고 상태만 바꾼다", async () => {
    const user = mountList([listing()]);
    const del = vi.spyOn(api, "deleteMyListing");
    const update = vi
      .spyOn(api, "updateMyListing")
      .mockResolvedValue(userListingItem(listing({ status: "traded" })));
    render(<Host />);

    await user.selectOptions(await screen.findByLabelText("7번 매물 상태"), "traded");

    await waitFor(() => expect(update).toHaveBeenCalledWith(7, { status: "traded" }));
    expect(del).not.toHaveBeenCalled();
  });
});

/* ─────────────────────────────────────────────────────────────────────────
 * CR35-7 · SR31-2 — 계약이 바뀌며 함께 온 것들
 * ───────────────────────────────────────────────────────────────────────── */

describe("저장 응답의 notes — '반영됐다'는 오해를 저장 직후에 막는다", () => {
  it("저장 결과의 고지를 렌더하되 목록 고지와 **중복해서 띄우지 않는다**", async () => {
    const user = mountList([]);
    vi.spyOn(api, "createMyListing").mockResolvedValue(userListingItem(listing()));
    render(<Host />);

    await screen.findByLabelText("호가");
    await user.type(screen.getByLabelText("호가"), "148000");
    await user.type(screen.getByLabelText("전용면적 (㎡)"), "84.97");
    fireEvent.change(screen.getByLabelText("이 호가를 확인한 날짜"), {
      target: { value: daysAgo(1) },
    });
    await user.click(screen.getByRole("button", { name: "호가 추가" }));

    // 저장 직후에도 "자격 ≠ 반영"이 화면에 있다. 다만 같은 문장이 두 번 뜨지는 않는다.
    await waitFor(() => expect(screen.getAllByText(LISTING_ELIGIBILITY_NOTE)).toHaveLength(1));
  });

  it("목록이 그 고지를 안 줘도 저장 응답의 고지는 살아남는다", async () => {
    // 목록 응답에서 고지가 빠진 상황(구버전·부분 배포)을 가정한다
    const user = mountList([], { notes: [] });
    vi.spyOn(api, "createMyListing").mockResolvedValue(userListingItem(listing()));
    render(<Host />);

    await screen.findByLabelText("호가");
    await user.type(screen.getByLabelText("호가"), "148000");
    await user.type(screen.getByLabelText("전용면적 (㎡)"), "84.97");
    fireEvent.change(screen.getByLabelText("이 호가를 확인한 날짜"), {
      target: { value: daysAgo(1) },
    });
    await user.click(screen.getByRole("button", { name: "호가 추가" }));

    expect(await screen.findByText(LISTING_ELIGIBILITY_NOTE)).toBeTruthy();
  });

  it("등록에 성공하면 폼을 비운다 — 방금 넣은 날짜·가격이 다음 매물에 붙지 않게", async () => {
    const user = mountList([]);
    vi.spyOn(api, "createMyListing").mockResolvedValue(userListingItem(listing()));
    render(<Host />);

    await screen.findByLabelText("호가");
    await user.type(screen.getByLabelText("호가"), "148000");
    await user.type(screen.getByLabelText("전용면적 (㎡)"), "84.97");
    fireEvent.change(screen.getByLabelText("이 호가를 확인한 날짜"), {
      target: { value: daysAgo(1) },
    });
    await user.click(screen.getByRole("button", { name: "호가 추가" }));

    await waitFor(() =>
      expect((screen.getByLabelText("이 호가를 확인한 날짜") as HTMLInputElement).value).toBe(""),
    );
    expect((screen.getByLabelText("호가") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("전용면적 (㎡)") as HTMLInputElement).value).toBe("");
  });
});

describe("상한(409) — 서버 문장을 그대로 보여준다", () => {
  it("200건을 넘기면 무엇을 하면 되는지까지 전한다", async () => {
    const user = mountList([]);
    vi.spyOn(api, "createMyListing").mockRejectedValue(
      new ApiException(409, {
        code: "LIMIT_REACHED",
        message:
          "등록할 수 있는 호가는 최대 200건입니다 (현재 200건). 팔렸거나 더 안 보는 " +
          "매물을 지우거나, 가격이 바뀐 것이면 새로 넣지 말고 수정(PATCH)하세요",
      }),
    );
    render(<Host />);

    await screen.findByLabelText("호가");
    await user.type(screen.getByLabelText("호가"), "148000");
    await user.type(screen.getByLabelText("전용면적 (㎡)"), "84.97");
    fireEvent.change(screen.getByLabelText("이 호가를 확인한 날짜"), {
      target: { value: daysAgo(1) },
    });
    await user.click(screen.getByRole("button", { name: "호가 추가" }));

    // 상한 값을 화면이 따로 적어 두지 않는다 — 서버 문장이 정본이다
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("최대 200건");
    expect(alert.textContent).toContain("현재 200건");
    expect(alert.textContent).toContain("수정");
  });
});
