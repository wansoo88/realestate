// @vitest-environment jsdom
/**
 * 추천 패널 — "왜 이건 안 나왔지"에 답하는 부분을 못박는다.
 * 제외 사유가 안 보이면 사용자는 결과를 신뢰할 수 없고, 신뢰 못 하면 이 도구를 안 쓴다.
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RecommendationItem, RecommendationJob } from "../api/client";
import type { SearchScope } from "../lib/searchScope";
import { RecommendPanel } from "./RecommendPanel";

afterEach(cleanup);

const noop = () => {};

function base(over: Partial<React.ComponentProps<typeof RecommendPanel>> = {}) {
  return {
    phase: "idle" as const,
    job: null,
    error: null,
    budgetKrw: 850_000_000,
    regionCodes: [] as string[],
    onRegionsChange: noop,
    currentBbox: "126.9,37.4,127.0,37.6" as string | null,
    areaBbox: null as string | null,
    onCaptureArea: noop as (bbox: string) => void,
    onClearArea: noop,
    appliedScope: null as SearchScope | null,
    onStart: noop,
    onCancel: noop,
    ...over,
  };
}

const DONE: RecommendationJob = {
  job_id: "rec_1",
  status: "done",
  items: [],
  excluded: [
    { complex_id: 7, reason: "예산 초과 (최근 실거래 중위 12억(추정) > 한도 8.5억)" },
    { complex_id: 9, reason: "가격 근거 없음 — 활성 호가가 없고 실거래 표본 부족" },
  ],
  notes: ["입지 분석은 데이터 수집 후 제공됩니다."],
  disclaimer: "투자 권유가 아닙니다.",
};

describe("실행 전", () => {
  it("어떤 예산으로 분석하는지 먼저 말한다", () => {
    render(<RecommendPanel {...base()} />);
    expect(screen.getByText(/내 예산 8.50억 기준으로 분석합니다/)).toBeTruthy();
  });

  it("예산을 모르면 그 사실을 숨기지 않는다", () => {
    render(<RecommendPanel {...base({ budgetKrw: null })} />);
    expect(screen.getByText(/예산이 아직 계산되지 않았습니다/)).toBeTruthy();
  });

  it("분석은 명시적 버튼으로만 시작한다(자동 실행 금지 — API 비용)", async () => {
    const onStart = vi.fn();
    const user = userEvent.setup();
    render(<RecommendPanel {...base({ onStart })} />);

    expect(onStart).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "AI 추천 실행" }));
    expect(onStart).toHaveBeenCalledTimes(1);
  });
});

describe("진행 중", () => {
  it("진행 상태를 보조기기에도 알린다", () => {
    render(<RecommendPanel {...base({ phase: "running", job: { ...DONE, status: "running" } })} />);
    const status = screen.getByRole("status");
    expect(status.textContent).toContain("분석 중");
  });

  it("진행률이 없으면 지어내지 않는다", () => {
    render(<RecommendPanel {...base({ phase: "running" })} />);
    expect(screen.getByRole("status").textContent).not.toMatch(/%/);
  });
});

describe("결과", () => {
  it("제외된 후보와 사유를 보여준다", () => {
    render(<RecommendPanel {...base({ phase: "done", job: DONE })} />);
    expect(screen.getByText("제외된 후보")).toBeTruthy();
    expect(screen.getByText(/예산 초과/)).toBeTruthy();
    expect(screen.getByText(/가격 근거 없음/)).toBeTruthy();
  });

  it("0건이면 왜 0건인지 말하고, 지어낸 후보로 채우지 않는다", () => {
    render(<RecommendPanel {...base({ phase: "done", job: { ...DONE, excluded: [] } })} />);
    expect(screen.getByText("조건에 맞는 후보가 없습니다.")).toBeTruthy();
    expect(screen.getByText(/지어낸 후보를 채우지 않습니다/)).toBeTruthy();
  });

  it("서버가 제외 목록을 안 주면 '없다'가 아니라 '응답에 없다'고 말한다", () => {
    const { container } = render(
      <RecommendPanel {...base({ phase: "done", job: { ...DONE, excluded: null } })} />,
    );
    expect(screen.getByText(/제외 사유 목록은 이번 응답에 포함되지 않았습니다/)).toBeTruthy();
    expect(container.textContent).not.toContain("제외된 후보");
  });

  it("서버 고지(disclaimer)와 실거래 지연 고지를 함께 남긴다", () => {
    render(<RecommendPanel {...base({ phase: "done", job: DONE })} />);
    expect(screen.getByText("투자 권유가 아닙니다.")).toBeTruthy();
    expect(screen.getByText(/최대 30일/)).toBeTruthy();
  });

  it("서버 notes(좌표 없는 단지 누락 등)를 빠뜨리지 않는다", () => {
    const job = {
      ...DONE,
      notes: ["좌표가 없는 단지 5.5%는 지도 범위(bbox) 검색에서 빠졌습니다."],
    };
    render(<RecommendPanel {...base({ phase: "done", job })} />);
    expect(screen.getByText(/좌표가 없는 단지 5.5%/)).toBeTruthy();
  });
});

/* ─────────────────────────────────────────────────────────────────────────
 * 예산 토글 · 특성 칩
 *
 * 여기서 지키는 것은 두 가지다.
 *  ① **순위를 다시 매기지 않는다.** 3위만 남았으면 화면에도 3위여야 한다 —
 *     1위로 다시 붙이면 "이게 1등"이라는 없는 사실을 만들어낸다.
 *  ② **가린 건 숫자로 말한다.**
 * ───────────────────────────────────────────────────────────────────────── */

