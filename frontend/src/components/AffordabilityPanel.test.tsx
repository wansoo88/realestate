// @vitest-environment jsdom
/**
 * 자금계획 표시 — "이 집을 사려면 뭐가 필요한가"에 숫자로 답하는 자리.
 *
 * 이 화면이 반드시 지켜야 하는 것 셋
 *  ① **한도를 넘어도 숫자를 지우지 않는다.** "불가능"만 띄우면 얼마를 더 모아야 하는지
 *     알 수 없다 — 그게 사용자가 물어본 것이다.
 *  ② **가정(금리·기간)이 월 상환액 옆에 있다.** 4%/30년이 5%/20년이면 40% 넘게 달라진다(G2).
 *  ③ 단지 기준 계획의 가격은 `recent_price_krw` = **실거래 추정치**지 호가가 아니다.
 */
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AffordabilityPlan, AffordabilityResponse } from "../api/client";
import { AffordabilityPanel, type PlanBasis } from "./AffordabilityPanel";

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

function response(plan: AffordabilityPlan | null = PLAN): AffordabilityResponse {
  return {
    max_purchase_krw: 850_000_000,
    plan,
    breakdown: {
      own_cash_krw: 300_000_000,
      max_loan_krw: 550_000_000,
      binding_constraint: "DSR",
    },
    acquisition_cost_krw: {
      tax: 9_350_000,
      brokerage: 5_100_000,
      registration: 1_000_000,
      total: 15_450_000,
    },
    assumptions: ["기존 대출 상환액 미입력 — 0으로 계산했습니다"],
    evidence: [{ claim: "취득세율 1.1%", source: "지방세법 §11", as_of: "2026-07-24" }],
    warnings: [],
    disclaimer: "실제 한도는 금융기관 심사에 따라 달라집니다.",
  };
}

function renderPanel(props: Partial<React.ComponentProps<typeof AffordabilityPanel>> = {}) {
  render(
    <AffordabilityPanel
      data={response()}
      loading={false}
      error={null}
      planBasis={{ kind: "manual" }}
      {...props}
    />,
  );
}

afterEach(cleanup);

describe("라벨", () => {
  it("'최대 실구매 가능 금액' 이라고 부른다 — '실구매 가능 금액'은 희망가와 헷갈린다", () => {
    renderPanel();
    expect(screen.getByRole("heading", { name: "최대 실구매 가능 금액" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "실구매 가능 금액" })).toBeNull();
  });

  it("자산 미입력 안내에도 같은 이름을 쓴다", () => {
    renderPanel({ data: null, needsProfile: true });
    expect(screen.getByText(/최대 실구매 가능 금액을 계산합니다/)).toBeTruthy();
  });

  it("값 계산은 그대로다(문구만 바꿨다)", () => {
    renderPanel();
    expect(screen.getByText("8억 5,000만")).toBeTruthy();
  });
});

describe("자금계획 — 필요한 돈을 단계로 보여준다", () => {
  it("희망가 · 총 필요자금 · 부대비용 내역이 함께 나온다", () => {
    renderPanel();

    const plan = screen.getByRole("region", { name: "자금계획" });
    expect(plan.textContent).toContain("9억"); // 희망가
    expect(plan.textContent).toContain("9억 3,000만"); // 총 필요자금
    // 총 필요자금이 어디서 왔는지 — 합계만 보여주면 사용자가 검산할 수 없다
    expect(plan.textContent).toContain("취득세");
    expect(plan.textContent).toContain("2,500만");
    expect(plan.textContent).toContain("중개보수");
  });

  it("내 현금과 **더 필요한 돈**을 나눠 말한다", () => {
    renderPanel();
    const plan = screen.getByRole("region", { name: "자금계획" });

    expect(plan.textContent).toContain("내 현금");
    expect(plan.textContent).toContain("3억");
    expect(plan.textContent).toContain("더 필요한 돈");
    expect(plan.textContent).toContain("6억 3,000만");
  });

  it("월 원리금에 **가정(금리·기간)이 붙어 있다** — 가정 없는 상환액은 근거 없는 숫자다", () => {
    renderPanel();

    // 만원 단위 소수까지 — 3,007,000원을 "300만"으로 뭉개면 30년 치 250만원이 사라진다
    expect(screen.getByText("300.7만원")).toBeTruthy();
    const terms = screen.getByText(/금리 4% · 30년/);
    expect(terms).toBeTruthy();
    expect(terms.textContent).toContain("원리금 균등");
  });

  it("총 이자도 같은 가정 기준임을 밝힌다", () => {
    renderPanel();
    expect(screen.getByText(/총 이자/).textContent).toContain("같은 가정");
  });
});

