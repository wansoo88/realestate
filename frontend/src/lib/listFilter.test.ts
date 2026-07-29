/**
 * 목록 필터 — **숨긴 건 반드시 세어 돌려준다**를 못박는다.
 *
 * 필터가 항목을 조용히 지우면 사용자는 "왜 안 보이지?"가 되고, 그 순간 이 도구는
 * 신뢰를 잃는다. 그래서 이 모듈의 반환값에는 "몇 건을 왜 숨겼는가"가 항상 들어 있다.
 */
import { describe, expect, it } from "vitest";
import {
  budgetVerdict,
  filterList,
  missingFactLabels,
  unmeasurableTags,
  type FilterSource,
} from "./listFilter";
import type { TagFacts } from "./tags";

interface Row {
  name: string;
}

const BUDGET = 1_000_000_000; // 10억

/**
 * 판정은 **호출부가 실어 준다**(filterList 는 판정하지 않는다). 여기서는 추천 목록과
 * 같은 방식(금액 하나로 판정)으로 만들어 넣는다 — 지도는 서버 값을 싣는다.
 */
function src(
  name: string,
  priceKrw: number | null,
  facts: TagFacts = {},
  budgetKrw: number | null = BUDGET,
): FilterSource<Row> {
  return { item: { name }, budget: budgetVerdict(priceKrw, budgetKrw), facts };
}

const DEFAULT = { budgetOnly: false, tags: [], includeUnknownTag: false };

const names = (o: { entries: Array<{ item: Row }> }) => o.entries.map((e) => e.item.name);

describe("budgetVerdict", () => {
  it("예산 이하면 within, 초과면 over", () => {
    expect(budgetVerdict(900_000_000, BUDGET)).toBe("within");
    expect(budgetVerdict(BUDGET, BUDGET)).toBe("within"); // 경계는 예산 안
    expect(budgetVerdict(1_100_000_000, BUDGET)).toBe("over");
  });

  it("가격을 모르면 **예산 내가 아니다** — unknown 이다", () => {
    // 서버도 같은 규칙이다(api-spec §4: 가격 미상이면 `over_budget: null`).
    expect(budgetVerdict(null, BUDGET)).toBe("unknown");
    expect(budgetVerdict(undefined, BUDGET)).toBe("unknown");
    expect(budgetVerdict(0, BUDGET)).toBe("unknown");
  });

  it("예산을 모르면 아무것도 판정하지 않는다", () => {
    expect(budgetVerdict(900_000_000, null)).toBe("unknown");
    expect(budgetVerdict(900_000_000, 0)).toBe("unknown");
  });
});

/**
 * `filterList` 는 **판정하지 않는다** (CR38-1).
 *
 * 예전에는 이 모듈이 `가격 ≤ 예산` 을 직접 계산했고, 그 "예산"이 목록 전체에 한 숫자였다.
 * 지도처럼 면적이 섞인 목록에서는 그 하나가 틀린다(취득세 구간이 85㎡ 를 가로지른다).
 * 판정을 입력으로 받으면 목록마다 **판정한 쪽**(지도 = 서버, 추천 = 화면)이 정해진다.
 */
describe("판정은 입력이다 — 여기서 다시 계산하지 않는다", () => {
  it("같은 가격이라도 실어 준 판정이 다르면 다르게 센다", () => {
    // 지도의 실제 모습: 가격은 같은데 면적이 달라 서버 상한이 갈린 두 단지.
    const out = filterList(
      [
        { item: { name: "84㎡" }, budget: "within", facts: {} },
        { item: { name: "120㎡" }, budget: "over", facts: {} },
      ],
      DEFAULT,
    );
    expect(out.overBudget).toBe(1);
    expect(out.budgetUnknown).toBe(0);
  });

  it("판정 불가만 있으면 토글을 켤 수 없다(켜 봐야 빈 화면이다)", () => {
    const out = filterList(
      [
        { item: { name: "가" }, budget: "unknown", facts: {} },
        { item: { name: "나" }, budget: "unknown", facts: {} },
      ],
      { ...DEFAULT, budgetOnly: true },
    );
    expect(out.budgetKnown).toBe(false);
    expect(names(out)).toEqual(["가", "나"]);
    expect(out.hiddenBudgetUnknown).toBe(0);
  });
});