function recItem(over: Partial<RecommendationItem> = {}): RecommendationItem {
  return {
    rank: 1,
    complex: { id: 1, name: "가나아파트" },
    unit_type: { area_m2: 84 },
    building: null,
    dong_valuation: null,
    price_basis: "trade",
    ask_price_krw: null,
    est_price_krw: 800_000_000,
    price_estimated: true,
    price_note: null,
    ask_gap_pct: null,
    price_band: null,
    total_score: 70,
    score_basis: "user_weighted",
    timing_signal: "unknown",
    headline: "요약",
    why: [],
    why_not: [],
    next_actions: [],
    findings: [],
    ...over,
  };
}

describe("결과 목록 필터", () => {
  const OVER_THEN_WITHIN = [
    recItem({
      rank: 1,
      complex: { id: 1, name: "비싼아파트" },
      total_households: 1500,
      nearest_station: { name: "가나역", distance_m: 300, basis: "straight_line" },
      est_price_krw: 1_500_000_000,
    }),
    recItem({
      rank: 2,
      complex: { id: 2, name: "싼아파트" },
      total_households: 300,
      nearest_station: { name: "다라역", distance_m: 900, basis: "straight_line" },
      est_price_krw: 700_000_000,
    }),
  ];

  function job(items: RecommendationItem[]): RecommendationJob {
    return { job_id: "rec_1", status: "done", items, excluded: [], notes: [] };
  }

  it("예산 내 토글로 가려도 **순위 번호는 그대로**다(2위가 1위가 되지 않는다)", () => {
    render(
      <RecommendPanel
        {...base({
          phase: "done",
          job: job(OVER_THEN_WITHIN),
          budgetOnly: true,
          listBudgetKrw: 1_000_000_000,
        })}
      />,
    );

    expect(screen.getByText("싼아파트")).toBeTruthy();
    expect(screen.queryByText("비싼아파트")).toBeNull();
    // 남은 카드의 순위는 서버가 준 2위 그대로
    expect(screen.getByLabelText("2순위")).toBeTruthy();
    expect(screen.queryByLabelText("1순위")).toBeNull();
  });

  it("가린 추천이 몇 건인지 말한다", () => {
    render(
      <RecommendPanel
        {...base({
          phase: "done",
          job: job(OVER_THEN_WITHIN),
          budgetOnly: true,
          listBudgetKrw: 1_000_000_000,
        })}
      />,
    );
    expect(screen.getByText(/예산 초과 1건 숨김/)).toBeTruthy();
  });

  it("특성 칩을 누르면 그 특성만 남고 순위는 유지된다", async () => {
    const user = userEvent.setup();
    render(<RecommendPanel {...base({ phase: "done", job: job(OVER_THEN_WITHIN) })} />);

    await user.click(screen.getByRole("button", { name: /대단지 1건/ }));

    expect(screen.getByText("비싼아파트")).toBeTruthy();
    expect(screen.queryByText("싼아파트")).toBeNull();
    expect(screen.getByLabelText("1순위")).toBeTruthy();
  });

  it("특성이 확인된 후보에는 배지가 붙고, 아닌 후보에는 안 붙는다", () => {
    render(<RecommendPanel {...base({ phase: "done", job: job(OVER_THEN_WITHIN) })} />);

    // 칩 줄에도 같은 낱말이 있으므로 **카드 안에서만** 찾는다
    const big = screen.getByText("비싼아파트").closest("article") as HTMLElement;
    expect(within(big).getByText(/대단지/)).toBeTruthy();
    expect(within(big).getByText(/역세권/)).toBeTruthy();

    // 300세대·900m 는 둘 다 기준 미달 — 배지를 붙이지 않는다
    const small = screen.getByText("싼아파트").closest("article") as HTMLElement;
    expect(small.querySelector(".tags")).toBeNull();
  });

  it("필터로 전부 가려지면 '추천이 없다'가 아니라 '가려졌다'고 말한다", () => {
    render(
      <RecommendPanel
        {...base({
          phase: "done",
          job: job([recItem({ est_price_krw: 5_000_000_000 })]),
          budgetOnly: true,
          listBudgetKrw: 1_000_000_000,
        })}
      />,
    );
    expect(screen.getByText(/필터에 걸려 추천 1건이 모두 가려졌습니다/)).toBeTruthy();
    // 0건 안내(조건에 맞는 후보가 없습니다)와 섞이면 안 된다 — 원인이 다르다
    expect(screen.queryByText("조건에 맞는 후보가 없습니다.")).toBeNull();
  });

  /**
   * 서버가 세대수·역 거리를 아직 안 싣는 현재 상태.
   * 이때 칩이 "0" 이라고만 적히면 "이 결과엔 대단지가 없다"는 **거짓 단언**이 된다.
   */
  it("판정에 필요한 사실이 없으면 '없다'가 아니라 '모른다'고 말한다", () => {
    render(
      <RecommendPanel
        {...base({
          phase: "done",
          job: job([recItem({ complex: { id: 1, name: "가나아파트" } })]),
        })}
      />,
    );

    const chip = screen.getByRole("button", { name: /대단지 0건/ }) as HTMLButtonElement;
    expect(chip.disabled).toBe(true);
    expect(screen.getByText(/해당 단지가 없는 게 아니라 판정할 정보가 없습니다/)).toBeTruthy();
    // 사실이 없으면 카드에 배지도 달지 않는다(지어내지 않는다)
    const card = screen.getByText("가나아파트").closest("article") as HTMLElement;
    expect(card.querySelector(".tags")).toBeNull();
  });

  it("결과가 없으면 필터 줄 자체를 만들지 않는다(거를 게 없으면 조작도 없다)", () => {
    render(<RecommendPanel {...base({ phase: "done", job: DONE })} />);
    expect(screen.queryByRole("switch", { name: /예산 내/ })).toBeNull();
  });
});

