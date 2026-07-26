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
