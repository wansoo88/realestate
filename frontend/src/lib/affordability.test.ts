/**
 * 희망 매매가 · 자금계획의 **순수 규칙**.
 *
 * 여기서 가장 중요한 성질 하나: **한도를 넘는 값을 막지 않는다.**
 * 막는 순간 "얼마를 더 모아야 하나"라는 질문이 화면에서 사라진다 — 이 기능의 존재 이유다.
 */
import { describe, expect, it } from "vitest";
import type { AffordabilityPlan } from "../api/client";
import {
  TARGET_ABS_MAX_KRW,
  TARGET_MIN_KRW,
  TARGET_STEP_KRW,
  clampToRange,
  normalizeTargetPrice,
  planOverLimit,
  planOverLimitKrw,
  readTargetPrice,
  targetPriceRange,
  usablePlan,
  withTargetPrice,
} from "./affordability";

const LIMIT = 850_000_000; // 8.5억

describe("targetPriceRange", () => {
  it("한도보다 **높은 값도 고를 수 있게** 상한을 잡는다", () => {
    const r = targetPriceRange(LIMIT);
    expect(r.max).toBeGreaterThan(LIMIT);
    expect(r.limitKrw).toBe(LIMIT);
  });

  it("눈금은 500만원 배수라 억 단위가 깔끔하게 떨어진다", () => {
    const r = targetPriceRange(LIMIT);
    expect(r.step).toBe(TARGET_STEP_KRW);
    expect(r.max % TARGET_STEP_KRW).toBe(0);
    expect(r.min).toBe(TARGET_MIN_KRW);
  });

  it("한도를 모르면 한도 표시를 **비워 둔다**(기준값으로 그리지 않는다)", () => {
    const r = targetPriceRange(null);
    expect(r.limitKrw).toBeNull();
    expect(r.max).toBeGreaterThan(r.min); // 그래도 슬라이더는 동작한다
  });

  it("0·음수·NaN 한도는 '모름'과 같게 본다", () => {
    for (const bad of [0, -1, Number.NaN]) {
      expect(targetPriceRange(bad).limitKrw).toBeNull();
    }
  });
});

describe("clampToRange", () => {
  const range = targetPriceRange(LIMIT);

  it("범위 밖 값을 끝으로 맞추고 눈금에 붙인다", () => {
    expect(clampToRange(0, range)).toBe(range.min);
    expect(clampToRange(9_999_999_999, range)).toBe(range.max);
    expect(clampToRange(900_123_456, range) % TARGET_STEP_KRW).toBe(0);
  });

  it("한도를 넘는 값도 **범위 안이면 그대로 통과시킨다**", () => {
    const over = LIMIT + 100_000_000; // 9.5억
    expect(clampToRange(over, range)).toBe(over);
    expect(clampToRange(over, range)).toBeGreaterThan(LIMIT);
  });
});

describe("normalizeTargetPrice", () => {
  it("정하지 않음(null)과 0 을 구분한다", () => {
    expect(normalizeTargetPrice(null)).toBeNull();
    expect(normalizeTargetPrice(0)).toBeNull();
    expect(normalizeTargetPrice(undefined)).toBeNull();
  });

  it("음수·NaN·Infinity 는 값이 아니다", () => {
    expect(normalizeTargetPrice(-1)).toBeNull();
    expect(normalizeTargetPrice(Number.NaN)).toBeNull();
    expect(normalizeTargetPrice(Number.POSITIVE_INFINITY)).toBeNull();
  });

  it("오타 수준의 큰 값만 상한에서 자른다(한도 초과는 자르지 않는다)", () => {
    expect(normalizeTargetPrice(TARGET_ABS_MAX_KRW * 10)).toBe(TARGET_ABS_MAX_KRW);
    expect(normalizeTargetPrice(1_200_000_000)).toBe(1_200_000_000);
  });
});

