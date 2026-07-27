// @vitest-environment jsdom
/**
 * 리포트 카드 — **화면에 나가는 것**을 못박는다.
 *
 * 순수 함수 테스트(lib/recommendation.test.ts)만으로는 부족하다.
 * 컴포넌트가 그 함수를 실제로 쓰는지, 아니면 원본 필드를 몰래 다시 읽는지는
 * DOM 을 봐야 안다.
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import type { RecommendationItem } from "../api/client";
import { ReportCard } from "./ReportCard";

afterEach(cleanup);

const LISTING: RecommendationItem = {
  rank: 1,
  complex: { id: 1024, name: "○○아파트" },
  unit_type: { area_m2: 84.97, type_name: "84A" },
  building: { id: 88, name: "101동", confidence: 0.6, basis: "listing_reported" },
  dong_valuation: {
    available: true,
    method: "실측(aptDong)",
    basis: "trade_measured",
    confidence: 0.85,
    coverage_pct: 87,
    dongs: [{ dong: "101", vs_complex_pct: 5.2, sample: 12, median_ppm_krw: 16_800_000 }],
  },
  price_basis: "listing",
  ask_price_krw: 1_480_000_000,
  est_price_krw: 1_480_000_000,
  price_estimated: false,
  price_note: null,
  ask_gap_pct: 5.7,
  price_band: {
    p25_krw: 1_380_000_000,
    median_krw: 1_400_000_000,
    p75_krw: 1_450_000_000,
    sample_size: 37,
    period_months: 6,
    expanded: false,
    source: "국토교통부 실거래가",
  },
  total_score: 82.4,
  score_basis: "agent_scores",
  timing_signal: "unknown",
  headline: "예산 내 후보입니다.",
  why: ["취득세 포함 총 필요자금이 한도 내"],
  why_not: ["용적률이 높아 재건축 사업성이 낮음"],
  next_actions: ["현장 방문"],
  findings: [
    {
      agent_id: "valuation-trader",
      verdict: "적정가 범위",
      rationale: "중위 대비 +5.7%",
      evidence: [
        { claim: "중위 실거래가 14억", source: "국토교통부 실거래가", data_rows: 37 },
        { claim: "출처 없는 주장" }, // ← 렌더링되면 안 된다
      ],
      risks: [{ severity: "medium", detail: "실거래 신고 지연" }],
      score: 76,
      confidence: 0.8,
      basis: null,
      missing: [],
    },
  ],
};

/** 호가가 없는(공공API만 있는) 현실의 기본 케이스. */
const TRADE: RecommendationItem = {
  ...LISTING,
  price_basis: "trade",
  ask_price_krw: null,
  est_price_krw: 1_400_000_000,
  price_estimated: true,
  price_note: "현재 등록된 매물이 없습니다 — 최근 실거래 기준 추정가입니다.",
  ask_gap_pct: null,
  building: null,
  total_score: null,
  score_basis: null,
  findings: [
    {
      agent_id: "location-analyst",
      verdict: "판단 보류",
      rationale: "판단에 필요한 데이터가 부족합니다: 입지 데이터(학군·교통·인프라) 미수집",
      evidence: [],
      risks: [],
      score: null,
      confidence: 0,
      basis: null,
      missing: ["입지 데이터(학군·교통·인프라) 미수집"],
    },
  ],
};

describe("price_basis=listing", () => {
  it("호가와 적정가 갭을 보여준다", () => {
    render(<ReportCard item={LISTING} />);
    expect(screen.getAllByText(/호가/).length).toBeGreaterThan(0);
    expect(screen.getByText("+5.7%")).toBeTruthy();
  });

  it("출처 없는 근거는 렌더링하지 않는다(G2)", () => {
    render(<ReportCard item={LISTING} />);
    expect(screen.getByText(/중위 실거래가 14억/)).toBeTruthy();
    expect(screen.queryByText(/출처 없는 주장/)).toBeNull();
  });

  it("동별 실측이면 실측으로 표기한다", () => {
    render(<ReportCard item={LISTING} />);
    expect(screen.getByText(/동별 실측/)).toBeTruthy();
  });
});

