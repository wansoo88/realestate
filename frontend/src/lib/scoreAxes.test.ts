/**
 * 축별 반영 결과 (api-spec §5.3).
 *
 * 여기서 못박는 계약 두 가지:
 *  ① `score_coverage_pct < 100` 이면 점수 옆 **부분 반영 표기**가 나와야 한다
 *  ② `score_basis === "agent_scores"` 는 가중치 점수가 **아니다**
 */
import { beforeEach, describe, expect, it } from "vitest";
import type { RecommendationItem, ScoreAxis } from "../api/client";
import {
  axisViews,
  coverageView,
  forgetAxisGaps,
  observedNoSignal,
  rememberAxisGaps,
  unscoredAxes,
} from "./scoreAxes";

function axis(over: Partial<ScoreAxis> & { axis: string }): ScoreAxis {
  return {
    label: over.axis,
    agent_ids: ["valuation-trader"],
    signal: "신호",
    coverage: "full",
    coverage_gap: null,
    weight: 0.25,
    applied_weight: null,
    score: null,
    status: "no_signal",
    missing: [],
    ...over,
  };
}

function item(over: Partial<RecommendationItem> = {}): RecommendationItem {
  return {
    complex: { id: 1, name: "단지" },
    unit_type: null,
    building: null,
    dong_valuation: null,
    price_basis: "trade",
    ask_price_krw: null,
    est_price_krw: 1_000_000_000,
    price_estimated: true,
    price_note: null,
    ask_gap_pct: null,
    price_band: null,
    total_score: 62.8,
    score_basis: "user_weighted",
    timing_signal: "",
    headline: "",
    why: [],
    why_not: [],
    next_actions: [],
    findings: [],
    ...over,
  };
}

beforeEach(() => forgetAxisGaps());

describe("coverageView — 부분 반영 표기(계약)", () => {
  it("100% 미만이면 점수 옆에 붙일 표기를 만든다", () => {
    const v = coverageView(item({ score_coverage_pct: 25 }));
    expect(v.partial).toBe(true);
    expect(v.badge).toContain("25%");
  });

  it("100% 면 표기가 없다(할 말이 없을 때 말하지 않는다)", () => {
    const v = coverageView(item({ score_coverage_pct: 100 }));
    expect(v.partial).toBe(false);
    expect(v.badge).toBeNull();
  });

  it("서버가 커버리지를 안 주면 부분 반영이라고 단정하지 않는다", () => {
    const v = coverageView(item({}));
    expect(v.pct).toBeNull();
    expect(v.partial).toBe(false);
  });

  it("agent_scores 는 사용자 가중치 점수가 아니다", () => {
    expect(coverageView(item({ score_basis: "agent_scores" })).userWeighted).toBe(false);
    expect(coverageView(item({ score_basis: "user_weighted" })).userWeighted).toBe(true);
  });
});

describe("axisViews", () => {
  it("반영된 축 → 못 한 축 → 내가 0 준 축 순서로 보여주되 **아무것도 빼지 않는다**", () => {
    const rows = axisViews(
      item({
        score_axes: [
          axis({ axis: "price", status: "no_signal" }),
          axis({ axis: "risk", status: "zero_weight", weight: 0 }),
          axis({ axis: "value", status: "applied", score: 62.8, applied_weight: 1 }),
        ],
      }),
    );

    expect(rows.map((r) => r.axis)).toEqual(["value", "price", "risk"]);
    expect(rows).toHaveLength(3);
  });

  it("재정규화된 실효 비중을 퍼센트로 옮긴다", () => {
    const [row] = axisViews(
      item({ score_axes: [axis({ axis: "value", status: "applied", weight: 0.25, applied_weight: 1 })] }),
    );
    expect(row.weightPct).toBe(25);
    expect(row.appliedPct).toBe(100);
  });

  it("반영 못 한 축은 실효 비중이 null 이다 — 0% 로 적으면 '내가 0 을 줬다'로 읽힌다", () => {
    const [row] = axisViews(item({ score_axes: [axis({ axis: "price", status: "no_signal" })] }));
    expect(row.appliedPct).toBeNull();
    expect(row.applied).toBe(false);
    expect(row.zeroWeight).toBe(false);
  });

  it("partial 축의 한계는 **반영됐어도** 실려 나온다", () => {
    const [row] = axisViews(
      item({
        score_axes: [
          axis({
            axis: "risk",
            status: "applied",
            coverage: "partial",
            coverage_gap: "권리관계는 빠집니다",
            score: 70,
          }),
        ],
      }),
    );
    expect(row.applied).toBe(true);
    expect(row.coverageGap).toBe("권리관계는 빠집니다");
  });

  it("full 축은 한계 문구를 만들지 않는다", () => {
    const [row] = axisViews(
      item({ score_axes: [axis({ axis: "price", coverage: "full", coverage_gap: "무시돼야 함" })] }),
    );
    expect(row.coverageGap).toBeNull();
  });

  it("서버가 축 정보를 안 주면 빈 목록(없는 걸 지어내지 않는다)", () => {
    expect(axisViews(item({}))).toEqual([]);
  });
});

describe("관측 기억 — 조건 화면이 하드코딩 없이 현실을 말한다", () => {
  it("분석 전에는 아무것도 단정하지 않는다", () => {
    expect(observedNoSignal("location")).toBeUndefined();
  });

  it("근거가 없던 축을 기억한다", () => {
    rememberAxisGaps([
      item({
        score_axes: [
          axis({ axis: "location", status: "no_signal" }),
          axis({ axis: "value", status: "applied", score: 60 }),
        ],
      }),
    ]);

    expect(observedNoSignal("location")).toBe(true);
    expect(observedNoSignal("value")).toBe(false);
  });

  it("한 후보에서라도 반영됐으면 '근거 없음'이라고 말하지 않는다", () => {
    // 커버리지는 후보마다 다르다(호가가 있는 후보만 가격 축이 산다) — 과장하지 않는다.
    rememberAxisGaps([
      item({ score_axes: [axis({ axis: "price", status: "no_signal" })] }),
      item({ score_axes: [axis({ axis: "price", status: "applied", score: 80 })] }),
    ]);

    expect(observedNoSignal("price")).toBe(false);
  });

  it("서버가 축 정보를 안 주면 기억하지 않는다(모름 상태를 유지)", () => {
    rememberAxisGaps([item({})]);
    expect(observedNoSignal("price")).toBeUndefined();
  });

  it("잊으면 다시 '모름'으로 돌아간다", () => {
    rememberAxisGaps([item({ score_axes: [axis({ axis: "risk", status: "no_signal" })] })]);
    forgetAxisGaps();
    expect(observedNoSignal("risk")).toBeUndefined();
  });
});

describe("unscoredAxes", () => {
  it("근거가 없어 빠진 축만 고른다", () => {
    const codes = unscoredAxes(
      item({
        score_axes: [
          axis({ axis: "price", status: "no_signal" }),
          axis({ axis: "value", status: "applied" }),
          axis({ axis: "risk", status: "zero_weight" }),
        ],
      }),
    );
    // 사용자가 0 을 준 축은 '빠진 것'이 아니다 — 안 본 것이다.
    expect(codes).toEqual(["price"]);
  });
});