/**
 * 결과가 나온 뒤 지도를 옮기면 "그때 그 범위"를 알 길이 사라진다.
 * 그래서 **실행 당시 범위**를 결과 옆에 적어 둔다(조건 상태가 아니라 실행 기록을 그린다).
 */
describe("이 결과를 찾은 범위", () => {
  const SCOPE: SearchScope = { regionCodes: ["11680"], bbox: "126.9,37.4,127.0,37.6" };

  it("어느 범위로 돌았는지 결과와 함께 남는다", () => {
    render(<RecommendPanel {...base({ phase: "done", job: DONE, appliedScope: SCOPE })} />);
    expect(
      screen.getByText(/이 결과를 찾은 범위: 이 주변\(약 8\.8 × 22km\) ∩ 서울 강남구/),
    ).toBeTruthy();
  });

  it("실행 뒤 조건을 바꿔도 결과의 범위 표기는 따라 바뀌지 않는다", () => {
    // 지금 조건은 비었는데(칩 해제·지역 초기화) 결과는 그때 범위에서 나온 것이다
    render(
      <RecommendPanel
        {...base({ phase: "done", job: DONE, appliedScope: SCOPE, areaBbox: null, regionCodes: [] })}
      />,
    );
    expect(screen.getByText(/이 결과를 찾은 범위: 이 주변\(약 8\.8 × 22km\) ∩ 서울 강남구/))
      .toBeTruthy();
  });

  it("지금 지도와 다른 범위면 그 사실을 말한다(지금 화면 = 결과 로 읽히지 않게)", () => {
    render(
      <RecommendPanel
        {...base({
          phase: "done",
          job: DONE,
          appliedScope: SCOPE,
          currentBbox: "127.5,37.4,127.6,37.6",
        })}
      />,
    );
    expect(screen.getByText(/지금 보고 있는 지도와 다른 범위입니다/)).toBeTruthy();
  });

  it("지도가 그대로면 굳이 다르다고 말하지 않는다", () => {
    render(
      <RecommendPanel
        {...base({ phase: "done", job: DONE, appliedScope: SCOPE, currentBbox: SCOPE.bbox })}
      />,
    );
    expect(screen.queryByText(/지금 보고 있는 지도와 다른 범위입니다/)).toBeNull();
  });

  it("실행 전에는 범위 표기를 만들지 않는다(돌지도 않은 분석의 범위는 없다)", () => {
    const { container } = render(<RecommendPanel {...base({ appliedScope: null })} />);
    expect(container.textContent).not.toContain("이 결과를 찾은 범위");
  });
});

