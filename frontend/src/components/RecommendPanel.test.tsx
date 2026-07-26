// @vitest-environment jsdom
/**
 * 추천 패널 — "왜 이건 안 나왔지"에 답하는 부분을 못박는다.
 * 제외 사유가 안 보이면 사용자는 결과를 신뢰할 수 없고, 신뢰 못 하면 이 도구를 안 쓴다.
 */
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RecommendationJob } from "../api/client";
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
