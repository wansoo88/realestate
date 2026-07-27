// @vitest-environment jsdom
/**
 * 필터 줄 — **화면에 나가는 것**을 못박는다.
 *
 * 순수 함수 테스트(lib/listFilter.test.ts)는 "몇 건을 숨겼는지 계산했다"까지만 보장한다.
 * 그 숫자를 화면이 실제로 **말하는지**는 DOM 을 봐야 안다. 계산해 놓고 안 그리면
 * 사용자 입장에서는 조용히 사라진 것과 똑같다.
 */
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { filterList, type FilterSource } from "../lib/listFilter";
import type { TagFacts } from "../lib/tags";
import { ListFilterBar } from "./ListFilterBar";

afterEach(cleanup);

interface Row {
  name: string;
}

function src(name: string, priceKrw: number | null, facts: TagFacts = {}): FilterSource<Row> {
  return { item: { name }, priceKrw, facts };
}

const BUDGET = 1_000_000_000;

/** 컴포넌트는 순수 함수의 결과를 받아 그리기만 한다 — 같은 계산을 두 번 하지 않는다. */
function mount(
  sources: FilterSource<Row>[],
  state: Partial<Parameters<typeof filterList>[1]> = {},
  props: Partial<React.ComponentProps<typeof ListFilterBar<Row>>> = {},
) {
  const full = {
    budgetOnly: false,
    budgetKrw: BUDGET,
    tags: [],
    includeUnknownTag: false,
    ...state,
  };
  const outcome = filterList(sources, full);
  const noop = () => {};
  render(
    <ListFilterBar
      listLabel="주변 단지"
      outcome={outcome}
      budgetOnly={full.budgetOnly}
      onBudgetOnlyChange={noop}
      onToggleTag={noop}
      onClearTags={noop}
      includeUnknownTag={full.includeUnknownTag}
      onIncludeUnknownChange={noop}
      {...props}
    />,
  );
  return outcome;
}

