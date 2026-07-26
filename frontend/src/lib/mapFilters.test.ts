/**
 * "내 조건이 지도에 반영되는가" — 이 제품이 지도 뷰어가 아니라는 증거.
 */
import { describe, expect, it } from "vitest";
import {
  buildMapQuery,
  effectiveBudgetKrw,
  filterChips,
  type MapFilterState,
} from "./mapFilters";

const BASE: MapFilterState = {
  budgetKrw: 850_000_000,
  budgetApplied: true,
  prefer: { area_min_m2: 59, area_max_m2: 85, built_after: 2010 },
  preferApplied: true,
};

describe("buildMapQuery", () => {
  it("예산과 선호를 그대로 서버 파라미터로 옮긴다", () => {
    expect(buildMapQuery("126.9,37.5,127.1,37.6", 15, BASE)).toEqual({
      bbox: "126.9,37.5,127.1,37.6",
      zoom: 15,
      max_price_krw: 850_000_000,
      area_min_m2: 59,
      area_max_m2: 85,
      built_after: 2010,
    });
  });

  it("예산 스위치를 끄면 예산이 **빠진다**(끄는 게 실제로 동작해야 한다)", () => {
    const q = buildMapQuery("1,2,3,4", 15, { ...BASE, budgetApplied: false });
    expect(q.max_price_krw).toBeUndefined();
    expect(q.area_min_m2).toBe(59); // 다른 필터는 그대로
  });

  it("선호 스위치를 끄면 면적·연식이 빠진다", () => {
    const q = buildMapQuery("1,2,3,4", 15, { ...BASE, preferApplied: false });
    expect(q.max_price_krw).toBe(850_000_000);
    expect(q.area_min_m2).toBeUndefined();
    expect(q.built_after).toBeUndefined();
  });

  it("예산을 모르면(null) 필터를 걸지 않는다 — 0원으로 좁혀 전멸시키지 않는다", () => {
    const q = buildMapQuery("1,2,3,4", 15, { ...BASE, budgetKrw: null });
    expect(q.max_price_krw).toBeUndefined();
  });
});

/**
 * 희망 매매가 — 사용자가 정한 상한. 추천(`budget_override_krw`)과 **같은 숫자**를 지도에도
 * 써야 "추천에는 뜨는데 지도엔 없는 단지"가 생기지 않는다.
 */
describe("희망 매매가가 지도 상한이 된다", () => {
  it("희망가가 있으면 한도 대신 희망가로 좁힌다", () => {
    const q = buildMapQuery("1,2,3,4", 15, { ...BASE, targetPriceKrw: 700_000_000 });
    expect(q.max_price_krw).toBe(700_000_000);
  });

  it("한도를 **넘겨 잡아도 그대로 쓴다** — 못 사는 집을 보는 게 이 기능의 목적이다", () => {
    const q = buildMapQuery("1,2,3,4", 15, { ...BASE, targetPriceKrw: 1_200_000_000 });
    expect(q.max_price_krw).toBe(1_200_000_000);
  });

  it("희망가가 없으면 예전대로 한도를 쓴다", () => {
    expect(effectiveBudgetKrw(BASE)).toBe(850_000_000);
    expect(effectiveBudgetKrw({ ...BASE, targetPriceKrw: null })).toBe(850_000_000);
    expect(effectiveBudgetKrw({ ...BASE, targetPriceKrw: 0 })).toBe(850_000_000);
  });

  it("예산 스위치를 끄면 희망가도 함께 빠진다(끄는 게 실제로 동작한다)", () => {
    const q = buildMapQuery("1,2,3,4", 15, {
      ...BASE,
      targetPriceKrw: 700_000_000,
      budgetApplied: false,
    });
    expect(q.max_price_krw).toBeUndefined();
  });

  it("칩이 '내 예산'이 아니라 '희망가'라고 말한다 — 둘은 다른 숫자다", () => {
    const chips = filterChips({ ...BASE, targetPriceKrw: 700_000_000 });
    const budget = chips.filter((c) => c.id === "budget");
    expect(budget).toHaveLength(1); // 예산 칩이 두 개로 늘지 않는다
    expect(budget[0].label).toBe("희망가 7.00억 이하");
  });
});

describe("filterChips — 무엇이 걸렸는지 보이게", () => {
  it("예산 칩에 실제 금액이 들어간다", () => {
    const chips = filterChips(BASE);
    const budget = chips.find((c) => c.id === "budget");
    // 표기는 lib/format 의 짧은 금액 규칙을 그대로 따른다(10억 미만은 소수 둘째자리).
    expect(budget?.label).toBe("내 예산 8.50억 기준");
    expect(budget?.active).toBe(true);
  });

  it("스위치를 끄면 칩은 남고 active 만 false — 사라지면 되켤 수 없다", () => {
    const chips = filterChips({ ...BASE, budgetApplied: false });
    expect(chips.find((c) => c.id === "budget")?.active).toBe(false);
  });

  it("값이 없는 조건은 칩을 만들지 않는다(끌 게 없는 스위치 금지)", () => {
    const chips = filterChips({
      budgetKrw: null,
      budgetApplied: true,
      prefer: {},
      preferApplied: true,
    });
    expect(chips).toEqual([]);
  });

  it("한쪽만 있는 면적 범위도 문장으로 말한다", () => {
    const chips = filterChips({ ...BASE, prefer: { area_min_m2: 59 } });
    expect(chips.find((c) => c.id === "area")?.label).toBe("면적 59㎡ 이상");
  });
});
