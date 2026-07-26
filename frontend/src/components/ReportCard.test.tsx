// @vitest-environment jsdom
/**
 * 리포트 카드 — **화면에 나가는 것**을 못박는다.
 *
 * 순수 함수 테스트(lib/recommendation.test.ts)만으로는 부족하다.
 * 컴포넌트가 그 함수를 실제로 쓰는지, 아니면 원본 필드를 몰래 다시 읽는지는
 * DOM 을 봐야 안다.
 */
import { cleanup, render, screen, within } from "@testing-library/react";
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
  score_coverage_pct: 25,
  score_notes: [
    "입지 가중치 30%가 반영되지 않았습니다 — 학구도 데이터 미확보",
    "리스크 축은 매물 신뢰도까지만 봅니다 — 권리관계·근저당 분석은 2차 기능입니다.",
  ],
  score_axes: [
    {
      axis: "value",
      label: "가치(시세)",
      agent_ids: ["valuation-trader"],
      signal: "12개월 거래회전율(환금성)",
      coverage: "partial",
      coverage_gap: "동별 가격 편차는 후보 점수로 환산하지 않습니다.",
      weight: 0.25,
      applied_weight: 1,
      score: 62.8,
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
      weight: 0.3,
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
      coverage_gap: "권리관계·근저당·재건축 추가분담금 분석은 들어가지 않습니다.",
      weight: 0,
      applied_weight: null,
      score: null,
      status: "zero_weight",
      missing: [],
    },
  ],
};

describe("내 조건 반영 (가중치)", () => {
  it("부분 반영이면 점수 옆에 그 사실을 붙인다(계약: 100% 미만 표기 필수)", () => {
    render(<ReportCard item={WEIGHTED} />);

    expect(screen.getByText("62.8")).toBeTruthy();
    expect(screen.getByText("내 조건 25%만 반영")).toBeTruthy();
  });

  it("100% 반영이면 군더더기를 붙이지 않는다", () => {
    render(<ReportCard item={{ ...WEIGHTED, score_coverage_pct: 100 }} />);
    expect(screen.queryByText(/만 반영/)).toBeNull();
  });

  it("후보별 고지(score_notes)를 결과 전체 notes 와 **양쪽 다** 보여준다", () => {
    render(<ReportCard item={WEIGHTED} />);

    const notes = screen.getByRole("list", { name: "점수에 반영되지 않은 항목" });
    expect(within(notes).getByText(/입지 가중치 30%가 반영되지 않았습니다/)).toBeTruthy();
  });

  it("반영된 축 · 빠진 축 · 내가 0 준 축을 **전부** 보여준다", () => {
    render(<ReportCard item={WEIGHTED} />);
    const section = screen.getByText("내 조건 반영").closest("details");

    expect(section?.textContent).toContain("가치(시세)");
    expect(section?.textContent).toContain("입지");
    expect(section?.textContent).toContain("리스크");
    // 빠진 축은 사유와 함께
    expect(section?.textContent).toContain("학구도 데이터 미확보");
    // 사용자가 0 을 준 축은 "빠졌다"가 아니라 "안 봤다"로 말한다
    expect(section?.textContent).toContain("0% 로 둔 항목");
  });

  it("재정규화로 실효 비중이 달라지면 그 값을 함께 적는다", () => {
    render(<ReportCard item={WEIGHTED} />);
    expect(screen.getByText(/실제 100%/)).toBeTruthy();
  });

  it("partial 축의 한계는 **반영됐어도** 적는다", () => {
    render(<ReportCard item={WEIGHTED} />);
    // 가치 축은 반영됐지만 동별 편차는 안 본다 — 그 경계를 말해야 한다
    expect(screen.getByText(/동별 가격 편차는 후보 점수로 환산하지 않습니다/)).toBeTruthy();
  });

  it("agent_scores 폴백은 '내 가중치 점수'라고 말하지 않는다", () => {
    render(<ReportCard item={{ ...WEIGHTED, score_basis: "agent_scores" }} />);
    expect(screen.getByText(/전문가 신뢰도 평균으로 매겨졌습니다/)).toBeTruthy();
  });

  it("서버가 축 정보를 안 주면 섹션을 만들지 않는다(없는 걸 지어내지 않는다)", () => {
    render(<ReportCard item={TRADE} />);
    expect(screen.queryByText("내 조건 반영")).toBeNull();
  });
});
