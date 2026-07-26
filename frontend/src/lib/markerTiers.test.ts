/**
 * 줌 단계 · 밀집 강등 테스트.
 *
 * 여기서 못박는 것은 "예쁘게 보인다"가 아니라 **경계값**이다. 임계 ±1 에서 단계가 갈리는지,
 * 그리고 강등에 두는 예외(선택·추천·hover)가 실제로 예외로 동작하는지.
 */
import { describe, expect, it } from "vitest";
import {
  DENSITY_LIMIT,
  DETAIL_ZOOM,
  baseTier,
  densityNotice,
  tierFor,
} from "./markerTiers";

describe("baseTier — 줌 단계", () => {
  it("중간 줌은 가격만 압축해서 보여준다", () => {
    expect(baseTier(14, 20)).toBe("price");
    expect(baseTier(DETAIL_ZOOM - 1, 20)).toBe("price");
  });

  it("근접 줌부터 단지명을 함께 보여준다", () => {
    expect(baseTier(DETAIL_ZOOM, 20)).toBe("detail");
    expect(baseTier(18, 1)).toBe("detail");
  });
});

describe("baseTier — 밀집 강등", () => {
  it("임계 이하면 pill 을 유지한다", () => {
    expect(baseTier(15, DENSITY_LIMIT)).toBe("price");
  });

  it("임계를 넘으면 점으로 강등한다", () => {
    expect(baseTier(15, DENSITY_LIMIT + 1)).toBe("dot");
  });

  it("밀집은 줌보다 우선한다 — 확대해도 빽빽하면 점이다", () => {
    // pill 끼리 서로를 가리면 '표시했지만 읽을 수 없는' 상태가 된다.
    expect(baseTier(19, DENSITY_LIMIT + 1)).toBe("dot");
  });
});

describe("tierFor — 강등의 예외 (확신의 농도)", () => {
  it("선택한 단지는 밀집이어도 상세로 승격한다", () => {
    expect(tierFor("dot", { selected: true })).toBe("detail");
  });

  it("추천 순위가 붙은 후보는 최소한 가격을 보여준다", () => {
    expect(tierFor("dot", { rank: 3 })).toBe("price");
  });

  it("목록에서 가리키는 중이면 그 마커의 가격을 되살린다", () => {
    expect(tierFor("dot", { hovered: true })).toBe("price");
  });

  it("추천·hover 라고 해서 상세로 **올리지는** 않는다(선택만 상세다)", () => {
    // 순위 마커까지 단지명을 달면 강조가 흩어져 '어디를 볼지'가 다시 사라진다.
    expect(tierFor("price", { rank: 1 })).toBe("price");
    expect(tierFor("price", { hovered: true })).toBe("price");
  });

  it("시세를 모르는 단지는 점으로 둔다 — pill 에 넣을 숫자가 없다", () => {
    expect(tierFor("price", { hasPrice: false })).toBe("dot");
    expect(tierFor("detail", { hasPrice: false })).toBe("dot");
  });

  it("시세를 몰라도 사용자가 고르면 상세로 연다(그때 '데이터 없음'을 읽게 한다)", () => {
    expect(tierFor("price", { hasPrice: false, selected: true })).toBe("detail");
  });

  it("강조가 없으면 화면 기본 단계를 그대로 따른다", () => {
    expect(tierFor("price", {})).toBe("price");
    expect(tierFor("detail")).toBe("detail");
    expect(tierFor("dot", {})).toBe("dot");
  });
});

describe("densityNotice — 숨긴 것을 밝힌다", () => {
  it("강등됐을 때만, 몇 곳인지와 되찾는 방법을 함께 말한다", () => {
    const msg = densityNotice("dot", 1234);
    expect(msg).toContain("1,234곳");
    expect(msg).toContain("확대");
    expect(msg).toContain("목록");
  });

  it("강등이 아니면 아무 말도 하지 않는다", () => {
    expect(densityNotice("price", 1234)).toBeNull();
    expect(densityNotice("detail", 1234)).toBeNull();
  });

  it("보여줄 단지가 없으면 말하지 않는다", () => {
    expect(densityNotice("dot", 0)).toBeNull();
  });
});
