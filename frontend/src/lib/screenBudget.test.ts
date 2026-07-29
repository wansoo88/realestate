/**
 * 서버 판정을 화면 항목으로 옮기는 자리 — **만들지 않는가 · 모름을 아님으로 접지 않는가**.
 *
 * 이 검사가 왜 화면 테스트가 아니라 여기 있나: `null` 과 `false` 는 화면에서 **똑같이
 * 보인다**(배지는 `=== true` 일 때만 붙는다). 즉 접혀도 픽셀이 안 바뀐다. 그래서 순수
 * 함수 층에서 값 자체를 못박는다. 관문을 **우회할 수 없게** 만드는 건 타입(브랜드)과
 * `apiContract.test.ts` 의 전수 검사가 맡는다.
 *
 * "면적이 섞인 지도에서 배지가 자금계획과 같은 말을 하는가"는 여기서 못 본다 —
 * 그건 `App.test.tsx` 의 3상태 회귀가 화면 끝에서 본다(CR38-1).
 */
import { describe, expect, it } from "vitest";
import type { ComplexItem } from "../api/client";
import { applyScreenBudget, serverBudgetVerdict } from "./screenBudget";

function item(over: Partial<ComplexItem> & { id: number }): ComplexItem {
  return {
    name: `단지${over.id}`,
    point: [127, 37.5],
    households: 500,
    built_year: 2005,
    recent_price_krw: 800_000_000,
    price_as_of: "2026-06-30",
    price_confidence: "estimated",
    active_listings: 0,
    over_budget: null,
    ...over,
  };
}

describe("serverBudgetVerdict — 3값을 3값으로 옮긴다", () => {
  it("true → over · false → within · **null → unknown**", () => {
    expect(serverBudgetVerdict(true)).toBe("over");
    expect(serverBudgetVerdict(false)).toBe("within");
    expect(serverBudgetVerdict(null)).toBe("unknown");
    // 세 값이 서로 다르다는 것 자체가 계약이다(둘로 접으면 여기서 걸린다)
    expect(serverBudgetVerdict(null)).not.toBe("within");
  });

  it("필드가 아예 없어도(구버전 응답) '예산 내'라고 말하지 않는다", () => {
    expect(serverBudgetVerdict(undefined)).toBe("unknown");
  });
});

describe("applyScreenBudget — 서버 판정을 옮긴다(다시 만들지 않는다)", () => {
  it("서버 값을 **그대로** 싣는다 — 가격·예산으로 다시 계산하지 않는다", () => {
    // 가격만 보면 셋 다 같은 값이지만 서버 판정은 다르다(면적별 상한이 다르기 때문).
    // 화면이 다시 판정하면 셋이 같아져 버린다 — 그 순간 이 단언이 죽는다.
    const rows = applyScreenBudget(
      [
        item({ id: 1, recent_price_krw: 1_025_570_000, over_budget: false }),
        item({ id: 2, recent_price_krw: 1_025_570_000, over_budget: true }),
        item({ id: 3, recent_price_krw: 1_025_570_000, over_budget: null }),
      ],
      true,
    );
    expect(rows.map((r) => r.over_budget)).toEqual([false, true, null]);
  });

  it("서버가 판정 못 한 항목은 **null** 이다 — `false`(예산 안)가 아니다", () => {
    const [unknown] = applyScreenBudget([item({ id: 1, over_budget: null })], true);
    expect(unknown.over_budget).toBeNull();
    expect(unknown.over_budget).not.toBe(false); // 접히면 여기서 죽는다
  });

  it("표시를 끄면 전부 **null** 이다(false 로 접지 않는다) — 재조회를 기다리지 않는다", () => {
    const rows = applyScreenBudget(
      [
        item({ id: 1, over_budget: true }),
        item({ id: 2, over_budget: false }),
      ],
      false,
    );
    expect(rows.map((r) => r.over_budget)).toEqual([null, null]);
  });

  it("나머지 필드는 그대로 둔다(원본을 변형하지 않는다)", () => {
    const src = item({ id: 7, name: "가나아파트", over_budget: true });
    const [row] = applyScreenBudget([src], false);
    expect(row.id).toBe(7);
    expect(row.name).toBe("가나아파트");
    expect(src.over_budget).toBe(true); // 입력은 건드리지 않았다
  });

  it("브랜드는 **런타임에 존재하지 않는다** — 직렬화·DOM 어디에도 안 샌다", () => {
    const [row] = applyScreenBudget([item({ id: 1 })], true);
    expect(Object.getOwnPropertySymbols(row)).toEqual([]);
    expect(Object.keys(row).sort()).toEqual(Object.keys(item({ id: 1 })).sort());
  });
});
