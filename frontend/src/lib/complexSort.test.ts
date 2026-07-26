/**
 * 정렬 테스트 — 핵심은 **모르는 값(null)을 0 으로 취급하지 않는다**는 것이다.
 * 시세 미상 단지가 "가장 싼 집" 자리에 오면 그 목록은 사용자를 속인다.
 */
import { describe, expect, it } from "vitest";
import type { ComplexItem } from "../api/client";
import { SORT_OPTIONS, isSortKey, sortComplexes } from "./complexSort";

function item(over: Partial<ComplexItem> & { id: number }): ComplexItem {
  return {
    name: `단지${over.id}`,
    point: [127, 37.5],
    households: 500,
    built_year: 2005,
    recent_price_krw: 1_000_000_000,
    price_as_of: "2026-06-30",
    price_confidence: "estimated",
    active_listings: 0,
    over_budget: false,
    ...over,
  };
}

const ids = (list: ComplexItem[]) => list.map((i) => i.id);

describe("sortComplexes — 가격", () => {
  const list = [
    item({ id: 1, recent_price_krw: 1_400_000_000 }),
    item({ id: 2, recent_price_krw: 800_000_000 }),
    item({ id: 3, recent_price_krw: 1_100_000_000 }),
  ];

  it("낮은 순", () => {
    expect(ids(sortComplexes(list, "price_asc"))).toEqual([2, 3, 1]);
  });

  it("높은 순", () => {
    expect(ids(sortComplexes(list, "price_desc"))).toEqual([1, 3, 2]);
  });

  it("입력 배열을 뒤집지 않는다(리액트 상태 배열이 들어온다)", () => {
    const before = ids(list);
    sortComplexes(list, "price_desc");
    expect(ids(list)).toEqual(before);
  });
});

describe("sortComplexes — 모르는 값은 0 이 아니다", () => {
  const withNulls = [
    item({ id: 1, recent_price_krw: null }),
    item({ id: 2, recent_price_krw: 900_000_000 }),
    item({ id: 3, recent_price_krw: null }),
    item({ id: 4, recent_price_krw: 700_000_000 }),
  ];

  it("가격 낮은 순에서도 시세 미상은 맨 뒤다(가장 싼 집이 아니다)", () => {
    expect(ids(sortComplexes(withNulls, "price_asc"))).toEqual([4, 2, 1, 3]);
  });

  it("가격 높은 순에서도 시세 미상은 맨 뒤다(방향이 바뀌어도 뒤)", () => {
    expect(ids(sortComplexes(withNulls, "price_desc"))).toEqual([2, 4, 1, 3]);
  });

  it("준공년도 미상도 맨 뒤다", () => {
    const list = [
      item({ id: 1, built_year: null }),
      item({ id: 2, built_year: 1998 }),
      item({ id: 3, built_year: 2021 }),
    ];
    expect(ids(sortComplexes(list, "built_desc"))).toEqual([3, 2, 1]);
  });

  it("세대수 미상도 맨 뒤다", () => {
    const list = [
      item({ id: 1, households: null }),
      item({ id: 2, households: 300 }),
      item({ id: 3, households: 2_000 }),
    ];
    expect(ids(sortComplexes(list, "households_desc"))).toEqual([3, 2, 1]);
  });
});

describe("sortComplexes — 추천 순(기본)", () => {
  const list = [item({ id: 1 }), item({ id: 2 }), item({ id: 3 }), item({ id: 4 })];

  it("추천 순위가 붙은 후보가 순위대로 앞에 온다", () => {
    expect(ids(sortComplexes(list, "default", { 3: 1, 1: 2 }))).toEqual([3, 1, 2, 4]);
  });

  it("순위가 없으면 서버 순서를 그대로 둔다 — 몰래 가격순으로 바꾸지 않는다", () => {
    const mixed = [
      item({ id: 1, recent_price_krw: 2_000_000_000 }),
      item({ id: 2, recent_price_krw: 500_000_000 }),
    ];
    expect(ids(sortComplexes(mixed, "default"))).toEqual([1, 2]);
  });

  it("순위 없는 단지끼리는 원래 순서가 유지된다(안정 정렬)", () => {
    expect(ids(sortComplexes(list, "default", { 4: 1 }))).toEqual([4, 1, 2, 3]);
  });
});

describe("isSortKey", () => {
  it("선택지에 있는 값만 통과시킨다(select 값은 문자열로 들어온다)", () => {
    expect(isSortKey("price_asc")).toBe(true);
    expect(isSortKey("가격")).toBe(false);
    expect(SORT_OPTIONS[0].key).toBe("default");
  });
});
