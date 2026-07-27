/**
 * 반영률 요약 — **구조화된 필드에서만** 만든다.
 * 서버 문장을 잘라 붙이지 않는지, 임계값이 한 곳에 있는지를 못박는다.
 */
import { describe, expect, it } from "vitest";
import type { RecommendationItem, ScoreAxis } from "../api/client";
import { COVERAGE_THRESHOLDS, coverageDetail, coverageTone } from "./scoreCoverage";

function axis(over: Partial<ScoreAxis> & { axis: string }): ScoreAxis {
  return {
    label: over.axis,
    agent_ids: [],
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

const AXES: ScoreAxis[] = [
  axis({ axis: "location", label: "입지", weight: 0.35, applied_weight: 0.67, score: 70, status: "applied" }),
  axis({ axis: "value", label: "가치(시세)", weight: 0.17, applied_weight: 0.33, score: 50, status: "applied" }),
  axis({ axis: "price", label: "가격", weight: 0.31, status: "no_signal", missing: ["활성 호가가 없습니다"] }),
  axis({ axis: "risk", label: "리스크", weight: 0.17, status: "no_signal", missing: ["매물 없음"] }),
];

describe("톤 임계값 — 한 곳에만 있다", () => {
  it("100% 는 경고 없음", () => {
    expect(coverageTone(100)).toBe("full");
    expect(coverageDetail(item({ score_coverage_pct: 100, score_axes: AXES })).warn).toBe(false);
  });

  it("절반 이상~100% 미만은 partial", () => {
    expect(coverageTone(52)).toBe("partial");
    expect(coverageTone(COVERAGE_THRESHOLDS.low)).toBe("partial");
    expect(coverageTone(99)).toBe("partial");
  });

  it("절반 미만은 low(문장도 강해진다)", () => {
    expect(coverageTone(COVERAGE_THRESHOLDS.low - 1)).toBe("low");
    const d = coverageDetail(item({ score_coverage_pct: 25, score_axes: AXES }));
    expect(d.tone).toBe("low");
    expect(d.headline).toContain("절반도 반영되지 않았습니다");
  });

  it("모르면 단정하지 않는다", () => {
    expect(coverageTone(null)).toBe("unknown");
    const d = coverageDetail(item({ score_axes: AXES }));
    expect(d.warn).toBe(false);
    expect(d.headline).toBeNull();
  });
});

describe("반영/미반영 구분", () => {
  const d = coverageDetail(item({ score_coverage_pct: 52, score_axes: AXES }));

  it("반영된 축과 못 한 축을 비중과 함께 나눈다", () => {
    expect(d.applied.map((a) => a.label)).toEqual(["입지", "가치(시세)"]);
    expect(d.dropped.map((a) => a.label)).toEqual(["가격", "리스크"]);
    expect(d.appliedSumPct).toBe(52);
    expect(d.droppedSumPct).toBe(48);
  });

  it("사유 한 줄은 **축 이름**으로 만든다(서버 문장을 파싱하지 않는다)", () => {
    expect(d.reason).toBe("가격 · 리스크 항목을 판단할 근거가 없어서입니다");
  });

  it("내가 0% 로 둔 축은 미반영과 섞이지 않는다", () => {
    const z = coverageDetail(
      item({
        score_coverage_pct: 60,
        score_axes: [
          axis({ axis: "value", label: "가치", weight: 0.6, applied_weight: 1, status: "applied", score: 50 }),
          axis({ axis: "risk", label: "리스크", weight: 0, status: "zero_weight" }),
        ],
      }),
    );
    expect(z.dropped).toEqual([]);
    expect(z.zeroWeight.map((a) => a.label)).toEqual(["리스크"]);
  });
});

describe("내부 식별자 제거", () => {
  it("사유·한계 문구에서 식별자를 걷어낸다", () => {
    const d = coverageDetail(
      item({
        score_coverage_pct: 50,
        score_axes: [
          axis({
            axis: "value",
            label: "가치",
            status: "applied",
            applied_weight: 1,
            score: 50,
            coverage: "partial",
            coverage_gap: "동별 가격 편차(dong_valuation)는 참고 정보입니다.",
          }),
          axis({
            axis: "risk",
            label: "리스크",
            status: "no_signal",
            missing: ["권리관계 분석(risk-auditor) 없음"],
          }),
        ],
      }),
    );
    expect(d.limits[0].text).toBe("동별 가격 편차는 참고 정보입니다.");
    expect(d.reasons[0].text).toBe("권리관계 분석 없음");
  });
});

describe("점수 계산 방식", () => {
  it("빠진 축이 있으면 재정규화를 평이한 말로 적는다", () => {
    const d = coverageDetail(item({ score_coverage_pct: 52, score_axes: AXES }));
    expect(d.method.join(" ")).toContain("다시 100% 기준을 잡아 계산했습니다");
  });

  it("전부 반영되면 재정규화 문장을 만들지 않는다", () => {
    const d = coverageDetail(
      item({
        score_coverage_pct: 100,
        score_axes: [
          axis({ axis: "value", label: "가치", weight: 1, applied_weight: 1, score: 50, status: "applied" }),
        ],
      }),
    );
    expect(d.method.join(" ")).not.toContain("다시 100% 기준");
    expect(d.method.join(" ")).toContain("그대로 점수에 반영");
  });

  it("반영된 축이 하나도 없으면 0점이 아니라 '모름'이라고 말한다", () => {
    const d = coverageDetail(
      item({
        total_score: null,
        score_coverage_pct: 0,
        score_axes: [axis({ axis: "price", label: "가격", status: "no_signal" })],
      }),
    );
    expect(d.method.join(" ")).toContain("0점이 아니라 '모름'");
  });

  it("가중치 폴백이면 '내 가중치 점수'라고 하지 않는다", () => {
    const d = coverageDetail(
      item({ score_basis: "agent_scores", score_coverage_pct: 100, score_axes: AXES }),
    );
    expect(d.method.join(" ")).toContain("전문가 신뢰도 평균");
  });
});

describe("서버가 축 정보를 안 줄 때", () => {
  it("고지 문구만 있으면 원문을 그대로 남긴다(고지가 사라지지 않게)", () => {
    const d = coverageDetail(item({ score_notes: ["입지 가중치 30%가 반영되지 않았습니다"] }));
    expect(d.rawNotes).toEqual(["입지 가중치 30%가 반영되지 않았습니다"]);
    expect(d.hasDetail).toBe(true);
  });

  it("축도 고지도 없으면 블록 자체를 만들지 않는다", () => {
    expect(coverageDetail(item({})).hasDetail).toBe(false);
  });

  it("축 정보가 있으면 그것이 정본이다(원문 고지를 겹쳐 그리지 않는다)", () => {
    const d = coverageDetail(
      item({ score_axes: AXES, score_coverage_pct: 52, score_notes: ["중복될 문구"] }),
    );
    expect(d.rawNotes).toEqual([]);
  });
});