describe("readTargetPrice / withTargetPrice", () => {
  it("저장값이 숫자가 아니면 없는 것으로 본다(서버 prefer 는 열린 dict 다)", () => {
    expect(readTargetPrice({ target_price_krw: "9억" } as never)).toBeNull();
    expect(readTargetPrice({ target_price_krw: -5 })).toBeNull();
    expect(readTargetPrice(null)).toBeNull();
    expect(readTargetPrice({})).toBeNull();
  });

  it("정상 값은 그대로 읽는다", () => {
    expect(readTargetPrice({ target_price_krw: 900_000_000 })).toBe(900_000_000);
  });

  it("지울 때는 **키 자체를 뺀다** — null 을 남기면 '0원을 원한다'와 섞인다", () => {
    const next = withTargetPrice({ target_price_krw: 900_000_000 }, null);
    expect("target_price_krw" in next).toBe(false);
  });

  it("담을 때 다른 선호를 건드리지 않는다", () => {
    const next = withTargetPrice({ built_after: 2010 }, 900_000_000);
    expect(next).toEqual({ built_after: 2010, target_price_krw: 900_000_000 });
  });
});

/* ── 서버 plan 검증 ─────────────────────────────────────────────────────── */

const PLAN: AffordabilityPlan = {
  target_price_krw: 900_000_000,
  total_needed_krw: 930_000_000,
  cost_breakdown: { tax: 25_000_000, brokerage: 4_000_000, etc: 1_000_000 },
  own_cash_krw: 300_000_000,
  shortfall_krw: 630_000_000,
  required_loan_krw: 630_000_000,
  loan_feasible: false,
  loan_limit_krw: 550_000_000,
  over_limit_krw: 80_000_000,
  binding_constraint: "DSR",
  monthly_payment_krw: 3_007_000,
  total_interest_krw: 452_000_000,
  terms: { annual_rate_pct: 4.0, years: 30 },
};

describe("usablePlan", () => {
  it("정상 plan 은 그대로 통과한다", () => {
    expect(usablePlan(PLAN)).toBe(PLAN);
  });

  it("필수 숫자가 빠지면 **렌더링하지 않는다**(NaN 을 화면에 흘리지 않는다)", () => {
    for (const key of [
      "total_needed_krw",
      "shortfall_krw",
      "required_loan_krw",
      "loan_limit_krw",
      "monthly_payment_krw",
    ] as const) {
      const broken = { ...PLAN, [key]: undefined } as unknown as AffordabilityPlan;
      expect(usablePlan(broken)).toBeNull();
    }
  });

  it("문자열 금액도 거부한다(서버가 바뀌어도 화면이 거짓말하지 않게)", () => {
    expect(usablePlan({ ...PLAN, monthly_payment_krw: "300만" } as never)).toBeNull();
  });

  it("null·undefined 는 '아직 없음'", () => {
    expect(usablePlan(null)).toBeNull();
    expect(usablePlan(undefined)).toBeNull();
  });
});

describe("planOverLimit", () => {
  it("서버 loan_feasible 이 정본이다", () => {
    expect(planOverLimit(PLAN)).toBe(true);
    expect(planOverLimit({ ...PLAN, loan_feasible: true })).toBe(false);
  });

  it("loan_feasible 이 없는 응답에서만 숫자로 되짚는다", () => {
    const noFlag = { ...PLAN, loan_feasible: undefined } as unknown as AffordabilityPlan;
    expect(planOverLimit(noFlag)).toBe(true);
    expect(planOverLimit({ ...noFlag, required_loan_krw: 100_000_000 })).toBe(false);
  });

  it("초과분은 서버 값을 쓰고, 없으면 계산해 보완한다", () => {
    expect(planOverLimitKrw(PLAN)).toBe(80_000_000);
    const noField = { ...PLAN, over_limit_krw: null };
    expect(planOverLimitKrw(noField)).toBe(80_000_000);
  });

  it("초과가 아니면 0 (음수를 보여주지 않는다)", () => {
    expect(planOverLimitKrw({ ...PLAN, over_limit_krw: null, required_loan_krw: 1 })).toBe(0);
  });
});