describe("예산 토글", () => {
  const rows = [
    src("싼집", 800_000_000),
    src("비싼집", 1_500_000_000),
    src("가격미상", null),
  ];

  it("끄면 전부 보이고, 초과·미상 건수는 사실로 돌려준다", () => {
    const out = filterList(rows, DEFAULT);
    expect(names(out)).toEqual(["싼집", "비싼집", "가격미상"]);
    expect(out.overBudget).toBe(1);
    expect(out.budgetUnknown).toBe(1);
    // 숨긴 게 없으므로 숨김 건수는 0 이다(사실과 숨김을 구분한다)
    expect(out.hiddenOverBudget).toBe(0);
    expect(out.hiddenBudgetUnknown).toBe(0);
  });

  it("켜면 예산 내만 남고, **몇 건을 숨겼는지** 함께 돌려준다", () => {
    const out = filterList(rows, { ...DEFAULT, budgetOnly: true });
    expect(names(out)).toEqual(["싼집"]);
    expect(out.hiddenOverBudget).toBe(1);
    expect(out.hiddenBudgetUnknown).toBe(1);
    expect(out.total).toBe(3);
  });

  it("판정 불가는 예산 내로 치지 않는다 — 다만 혼자 남으면 토글이 잠긴다", () => {
    // 판정된 항목이 하나도 없으면 토글을 켤 수 없다(켜면 전부 사라진다).
    const alone = filterList([src("가격미상", null)], { ...DEFAULT, budgetOnly: true });
    expect(alone.budgetKnown).toBe(false);
    expect(alone.entries).toHaveLength(1);

    // 판정된 항목이 섞여 있으면 초과와 **따로** 세어 숨긴다.
    const mixed = filterList([src("싼집", 800_000_000), src("가격미상", null)], {
      ...DEFAULT,
      budgetOnly: true,
    });
    expect(names(mixed)).toEqual(["싼집"]);
    expect(mixed.hiddenBudgetUnknown).toBe(1);
    expect(mixed.hiddenOverBudget).toBe(0);
  });

  it("예산을 모르면 토글이 켜져 있어도 아무것도 숨기지 않는다(빈 화면 방지)", () => {
    const unknownBudget = rows.map((r) => ({ ...r, budget: "unknown" as const }));
    const out = filterList(unknownBudget, { ...DEFAULT, budgetOnly: true });
    expect(names(out)).toEqual(["싼집", "비싼집", "가격미상"]);
    expect(out.budgetKnown).toBe(false);
    expect(out.hiddenOverBudget).toBe(0);
  });
});

describe("특성 칩", () => {
  const rows = [
    src("대단지역세권", 800_000_000, { households: 1500, stationDistanceM: 300 }),
    src("대단지만", 900_000_000, { households: 1200, stationDistanceM: 900 }),
    src("역세권만", 700_000_000, { households: 400, stationDistanceM: 200 }),
    src("세대수미상", 600_000_000, { households: null, stationDistanceM: 100 }),
  ];

  it("칩마다 해당 건수와 판정 불가 건수를 따로 센다", () => {
    const out = filterList(rows, DEFAULT);
    const large = out.chips.find((c) => c.id === "large_complex")!;
    expect(large.count).toBe(2);
    expect(large.unknown).toBe(1); // 세대수미상 — 0 건에 포함되지 않는다
    const station = out.chips.find((c) => c.id === "near_station")!;
    expect(station.count).toBe(3);
    expect(station.unknown).toBe(0);
  });

  it("해당 0건 칩도 목록에 남는다(없다는 것도 정보) — 다만 누를 수 없다", () => {
    const out = filterList(rows, DEFAULT);
    const redev = out.chips.find((c) => c.id === "redevelopment")!;
    expect(redev.count).toBe(0);
    expect(redev.disabled).toBe(true);
    expect(out.chips).toHaveLength(3); // 숨기지 않는다
  });

  it("칩 개수는 **예산 필터 적용 후** 기준이다(칩 숫자와 결과가 어긋나지 않게)", () => {
    const out = filterList(
      [
        src("싼대단지", 800_000_000, { households: 1500 }),
        src("비싼대단지", 5_000_000_000, { households: 2000 }),
      ],
      { ...DEFAULT, budgetOnly: true },
    );
    expect(out.chips.find((c) => c.id === "large_complex")!.count).toBe(1);
    expect(names(out)).toEqual(["싼대단지"]);
  });

  it("칩 하나를 고르면 그 특성만 남는다", () => {
    const out = filterList(rows, { ...DEFAULT, tags: ["large_complex"] });
    expect(names(out)).toEqual(["대단지역세권", "대단지만"]);
    expect(out.mode).toBe("single");
  });

  it("둘을 고르면 **교집합**이다(둘 다 만족하는 것만)", () => {
    const out = filterList(rows, { ...DEFAULT, tags: ["large_complex", "near_station"] });
    expect(names(out)).toEqual(["대단지역세권"]);
    expect(out.mode).toBe("intersection");
  });

  it("원래 순서를 유지한다 — 필터는 순위를 다시 매기지 않는다", () => {
    const out = filterList(rows, { ...DEFAULT, tags: ["near_station"] });
    expect(names(out)).toEqual(["대단지역세권", "역세권만", "세대수미상"]);
  });
});

