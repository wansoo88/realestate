import { describe, expect, it } from "vitest";
import { DEFAULT_WEIGHTS, normalizeWeights } from "./preferences";

describe("normalizeWeights", () => {
  it("합이 1 이 되게 맞춘다(사용자에게 100 맞추기를 시키지 않는다)", () => {
    const w = normalizeWeights({ price: 50, location: 25, value: 15, risk: 10 });
    expect(w.price).toBeCloseTo(0.5, 4);
    const sum = w.price + w.location + w.value + w.risk;
    expect(sum).toBeCloseTo(1, 3);
  });

  it("전부 0 이면 기본값으로 되돌린다(0 나눗셈·무의미한 가중치 방지)", () => {
    expect(normalizeWeights({ price: 0, location: 0, value: 0, risk: 0 })).toEqual(DEFAULT_WEIGHTS);
    expect(normalizeWeights(undefined)).toEqual(DEFAULT_WEIGHTS);
  });

  it("음수·NaN 은 0 으로 본다", () => {
    const w = normalizeWeights({ price: -5, location: Number.NaN, value: 1, risk: 1 });
    expect(w.price).toBe(0);
    expect(w.location).toBe(0);
    expect(w.value).toBeCloseTo(0.5, 4);
  });
});