describe("한도 초과 — 숫자를 지우지 않는다", () => {
  it("필요 대출 · 내 한도 · 초과분 · 무엇이 막는지를 모두 보여준다", () => {
    renderPanel();
    const plan = screen.getByRole("region", { name: "자금계획" });

    expect(plan.textContent).toContain("필요 대출");
    expect(plan.textContent).toContain("6억 3,000만"); // 필요 대출
    expect(plan.textContent).toContain("5억 5,000만"); // 내 한도
    expect(plan.textContent).toContain("8,000만"); // 초과분
    expect(plan.textContent).toContain("총부채원리금상환비율(DSR)"); // 무엇이 막는가
    expect(screen.getByText("한도 초과")).toBeTruthy();
  });

  it("'불가능합니다'로 끝내지 않고 **다음 행동**을 말한다", () => {
    renderPanel();
    expect(screen.getByText(/현금을 더 모으거나 더 싼 집/)).toBeTruthy();
  });

  it("한도 안이면 초과 경고 대신 여유를 말한다", () => {
    renderPanel({
      data: response({ ...PLAN, loan_feasible: true, over_limit_krw: null }),
    });
    expect(screen.queryByText("한도 초과")).toBeNull();
    const plan = screen.getByRole("region", { name: "자금계획" });
    expect(plan.textContent).toContain("내 대출 한도");
    expect(plan.textContent).toContain("안입니다");
    // 그래도 월 상환액은 그대로 보인다
    expect(screen.getByText("300.7만원")).toBeTruthy();
  });
});

describe("단지 기준 계획 — 추정치임을 감추지 않는다", () => {
  const basis: PlanBasis = {
    kind: "complex",
    name: "○○아파트",
    estimated: true,
    asOf: "2026-06-30",
  };

  it("단지명과 함께 '추정' 배지·기준일을 붙인다", () => {
    renderPanel({ planBasis: basis });

    expect(screen.getByText("○○아파트")).toBeTruthy();
    expect(screen.getByText("추정")).toBeTruthy();
    expect(screen.getByText(/2026년 6월 30일 기준/)).toBeTruthy();
  });

  it("'지금 살 수 있는 호가가 아니다'를 문장으로 말한다", () => {
    renderPanel({ planBasis: basis });
    expect(screen.getByText(/지금 살 수 있는 호가가 아니라/)).toBeTruthy();
    expect(screen.getByText(/신고 지연/)).toBeTruthy();
  });

  it("내 희망가로 되돌아갈 길이 있다", async () => {
    const onClear = vi.fn();
    const user = userEvent.setup();
    renderPanel({ planBasis: basis, onClearComplex: onClear, targetPriceKrw: 800_000_000 });

    await user.click(screen.getByRole("button", { name: /내 희망가\(8억\) 기준으로 계산/ }));
    expect(onClear).toHaveBeenCalled();
  });

  it("시세 근거가 없는 단지는 **왜 이 단지 기준이 아닌지** 말한다", () => {
    renderPanel({ planBasis: { kind: "manual" }, noPriceComplexName: "미상아파트" });
    const note = screen.getByText(/최근 실거래 근거가 없어/);
    expect(note.textContent).toContain("미상아파트");
    expect(note.textContent).toContain("계산할 수 없습니다");
    // 보조기기가 이 변화를 놓치지 않게 라이브 리전으로 알린다
    expect(note.getAttribute("role")).toBe("status");
  });
});

describe("계획이 없을 때 — 지어내지 않는다", () => {
  it("희망가도 단지도 없으면 정하는 길을 안내한다", async () => {
    const onEdit = vi.fn();
    const user = userEvent.setup();
    renderPanel({ data: response(null), planBasis: null, onEditConditions: onEdit });

    expect(screen.getByText(/희망 매매가를 정하거나 지도에서 단지를 고르면/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "희망 매매가 정하기" }));
    expect(onEdit).toHaveBeenCalled();
  });

  it("희망가는 있는데 서버가 plan 을 안 주면 그 사실을 말한다(빈칸으로 두지 않는다)", () => {
    renderPanel({ data: response(null), planBasis: { kind: "manual" } });
    expect(screen.getByText(/자금계획이 포함되지 않았습니다/)).toBeTruthy();
  });

  it("필수 숫자가 빠진 plan 은 렌더링하지 않는다(NaN 을 화면에 흘리지 않는다)", () => {
    const broken = { ...PLAN, monthly_payment_krw: undefined } as unknown as AffordabilityPlan;
    const { container } = render(
      <AffordabilityPanel
        data={response(broken)}
        loading={false}
        error={null}
        planBasis={{ kind: "manual" }}
      />,
    );
    expect(container.textContent).not.toContain("NaN");
    expect(screen.getByText(/자금계획이 포함되지 않았습니다/)).toBeTruthy();
  });
});