describe("판정 불가를 아님으로 접지 않는다", () => {
  const rows = [
    src("확실한대단지", 800_000_000, { households: 1500 }),
    src("확실히아님", 800_000_000, { households: 300 }),
    src("세대수미상", 800_000_000, { households: null }),
  ];

  it("대단지 칩을 눌러도 세대수 미상은 '아님'으로 처리되지 않는다 — 따로 센다", () => {
    const out = filterList(rows, { ...DEFAULT, tags: ["large_complex"] });
    expect(names(out)).toEqual(["확실한대단지"]);
    // 확실히 아닌 1건은 그냥 빠진다. 판정 불가 1건은 **숫자로 남는다**.
    expect(out.hiddenTagUnknown).toBe(1);
  });

  it("함께 보기를 켜면 판정 불가 항목이 되살아나고, 무엇을 모르는지 표시된다", () => {
    const out = filterList(rows, {
      ...DEFAULT,
      tags: ["large_complex"],
      includeUnknownTag: true,
    });
    expect(names(out)).toEqual(["확실한대단지", "세대수미상"]);
    expect(out.shownTagUnknown).toBe(1);
    expect(out.hiddenTagUnknown).toBe(0);
    // 되살아난 항목에는 "무엇을 판정 못 했는지"가 붙는다 — 대단지인 척하지 않는다
    const revived = out.entries.find((e) => e.item.name === "세대수미상")!;
    expect(revived.unknownTags).toEqual(["large_complex"]);
    expect(revived.tags).toEqual([]);
  });

  it("교집합에서 하나라도 '아님'이면 판정 불가로 세지 않는다(확실히 제외)", () => {
    const out = filterList(
      [src("작고역세권", 800_000_000, { households: 100, stationDistanceM: null })],
      { ...DEFAULT, tags: ["large_complex", "near_station"], includeUnknownTag: true },
    );
    expect(out.entries).toHaveLength(0);
    expect(out.shownTagUnknown).toBe(0);
    expect(out.hiddenTagUnknown).toBe(0);
  });
});

describe("'없다'와 '모른다'를 구분하는 재료", () => {
  it("아무도 세대수를 모르면 그 칩은 '0건'이 아니라 '판정 불가'다", () => {
    const out = filterList(
      [src("가", 800_000_000, {}), src("나", 800_000_000, {})],
      DEFAULT,
    );
    const unmeasurable = unmeasurableTags(out);
    expect(unmeasurable.map((c) => c.id)).toEqual([
      "large_complex",
      "near_station",
      "redevelopment",
    ]);
    expect(missingFactLabels(unmeasurable)).toEqual(["세대수", "역 거리", "정비사업 확인"]);
  });

  it("진짜 0건(전부 판정했는데 해당 없음)은 판정 불가 목록에 들어가지 않는다", () => {
    const out = filterList([src("가", 800_000_000, { households: 100 })], DEFAULT);
    expect(unmeasurableTags(out).map((c) => c.id)).not.toContain("large_complex");
  });

  it("빈 목록이면 칩은 전부 0 이고 판정 불가도 없다", () => {
    const out = filterList([], DEFAULT);
    expect(out.entries).toEqual([]);
    expect(out.total).toBe(0);
    expect(out.chips.every((c) => c.count === 0 && c.unknown === 0)).toBe(true);
    expect(unmeasurableTags(out)).toEqual([]);
  });
});

describe("예산과 태그를 함께 걸 때", () => {
  it("예산 → 태그 순으로 걸리고 두 숨김 건수가 각각 남는다", () => {
    const out = filterList(
      [
        src("싼대단지", 800_000_000, { households: 1500 }),
        src("비싼대단지", 5_000_000_000, { households: 1500 }),
        src("싼세대수미상", 700_000_000, { households: null }),
      ],
      { ...DEFAULT, budgetOnly: true, tags: ["large_complex"] },
    );
    expect(names(out)).toEqual(["싼대단지"]);
    expect(out.hiddenOverBudget).toBe(1);
    expect(out.hiddenTagUnknown).toBe(1);
  });
});
