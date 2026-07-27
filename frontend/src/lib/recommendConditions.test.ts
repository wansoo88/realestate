/**
 * FE-4 — **"안 보냄"과 "끔"은 다른 뜻이다.**
 *
 * 서버는 조건 필드가 없으면 저장된 내 조건을 폴백으로 쓴다. 그래서 화면이 칩을 껐다는
 * 사실을 **명시적으로** 보내지 않으면, 지도만 필터가 풀리고 추천은 계속 걸러진다.
 * 아래 테스트가 그 한 가지를 못박는다.
 */
import { describe, expect, it } from "vitest";
import type { MapFilterState } from "./mapFilters";
import { conditionFields, conditionPlan, conditionText } from "./recommendConditions";

function state(over: Partial<MapFilterState> = {}): MapFilterState {
  return {
    budgetKrw: 850_000_000,
    budgetApplied: true,
    targetPriceKrw: null,
    prefer: { area_min_m2: 59, area_max_m2: 84, built_after: 2010 },
    preferApplied: true,
    ...over,
  };
}

describe("추천 요청 조건 — 끄는 방법이 있어야 한다", () => {
  it("칩이 켜져 있으면 아무것도 덧붙이지 않는다(저장본 폴백 = 예전 동작)", () => {
    const f = conditionFields(state());
    expect("use_saved_conditions" in f).toBe(false);
  });

  it("칩을 끄면 use_saved_conditions:false 가 나간다 — 이게 없으면 추천만 계속 걸러진다", () => {
    const f = conditionFields(state({ preferApplied: false }));
    expect(f.use_saved_conditions).toBe(false);
  });

  it("끄더라도 희망 매매가는 살아 있다 — 예산까지 함께 꺼지면 다른 사고가 된다", () => {
    // use_saved_conditions:false 는 저장된 target_price_krw 폴백도 함께 죽인다.
    // 그래서 희망가는 **항상** 요청에 명시된다(그러지 않으면 예산이 조용히 한도로 바뀐다).
    const f = conditionFields(state({ preferApplied: false, targetPriceKrw: 900_000_000 }));
    expect(f.budget_override_krw).toBe(900_000_000);
  });

  it("희망가가 없으면 null 이다 — 0 을 보내면 서버가 '0원 예산'으로 읽는다", () => {
    expect(conditionFields(state()).budget_override_krw).toBeNull();
    expect(conditionFields(state({ targetPriceKrw: 0 })).budget_override_krw).toBeNull();
  });

  it("칩이 없는 조건(최소 세대수)은 칩을 꺼도 살아남는다 — 칩이 말하지 않은 것을 끄지 않는다", () => {
    const f = conditionFields(
      state({ preferApplied: false, prefer: { min_households: 1000, area_min_m2: 59 } }),
    );
    expect(f.use_saved_conditions).toBe(false);
    expect(f.min_households).toBe(1000);
  });

  it("0 세대는 조건이 아니다(실어 보내지 않는다)", () => {
    const f = conditionFields(state({ preferApplied: false, prefer: { min_households: 0 } }));
    expect("min_households" in f).toBe(false);
  });
});

describe("이 결과가 어떤 조건으로 나왔나", () => {
  it("켜진 조건을 그대로 적는다", () => {
    const plan = conditionPlan(state());
    expect(conditionText(plan.on)).toBe("내 예산 8.50억 이내 · 전용 59~84㎡ · 2010년 이후 준공");
    expect(plan.off).toHaveLength(0);
  });

  it("희망가를 정했으면 '내 예산'이 아니라 희망가라고 말한다(다른 숫자다)", () => {
    const plan = conditionPlan(state({ targetPriceKrw: 900_000_000 }));
    expect(conditionText(plan.on)).toContain("희망가 9.00억 이하");
    expect(conditionText(plan.on)).not.toContain("내 예산");
  });

  it("꺼 둔 조건은 **사라지지 않고** 꺼졌다고 적힌다(모름을 아님으로 접지 않는다)", () => {
    const plan = conditionPlan(state({ preferApplied: false }));
    expect(conditionText(plan.on)).toBe("내 예산 8.50억 이내");
    expect(conditionText(plan.off)).toBe("전용 59~84㎡ · 2010년 이후 준공");
  });

  it("예산 칩을 꺼도 추천은 예산 안에서만 돈다 — 지도와 달라진 그 사실을 말한다", () => {
    // 못 사는 집은 취향이 아니라 후보 밖이다(서버가 실구매 가능 금액으로 자른다).
    // 지도만 풀리므로 "지도엔 보이는데 추천엔 없는 단지"가 생긴다.
    const plan = conditionPlan(state({ budgetApplied: false }));
    expect(plan.on.find((c) => c.id === "budget")?.side).toBe("rec_only");
    expect(plan.diverged).toBe(true);
  });

  it("최소 세대수는 지도에 없는 조건이라 항상 추천에만 걸린다", () => {
    const plan = conditionPlan(state({ prefer: { min_households: 1000 } }));
    expect(plan.on.find((c) => c.id === "households")).toMatchObject({
      label: "1,000세대 이상",
      side: "rec_only",
    });
    expect(plan.diverged).toBe(true);
  });

  it("지도와 추천이 같은 조건으로 돌면 다르다고 떠들지 않는다", () => {
    expect(conditionPlan(state()).diverged).toBe(false);
  });

  it("걸린 조건이 없으면 null — 빈 문자열로 자리만 차지하지 않는다", () => {
    expect(conditionText([])).toBeNull();
  });

  /**
   * 요청과 표시가 **같은 판단**에서 나와야 한다. 갈라지면 화면이
   * "면적 조건 없이 분석했습니다"라고 말하는 동안 서버는 면적으로 거른다.
   */
  it("표시와 요청이 어긋나지 않는다 — 꺼진 조건은 요청에서도 꺼져 있다", () => {
    const off = state({ preferApplied: false });
    expect(conditionPlan(off).off.length).toBeGreaterThan(0);
    expect(conditionFields(off).use_saved_conditions).toBe(false);

    const on = state();
    expect(conditionPlan(on).off).toHaveLength(0);
    expect("use_saved_conditions" in conditionFields(on)).toBe(false);
  });
});