describe("예산 내 토글", () => {
  const rows = [
    src("싼집", 800_000_000),
    src("비싼집", 1_500_000_000),
    src("가격미상", null),
  ];

  it("지금 켜졌는지 꺼졌는지가 상태로 드러난다(role=switch)", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    mount(rows, {}, { onBudgetOnlyChange: onChange });

    const sw = screen.getByRole("switch", { name: /예산 내/ });
    expect(sw.getAttribute("aria-checked")).toBe("false");

    await user.click(sw);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("켜져 있으면 aria-checked 가 켜진다", () => {
    mount(rows, { budgetOnly: true });
    expect(screen.getByRole("switch", { name: /예산 내/ }).getAttribute("aria-checked")).toBe("true");
  });

  it("**숨긴 개수를 화면에 적는다** — 조용히 사라지면 안 된다", () => {
    mount(rows, { budgetOnly: true });
    expect(screen.getByText(/예산 초과 1건 · 가격 미상 1건 숨김/)).toBeTruthy();
  });

  it("가격 미상을 예산 내로 치지 않는 이유를 화면이 말한다", () => {
    mount(rows, { budgetOnly: true });
    expect(screen.getByText(/가격을 모르는 항목은 예산 내로 치지 않습니다/)).toBeTruthy();
  });

  it("꺼져 있어도 초과·미상이 몇 건 섞여 있는지 말한다(상태를 양쪽 다 밝힌다)", () => {
    mount(rows);
    expect(screen.getByText(/예산 초과 1건 · 가격 미상 1건도 함께 보는 중/)).toBeTruthy();
  });

  it("예산을 모르면 토글을 켤 수 없고 그 이유를 적는다", () => {
    mount(rows, { budgetKrw: null });
    const sw = screen.getByRole("switch", { name: /예산 내/ }) as HTMLButtonElement;
    expect(sw.disabled).toBe(true);
    expect(screen.getByText(/내 예산을 아직 계산하지 못해/)).toBeTruthy();
  });

  it("보이는 건수와 전체 건수를 함께 적는다", () => {
    mount(rows, { budgetOnly: true });
    expect(screen.getByText(/전체 3건/)).toBeTruthy();
  });
});

describe("특성 칩", () => {
  const rows = [
    src("대단지역세권", 800_000_000, { households: 1500, stationDistanceM: 300 }),
    src("대단지만", 900_000_000, { households: 1200, stationDistanceM: 900 }),
    src("역세권만", 700_000_000, { households: 400, stationDistanceM: 200 }),
  ];

  it("칩마다 해당 건수를 적는다", () => {
    mount(rows);
    expect(screen.getByRole("button", { name: /대단지 2건/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /역세권 2건/ })).toBeTruthy();
  });

  it("0건 칩은 숨기지 않고 비활성으로 남긴다(없다는 것도 정보다)", () => {
    mount(rows);
    const redev = screen.getByRole("button", { name: /재건축 0건/ }) as HTMLButtonElement;
    expect(redev.disabled).toBe(true);
  });

  it("누르면 그 특성만 남기도록 알린다", async () => {
    const onToggle = vi.fn();
    const user = userEvent.setup();
    mount(rows, {}, { onToggleTag: onToggle });

    await user.click(screen.getByRole("button", { name: /대단지 2건/ }));
    expect(onToggle).toHaveBeenCalledWith("large_complex");
  });

  it("'전체' 칩은 아무 태그도 안 골랐을 때 눌린 상태다", () => {
    mount(rows);
    expect(screen.getByRole("button", { name: /전체/ }).getAttribute("aria-pressed")).toBe("true");
  });

  it("칩 기준을 보조기기에 함께 전달한다(왜 이게 대단지인가)", () => {
    mount(rows);
    expect(screen.getByRole("button", { name: /대단지 2건 · 기준 1,000세대 이상/ })).toBeTruthy();
  });

  it("색 없이도 구분되도록 아이콘과 라벨이 함께 있다", () => {
    const { container } = render(<div />);
    cleanup();
    mount(rows);
    const chip = screen.getByRole("button", { name: /대단지 2건/ });
    expect(chip.textContent).toContain("🏢");
    expect(chip.textContent).toContain("대단지");
    expect(container).toBeTruthy();
  });
});

describe("교집합/합집합을 화면이 분명히 말한다", () => {
  const rows = [
    src("둘다", 800_000_000, { households: 1500, stationDistanceM: 300 }),
    src("하나만", 800_000_000, { households: 1500, stationDistanceM: 900 }),
  ];

  it("칩 하나면 굳이 말하지 않는다", () => {
    mount(rows, { tags: ["large_complex"] });
    expect(screen.queryByText(/모두 만족하는/)).toBeNull();
  });

  it("칩 둘이면 '모두 만족'이라고 적는다(칩만 둘이면 합집합으로 읽힌다)", () => {
    mount(rows, { tags: ["large_complex", "near_station"] });
    expect(screen.getByText(/모두 만족하는 항목만 보입니다/)).toBeTruthy();
  });
});

describe("판정 불가를 아님으로 접지 않는다", () => {
  const rows = [
    src("확실한대단지", 800_000_000, { households: 1500 }),
    src("세대수미상", 800_000_000, { households: null }),
  ];

  it("제외한 건수와 이유를 적고, 볼 수 있는 길을 준다", async () => {
    const onInclude = vi.fn();
    const user = userEvent.setup();
    mount(rows, { tags: ["large_complex"] }, { onIncludeUnknownChange: onInclude });

    expect(screen.getByText(/세대수 정보가 없어 판정할 수 없는 1건은 제외했습니다/)).toBeTruthy();
    expect(screen.getByText(/'아님'이 아니라 '모름'입니다/)).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "판정 불가 항목도 보기" }));
    expect(onInclude).toHaveBeenCalledWith(true);
  });

  it("함께 보기를 켜면 몇 건이 되살아났는지 적는다", () => {
    mount(rows, { tags: ["large_complex"], includeUnknownTag: true });
    expect(screen.getByText(/1건을 함께 보는 중입니다/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "판정 불가 항목 숨기기" })).toBeTruthy();
  });

  it("판정 불가가 없으면 되살리기 버튼도 없다(할 게 없는 조작을 두지 않는다)", () => {
    mount([src("확실한대단지", 800_000_000, { households: 1500 })], { tags: ["large_complex"] });
    expect(screen.queryByRole("button", { name: /판정 불가/ })).toBeNull();
  });
});

describe("'0건'과 '모름'을 구분한다", () => {
  it("아무도 세대수를 모르면 '해당 없음'이 아니라 '판정 불가'라고 말한다", () => {
    mount([src("가", 800_000_000, {}), src("나", 800_000_000, {})]);
    // 칩은 0 이지만, 그게 "이 지역에 대단지가 없다"는 뜻이 아님을 적어야 한다
    expect(
      screen.getByText(/해당 단지가 없는 게 아니라 판정할 정보가 없습니다/),
    ).toBeTruthy();
    expect(screen.getByText(/대단지\(세대수 미상 2건\)/)).toBeTruthy();
  });

  it("보조기기에도 '해당 없음'과 '판정 불가'를 다르게 읽어 준다", () => {
    mount([src("가", 800_000_000, {})]);
    expect(
      screen.getByRole("button", {
        name: /대단지 0건 — 해당 없음이 아니라 1건을 판정할 수 없습니다/,
      }),
    ).toBeTruthy();
  });

  it("전부 판정된 진짜 0건은 판정 불가라고 하지 않는다", () => {
    mount([src("작은단지", 800_000_000, { households: 100, stationDistanceM: 900, redevelopment: false })]);
    expect(screen.queryByText(/판정할 정보가 없습니다/)).toBeNull();
  });
});