describe("price_basis=trade — 실거래를 호가로 둔갑시키지 않는다", () => {
  it("호가·호가갭을 화면에 내지 않는다", () => {
    render(<ReportCard item={TRADE} />);
    expect(screen.queryByText(/^호가/)).toBeNull();
    expect(screen.queryByText(/적정가 대비/)).toBeNull();
  });

  it("서버가 준 추정 안내 문구를 반드시 보여준다", () => {
    render(<ReportCard item={TRADE} />);
    expect(screen.getByText(/현재 등록된 매물이 없습니다/)).toBeTruthy();
  });

  it("기준가는 '추정' 배지와 함께 보인다", () => {
    render(<ReportCard item={TRADE} />);
    expect(screen.getByText("최근 실거래 기준 추정가")).toBeTruthy();
    expect(screen.getAllByText("추정").length).toBeGreaterThan(0);
  });

  it("서버가 계약을 어기고 trade 에 호가를 실어도 표시하지 않는다", () => {
    render(<ReportCard item={{ ...TRADE, ask_price_krw: 9_990_000_000, ask_gap_pct: 42 }} />);
    expect(screen.queryByText(/99억/)).toBeNull();
    expect(screen.queryByText(/\+42\.0%/)).toBeNull();
  });
});

describe("total_score = null", () => {
  it("'점수 없음'으로 표기하고 0 을 그리지 않는다", () => {
    const { container } = render(<ReportCard item={TRADE} />);
    expect(screen.getAllByText("점수 없음").length).toBeGreaterThan(0);
    // 점수 자리에 "0점"·"0.0점"이 절대 나오면 안 된다
    expect(container.textContent).not.toMatch(/\b0(\.0)?점/);
  });

  it("왜 점수가 없는지 이유를 함께 말한다", () => {
    render(<ReportCard item={TRADE} />);
    expect(screen.getByText(/점수를 매길 근거/)).toBeTruthy();
  });
});

describe("판단 보류 — 숨기지 않는다", () => {
  it("입지 데이터 미수집을 접힌 섹션이 아니라 **항상 보이는 자리**에 노출한다", () => {
    render(<ReportCard item={TRADE} />);
    // 접기(details) 안에 묻어두면 "분석했다"는 인상만 남는다 → 전용 배너를 확인한다.
    const banner = screen.getByRole("list", { name: "판단 보류 항목" });
    expect(within(banner).getByText("지역 전문가")).toBeTruthy();
    expect(within(banner).getByText(/입지 데이터\(학군·교통·인프라\) 미수집/)).toBeTruthy();
    expect(within(banner).getByText("판단 보류")).toBeTruthy();
  });

  it("동 근거가 없으면 동별도 판단 보류로 말한다", () => {
    render(<ReportCard item={{ ...TRADE, dong_valuation: null }} />);
    expect(screen.getByText("동별 판단 보류")).toBeTruthy();
  });
});

describe("리스크 섹션", () => {
  it("0건이어도 섹션을 감추지 않는다", () => {
    render(<ReportCard item={{ ...TRADE, why_not: [], findings: [] }} />);
    const warn = screen.getByText("확인할 점").closest("details");
    expect(warn).toBeTruthy();
    // 섹션이 남아 있고, 그 안이 "없음"으로 표시된다(감추지 않는다).
    expect(warn?.textContent).toContain("없음");
    expect(warn?.textContent).toContain("확인된 하방 리스크 없음");
  });
});

/**
 * 내 조건(가중치) 반영 — api-spec §5.3.
 *
 * 서버가 근거 있는 축만 총점에 넣고 나머지 가중치를 재정규화한다. 그 사실을 화면이
 * 말하지 않으면 **재정규화 자체가 거짓말**이 된다: 사용자는 자기가 준 30% 가 반영된 줄 안다.
 */