describe("기존 화면 회귀", () => {
  it("한도를 묶은 제약·근거·가정은 그대로 나온다", () => {
    renderPanel();
    expect(screen.getByText(/한도를 결정한 건 총부채원리금상환비율\(DSR\)/)).toBeTruthy();
    expect(screen.getByText("취득세율 1.1%")).toBeTruthy();
    expect(screen.getByText(/지방세법 §11/)).toBeTruthy();
  });
});

/* ─────────────────────────────────────────────────────────────────────────
 * CR35-4 — **무엇을 기준으로 계산했는지 화면이 말한다**
 *
 * 같은 단지가 자금계획과 추천 카드에서 다른 금액으로 서던 문제의 마지막 조각이다.
 * 이제 금액은 서버가 정하고(추천과 같은 함수), 화면은 그 근거를 **접지 않고** 적는다.
 * ───────────────────────────────────────────────────────────────────────── */

describe("기준가 근거 (target_price)", () => {
  const COMPLEX_BASIS: PlanBasis = {
    kind: "complex",
    name: "가나아파트",
    estimated: true,
    asOf: "2026-06-30",
  };

  it("시점 환산 추정가면 표본·기준월과 **무엇과 같은 기준인지**를 적는다 (CR36-5)", () => {
    renderPanel({
      data: {
        ...response(),
        target_price: {
          krw: 900_000_000,
          basis: "time_adjusted_band",
          as_of_ym: "2026-06",
          sample_size: 12,
          period_months: 12,
          reason: null,
        },
      },
      planBasis: COMPLEX_BASIS,
      planArea: { m2: 84.97, basis: "map_trade" },
    });

    const plan = screen.getByRole("region", { name: "자금계획" });
    expect(plan.textContent).toContain("최근 실거래를 한 시점으로 환산한 추정가");
    expect(plan.textContent).toContain("12건");
    expect(plan.textContent).toContain("2026-06");
    // 어느 카드와 같은 값인지 말하지 않으면, 추천을 안 돌린 사용자에게는 없는 카드를 가리킨다
    expect(plan.textContent).toContain("AI 추천도 '가나아파트 84.97㎡' 를 같은 기준으로 계산합니다");
    // 어느 면적으로 물었는지 — 없으면 34평 계획이 25평 매물의 계획으로 읽힌다
    expect(plan.textContent).toContain("84.97㎡ 기준");
  });

  it("직접 입력한 금액은 '직접 입력하신 금액'이라고 부른다(서버가 근거를 모른다)", () => {
    renderPanel({
      data: {
        ...response(),
        target_price: { krw: 900_000_000, basis: "client_supplied", sample_size: 0 },
      },
      planBasis: { kind: "manual" },
    });

    const plan = screen.getByRole("region", { name: "자금계획" });
    expect(plan.textContent).toContain("직접 입력하신 금액");
    expect(plan.textContent).toContain("서버가 근거를 확인하지 않았습니다");
  });

  it("기준가를 못 만들었으면 **계획을 지어내지 않고 사유**를 보인다", () => {
    renderPanel({
      data: {
        ...response(null),
        target_price: {
          krw: null,
          basis: null,
          sample_size: 0,
          reason: "이 단지의 실거래 자료가 없습니다",
        },
      },
      planBasis: COMPLEX_BASIS,
    });

    const plan = screen.getByRole("region", { name: "자금계획" });
    expect(plan.textContent).toContain("자금계획을 세우지 못했습니다");
    expect(plan.textContent).toContain("이 단지의 실거래 자료가 없습니다");
    // 사유를 아는데 "포함되지 않았습니다"로 뭉뚱그리지 않는다
    expect(plan.textContent).not.toContain("자금계획이 포함되지 않았습니다");
    expect(plan.textContent).not.toContain("0원");
  });

  it("서버가 블록을 안 주면(구버전) 근거 줄 자체가 없다 — 지어내지 않는다", () => {
    const { container } = render(
      <AffordabilityPanel
        data={response()}
        loading={false}
        error={null}
        planBasis={{ kind: "manual" }}
      />,
    );
    expect(container.querySelector(".plan__ref")).toBeNull();
    expect(container.querySelector(".plan__noref")).toBeNull();
  });
});