/* ─────────────────────────────────────────────────────────────────────────
 * FE-4 — "이 결과는 어떤 조건으로 나왔나"
 *
 * 칩을 껐는데 추천만 계속 걸러지던 사고 이후, 화면은 세 가지를 말해야 한다:
 *   ① 지금 무엇이 걸리는가  ② 무엇을 꺼 뒀는가  ③ 지도와 다르게 도는 부분이 있는가
 * ───────────────────────────────────────────────────────────────────────── */

describe("적용된 조건 표기", () => {
  const PLAN_ON = {
    on: [
      { id: "budget" as const, label: "희망가 9.00억 이하", side: "both" as const },
      { id: "area" as const, label: "전용 59~84㎡", side: "both" as const },
    ],
    off: [],
    diverged: false,
  };

  it("실행 전에는 '적용할 조건'으로 미리 보여준다", () => {
    render(<RecommendPanel {...base({ conditions: PLAN_ON })} />);
    expect(screen.getByText("적용할 조건")).toBeTruthy();
    expect(screen.getByText("희망가 9.00억 이하 · 전용 59~84㎡")).toBeTruthy();
  });

  it("결과가 나오면 **그때 쓴 조건**을 적는다(지금 칩 상태가 아니다)", () => {
    render(
      <RecommendPanel
        {...base({
          phase: "done",
          job: DONE,
          conditions: { on: [], off: [], diverged: false }, // 결과 후 칩을 다 껐다
          appliedConditions: PLAN_ON,
        })}
      />,
    );
    expect(screen.getByText("이 결과에 적용된 조건")).toBeTruthy();
    expect(screen.getByText("희망가 9.00억 이하 · 전용 59~84㎡")).toBeTruthy();
  });

  it("꺼 둔 조건은 사라지지 않고 '껐다'고 적힌다 — 추천에도 안 걸린다는 뜻이다", () => {
    render(
      <RecommendPanel
        {...base({
          conditions: {
            on: [{ id: "budget" as const, label: "내 예산 8.50억 이내", side: "both" as const }],
            off: [{ id: "area" as const, label: "전용 59~84㎡", side: "both" as const }],
            diverged: false,
          },
        })}
      />,
    );
    expect(screen.getByText("꺼 둔 조건")).toBeTruthy();
    expect(screen.getByText(/전용 59~84㎡ — 지도와 추천 모두 적용하지 않았습니다/)).toBeTruthy();
  });

  it("지도와 추천이 다른 조건으로 돌면 그 사실을 말한다", () => {
    render(
      <RecommendPanel
        {...base({
          conditions: {
            on: [
              { id: "budget" as const, label: "내 예산 8.50억 이내", side: "rec_only" as const },
              { id: "households" as const, label: "1,000세대 이상", side: "rec_only" as const },
            ],
            off: [],
            diverged: true,
          },
        })}
      />,
    );
    expect(
      screen.getByText(/내 예산 8.50억 이내 · 1,000세대 이상 은\(는\) 추천에만 걸립니다/),
    ).toBeTruthy();
  });

  it("걸린 조건이 없으면 빈 줄을 만들지 않는다", () => {
    const { container } = render(
      <RecommendPanel {...base({ conditions: { on: [], off: [], diverged: false } })} />,
    );
    expect(container.querySelector(".rec__conds")).toBeNull();
  });
});

/* CR31-2 — 카드별 강등 표기의 스위치를 패널이 계산해 내려준다. */
describe("요약 강등 표기는 결과 전체를 보고 정한다", () => {
  function job(items: RecommendationItem[]): RecommendationJob {
    return { job_id: "rec_1", status: "done", items, excluded: [], notes: [] };
  }

  it("AI 요약이 섞여 있으면 규칙 기반 카드에만 표기한다", () => {
    render(
      <RecommendPanel
        {...base({
          phase: "done",
          job: job([
            recItem({ rank: 1, complex: { id: 1, name: "가나" }, summary_basis: "llm" }),
            recItem({ rank: 2, complex: { id: 2, name: "다라" }, summary_basis: "fallback" }),
          ]),
        })}
      />,
    );
    expect(screen.getAllByText("규칙 기반 요약")).toHaveLength(1);
  });

  it("전부 규칙 기반이면(LLM 미연결) 카드에는 한 건도 띄우지 않는다", () => {
    render(
      <RecommendPanel
        {...base({
          phase: "done",
          job: job([
            recItem({ rank: 1, complex: { id: 1, name: "가나" }, summary_basis: "fallback" }),
            recItem({ rank: 2, complex: { id: 2, name: "다라" }, summary_basis: "fallback" }),
          ]),
        })}
      />,
    );
    expect(screen.queryByText("규칙 기반 요약")).toBeNull();
  });
});