const WEIGHTED: RecommendationItem = {
  ...TRADE,
  total_score: 62.8,
  score_basis: "user_weighted",
  score_coverage_pct: 52,
  score_notes: [
    "입지 가중치 30%가 반영되지 않았습니다 — 학구도 데이터 미확보",
    "리스크 축은 매물 신뢰도까지만 봅니다 — 권리관계·근저당 분석(risk-auditor)은 2차 기능입니다.",
  ],
  score_axes: [
    {
      axis: "value",
      label: "가치(시세)",
      agent_ids: ["valuation-trader"],
      // ⚠️ 서버 원문에는 내부 식별자가 섞여 있다 — 화면에 그대로 나가면 안 된다
      signal: "12개월 거래회전율 기반 환금성(liquidity.turnover_12m_pct)",
      coverage: "partial",
      coverage_gap:
        "동별 가격 편차(dong_valuation)는 후보 점수로 환산하지 않고 참고 정보로만 제공합니다.",
      weight: 0.35,
      applied_weight: 0.67,
      score: 62.8,
      status: "applied",
      missing: [],
    },
    {
      axis: "price",
      label: "가격",
      agent_ids: ["valuation-trader"],
      signal: "호가 − 적정가 밴드 중위 갭(ask_gap_pct)",
      coverage: "full",
      coverage_gap: null,
      weight: 0.17,
      applied_weight: 0.33,
      score: 40,
      status: "applied",
      missing: [],
    },
    {
      axis: "location",
      label: "입지",
      agent_ids: ["location-analyst"],
      signal: "학군·역세권·생활 인프라",
      coverage: "full",
      coverage_gap: null,
      weight: 0.31,
      applied_weight: null,
      score: null,
      status: "no_signal",
      missing: ["학구도 데이터 미확보"],
    },
    {
      axis: "risk",
      label: "리스크",
      agent_ids: ["listing-researcher"],
      signal: "매물 신뢰도",
      coverage: "partial",
      coverage_gap:
        "권리관계·근저당·재건축 추가분담금·깡통전세 분석(risk-auditor)은 2차 기능이라 들어가지 않습니다.",
      weight: 0,
      applied_weight: null,
      score: null,
      status: "zero_weight",
      missing: [],
    },
  ],
};

/**
 * 평가 반영률 — 사용자가 준 가중치가 실제로 얼마나 쓰였는가.
 *
 * ⛔ 이 한 줄만은 **절대 접지 않는다.** 가격 가중치를 31% 로 준 사람이 그게 반영되지
 *    않았다는 걸 모르면, 지금 순위를 "내가 설정한 대로 나온 순위"로 읽는다.
 */
describe("평가 반영률 — 접히지 않는 헤드라인", () => {
  it("부분 반영이면 점수 옆에 그 사실을 붙인다(계약: 100% 미만 표기 필수)", () => {
    render(<ReportCard item={WEIGHTED} />);

    expect(screen.getByText("62.8점")).toBeTruthy();
    expect(screen.getByText("내 조건 52%만 반영")).toBeTruthy();
  });

  it("반영률 문장은 details 안에 들어가지 않는다(접으면 오해가 된다)", () => {
    render(<ReportCard item={WEIGHTED} />);

    const head = screen.getByText(/설정하신 가중치의 52%만 반영됐습니다/);
    // 이 문장이 접기 안으로 들어가는 순간 계약이 깨진다 — 조상에 details 가 있으면 실패
    expect(head.closest("details")).toBeNull();
  });

  it("왜 그런지 한 줄로 함께 말한다 — 축 이름 기반(서버 문장을 잘라 붙이지 않는다)", () => {
    render(<ReportCard item={WEIGHTED} />);
    const why = screen.getByText(/입지 항목을 판단할 근거가 없어서입니다/);
    expect(why.closest("details")).toBeNull();
  });

  it("100% 반영이면 경고를 띄우지 않는다(항상 뜨는 경고는 아무도 안 읽는다)", () => {
    render(<ReportCard item={{ ...WEIGHTED, score_coverage_pct: 100 }} />);
    expect(screen.queryByText(/만 반영됐습니다/)).toBeNull();
    expect(screen.queryByText(/만 반영/)).toBeNull();
    // 그래도 상세는 남는다 — 궁금하면 열어 볼 수 있어야 한다
    expect(screen.getByText("평가 상세")).toBeTruthy();
  });

  it("절반도 못 미치면 톤이 한 단계 올라간다(문장도 함께 바뀐다 — 색만으로 구분 금지)", () => {
    const { container } = render(<ReportCard item={{ ...WEIGHTED, score_coverage_pct: 25 }} />);
    expect(screen.getByText(/25%만 반영됐습니다 — 절반도 반영되지 않았습니다/)).toBeTruthy();
    expect(container.querySelector(".cov--low")).toBeTruthy();
  });

  it("반영률을 서버가 안 주면 단정하지 않는다(경고도 없다)", () => {
    render(<ReportCard item={{ ...WEIGHTED, score_coverage_pct: undefined }} />);
    expect(screen.queryByText(/만 반영됐습니다/)).toBeNull();
    expect(screen.getByText("평가 상세")).toBeTruthy();
  });
});

