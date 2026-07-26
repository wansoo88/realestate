import { describe, expect, it } from "vitest";
import {
  DEFAULT_WEIGHTS,
  SERVER_APPLIES_WEIGHTS,
  WEIGHT_KEYS,
  WEIGHT_META,
  isWeightAdjustable,
  normalizeWeights,
  weightStatus,
  weightStatusNote,
  weightsApplied,
} from "./preferences";

describe("normalizeWeights", () => {
  it("합이 1 이 되게 맞춘다(사용자에게 100 맞추기를 시키지 않는다)", () => {
    const w = normalizeWeights({ price: 50, location: 25, value: 15, risk: 10 });
    expect(w.price).toBeCloseTo(0.5, 4);
    const sum = w.price + w.location + w.value + w.risk;
    expect(sum).toBeCloseTo(1, 3);
  });

  it("전부 0 이면 기본값으로 되돌린다(0 나눗셈·무의미한 가중치 방지)", () => {
    expect(normalizeWeights({ price: 0, location: 0, value: 0, risk: 0 })).toEqual(DEFAULT_WEIGHTS);
    expect(normalizeWeights(undefined)).toEqual(DEFAULT_WEIGHTS);
  });

  it("음수·NaN 은 0 으로 본다", () => {
    const w = normalizeWeights({ price: -5, location: Number.NaN, value: 1, risk: 1 });
    expect(w.price).toBe(0);
    expect(w.location).toBe(0);
    expect(w.value).toBeCloseTo(0.5, 4);
  });
});

/**
 * 가중치 설명·상태 (api-spec §5.3 · scoring.py AXIS_SPECS 가 정본).
 *
 * 여기서 지키는 것은 문구가 아니라 **정직성**이다:
 *  · 축이 실제로 보는 신호를 넘겨 말하지 않는다(partial 축의 한계를 늘 밝힌다)
 *  · "근거가 지금 있는가"는 하드코딩하지 않는다(관측값으로 판단한다)
 */
describe("가중치 설명", () => {
  it("네 항목 모두 설명·신호·담당 전문가를 가진다(빈 설명 금지)", () => {
    for (const key of WEIGHT_KEYS) {
      const meta = WEIGHT_META[key];
      expect(meta.tagline.length).toBeGreaterThan(0);
      expect(meta.summary.length).toBeGreaterThan(0);
      expect(meta.detail.length).toBeGreaterThan(meta.summary.length);
      expect(meta.signal.length).toBeGreaterThan(0);
      expect(meta.agent.length).toBeGreaterThan(0);
    }
  });

  it("'가격'과 '가치'가 서로 다른 질문임이 드러난다(사용자 지적의 핵심)", () => {
    // 가격 = 지금 이 호가가 적정가보다 싼가 / 가치 = 잘 팔리는가(환금성)
    expect(WEIGHT_META.price.summary).toContain("호가");
    expect(WEIGHT_META.price.signal).toContain("적정가");
    expect(WEIGHT_META.value.summary).toContain("회전율");
    expect(WEIGHT_META.value.tagline).toContain("환금성");
    expect(WEIGHT_META.price.tagline).not.toBe(WEIGHT_META.value.tagline);
  });

  it("축 설명이 서버 AXIS_SPECS 와 같은 신호를 말한다", () => {
    expect(WEIGHT_META.price.agent).toContain("valuation-trader");
    expect(WEIGHT_META.location.agent).toContain("location-analyst");
    expect(WEIGHT_META.value.agent).toContain("valuation-trader");
    // 리스크 점수는 risk-auditor 가 아니라 **매물 리서처**가 만든다(오해 지점)
    expect(WEIGHT_META.risk.agent).toContain("listing-researcher");
  });

  it("partial 축은 **무엇이 빠졌는지**를 반드시 갖는다", () => {
    expect(WEIGHT_META.value.coverage).toBe("partial");
    expect(WEIGHT_META.value.coverageGap).toContain("동별");
    expect(WEIGHT_META.risk.coverage).toBe("partial");
    // "호가만 들어오면 리스크가 다 반영된다"는 오해를 막는 문장이 반드시 있어야 한다
    expect(WEIGHT_META.risk.coverageGap).toContain("권리관계");
    expect(WEIGHT_META.risk.coverageGap).toContain("호가가 들어와도");
  });

  it("full 축은 빠진 것이 없으므로 gap 문구를 만들지 않는다", () => {
    expect(WEIGHT_META.price.coverage).toBe("full");
    expect(WEIGHT_META.price.coverageGap).toBeNull();
    expect(WEIGHT_META.location.coverage).toBe("full");
    expect(WEIGHT_META.location.coverageGap).toBeNull();
  });
});

describe("가중치 반영 여부 — 단일 판단 지점", () => {
  it("서버가 가중치를 실제로 반영한다(WEIGHT-1 이후)", () => {
    expect(SERVER_APPLIES_WEIGHTS).toBe(true);
    expect(weightStatus("price")).toBe("applied");
    expect(weightStatus("location")).toBe("applied");
  });

  it("'agent_scores' 는 가중치 점수가 아니다 — 그렇게 표시하면 계약 위반", () => {
    expect(weightsApplied("agent_scores")).toBe(false);
    expect(weightStatus("price", { scoreBasis: "agent_scores" })).toBe("not_scored_yet");
  });

  it("서버가 user_weighted 라고 하면 그대로 믿는다", () => {
    expect(weightsApplied("user_weighted")).toBe(true);
    expect(weightStatus("value", { scoreBasis: "user_weighted" })).toBe("applied");
  });

  it("직전 분석에서 근거가 없던 축은 'no_signal' 이다(관측값 · 하드코딩 아님)", () => {
    // 운영 실측(2026-07-26): listing·poi 0행 → 가격·입지·리스크는 근거 0건.
    // 그런데 그건 **데이터 상태**라 바뀔 수 있으므로 코드에 박지 않는다.
    expect(weightStatus("location", { observedNoSignal: true })).toBe("no_signal");
    expect(weightStatus("location", { observedNoSignal: false })).toBe("applied");
    expect(weightStatus("location", { observedNoSignal: undefined })).toBe("applied");
  });

  it("반영되지 않는 상태는 **반드시** 사유 문구를 가진다(조용히 죽지 않는다)", () => {
    expect(weightStatusNote("no_signal", "location")).toContain("입지");
    expect(weightStatusNote("no_signal", "location")).toContain("반영되지 않았습니다");
    expect(weightStatusNote("not_scored_yet")).toContain("저장");
    expect(weightStatusNote("applied")).toBeNull();
  });

  it("이제 네 항목 모두 조작할 수 있다 — 근거가 없으면 잠그는 대신 사유를 적는다", () => {
    expect(isWeightAdjustable()).toBe(true);
    expect(WEIGHT_KEYS).toContain("location");
    expect(WEIGHT_KEYS).toContain("risk");
  });
});