describe("평가 상세 — 접기/펼치기", () => {
  it("기본은 접혀 있고, 눌러서 펼칠 수 있다", async () => {
    const user = userEvent.setup();
    render(<ReportCard item={WEIGHTED} />);

    const summary = screen.getByText("평가 상세");
    const details = summary.closest("details") as HTMLDetailsElement;
    expect(details.open).toBe(false);

    await user.click(summary);
    expect(details.open).toBe(true);
  });

  it("반영됨 · 미반영을 비중과 함께 나눠 보여준다", () => {
    render(<ReportCard item={WEIGHTED} />);
    const details = screen.getByText("평가 상세").closest("details");

    expect(details?.textContent).toContain("반영됨");
    expect(details?.textContent).toContain("미반영");
    expect(details?.textContent).toContain("가치(시세)");
    expect(details?.textContent).toContain("35%");
    expect(details?.textContent).toContain("입지");
    expect(details?.textContent).toContain("31%");
    // 합계까지 적어야 "52%"가 어디서 나온 숫자인지 검증할 수 있다
    expect(details?.textContent).toContain("합계");
  });

  it("왜 못 봤는지 사유를 축별로 적는다", () => {
    render(<ReportCard item={WEIGHTED} />);
    const details = screen.getByText("평가 상세").closest("details");
    expect(details?.textContent).toContain("왜 못 봤나요");
    expect(details?.textContent).toContain("학구도 데이터 미확보");
  });

  it("점수를 어떻게 냈는지(재정규화) 평이한 말로 적는다", () => {
    render(<ReportCard item={WEIGHTED} />);
    expect(screen.getByText(/다시 100% 기준을 잡아 계산했습니다/)).toBeTruthy();
  });

  it("반영됐어도 남는 한계는 '아직 못 보는 것'으로 적는다", () => {
    render(<ReportCard item={WEIGHTED} />);
    const details = screen.getByText("평가 상세").closest("details");
    expect(details?.textContent).toContain("아직 못 보는 것");
    expect(details?.textContent).toContain("동별 가격 편차는 후보 점수로 환산하지 않고");
  });

  it("내가 0% 로 둔 축은 '빠졌다'가 아니라 '안 봤다'로 말한다", () => {
    render(<ReportCard item={WEIGHTED} />);
    expect(screen.getByText(/내가 0% 로 둔 항목/)).toBeTruthy();
    expect(screen.getByText(/리스크 — 처음부터 점수에 넣지 않았습니다/)).toBeTruthy();
    // 미반영(근거 없음)과 섞이면 안 된다
    const details = screen.getByText("평가 상세").closest("details");
    const missing = within(details as HTMLElement).getByText("왜 못 봤나요").parentElement;
    expect(missing?.textContent).not.toContain("리스크");
  });

  it("agent_scores 폴백은 '내 가중치 점수'라고 말하지 않는다", () => {
    render(<ReportCard item={{ ...WEIGHTED, score_basis: "agent_scores" }} />);
    expect(screen.getByText(/전문가 신뢰도 평균으로 매겨졌습니다/)).toBeTruthy();
  });

  it("서버가 축 정보를 안 주면 블록 자체를 만들지 않는다(없는 걸 지어내지 않는다)", () => {
    render(<ReportCard item={TRADE} />);
    expect(screen.queryByText("평가 상세")).toBeNull();
  });

  it("축 정보가 없고 고지 문구만 오면 그 문구를 그대로 남긴다(구버전 폴백)", () => {
    render(
      <ReportCard
        item={{ ...TRADE, score_axes: null, score_notes: ["입지 가중치 30%가 반영되지 않았습니다"] }}
      />,
    );
    const notes = screen.getByRole("list", { name: "점수에 반영되지 않은 항목" });
    expect(within(notes).getByText(/입지 가중치 30%가 반영되지 않았습니다/)).toBeTruthy();
  });
});

describe("내부 식별자는 화면에 나가지 않는다", () => {
  it("liquidity.turnover_12m_pct · dong_valuation · risk-auditor 가 보이지 않는다", () => {
    const { container } = render(<ReportCard item={WEIGHTED} />);
    const text = container.textContent ?? "";
    expect(text).not.toContain("liquidity.turnover_12m_pct");
    expect(text).not.toContain("dong_valuation");
    expect(text).not.toContain("risk-auditor");
    expect(text).not.toContain("ask_gap_pct");
  });

  it("식별자를 지워도 문장의 뜻은 남는다", () => {
    render(<ReportCard item={WEIGHTED} />);
    expect(screen.getByText(/권리관계·근저당·재건축 추가분담금·깡통전세 분석은 2차 기능이라/))
      .toBeTruthy();
  });
});
