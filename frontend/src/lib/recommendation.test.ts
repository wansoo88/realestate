/**
 * 정직한 렌더링 계약 테스트 (api-spec §5·§5.1).
 *
 * 여기 있는 단언은 스타일이 아니라 **계약**이다:
 *  · 실거래 중위가가 호가로 둔갑하지 않는다
 *  · 점수 없음(null)이 0(나쁨)으로 바뀌지 않는다
 *  · 출처 없는 근거는 근거로 세지 않는다
 */
import { describe, expect, it } from "vitest";
import type { Finding, PriceBand, RecommendationItem } from "../api/client";
import {
  bandTimeView,
  dongView,
  findingView,
  jobPhase,
  llmSummaryActive,
  priceView,
  progressText,
  resolvePollPath,
  scoreView,
  summaryBasisView,
  usableEvidence,
} from "./recommendation";

function item(over: Partial<RecommendationItem> = {}): RecommendationItem {
  return {
    rank: 1,
    complex: { id: 1, name: "○○아파트" },
    unit_type: { area_m2: 84.97 },
    building: null,
    dong_valuation: null,
    price_basis: "listing",
    ask_price_krw: 1_480_000_000,
    est_price_krw: 1_480_000_000,
    price_estimated: false,
    price_note: null,
    ask_gap_pct: 5.7,
    price_band: null,
    total_score: 82.4,
    score_basis: "agent_scores",
    timing_signal: "unknown",
    headline: "요약",
    why: [],
    why_not: [],
    next_actions: [],
    findings: [],
    ...over,
  };
}

/**
 * CR31-2 — 요약을 누가 썼는가(`summary_basis`)가 화면에 닿아야 한다.
 *
 * 서버는 AI 요약이 분담금 표현을 쓰면 **요약 전체를 폐기**하고 규칙 문장으로 강등한다.
 * 그 사실이 화면에 안 닿으면 사용자는 강등된 걸 모른다. 반대로 LLM 미연결이라 전부
 * 규칙 기반인 상태에서 카드마다 경고를 띄우면 아무도 안 읽는다 — 그건 job 고지가 말한다.
 */
describe("summaryBasisView — 강등은 알리되 소음은 만들지 않는다", () => {
  it("AI 가 돌았는데 이 카드만 규칙 기반이면 알린다", () => {
    const v = summaryBasisView(item({ summary_basis: "fallback" }), { llmActive: true });
    expect(v.degraded).toBe(true);
    expect(v.label).toBe("규칙 기반 요약");
    expect(v.note).toContain("순위");
  });

  it("전부 규칙 기반이면(LLM 미연결) 카드에는 아무 말도 하지 않는다 — job 고지와 중복", () => {
    const v = summaryBasisView(item({ summary_basis: "fallback" }), { llmActive: false });
    expect(v.fallback).toBe(true); // 사실은 사실대로 안다
    expect(v.degraded).toBe(false); // 다만 카드에는 표기하지 않는다
    expect(v.label).toBeNull();
  });

  it("AI 요약 카드에는 표기하지 않는다", () => {
    expect(summaryBasisView(item({ summary_basis: "llm" }), { llmActive: true }).degraded).toBe(
      false,
    );
  });

  it("서버가 값을 안 주면(구버전) 단정하지 않는다", () => {
    const v = summaryBasisView(item(), { llmActive: true });
    expect(v.fallback).toBe(false);
    expect(v.degraded).toBe(false);
  });

  it("한 건이라도 AI 요약이 있으면 LLM 은 살아 있었다고 본다", () => {
    expect(llmSummaryActive([item({ summary_basis: "fallback" })])).toBe(false);
    expect(
      llmSummaryActive([item({ summary_basis: "fallback" }), item({ summary_basis: "llm" })]),
    ).toBe(true);
    expect(llmSummaryActive([])).toBe(false);
    expect(llmSummaryActive(null)).toBe(false);
  });
});

describe("priceView — 호가와 실거래는 같은 숫자가 아니다", () => {
  it("호가 기준이면 호가와 갭을 그대로 쓴다", () => {
    const v = priceView(item());
    expect(v.askKrw).toBe(1_480_000_000);
    expect(v.gapPct).toBe(5.7);
    expect(v.confidence).toBe("confirmed");
    expect(v.estimated).toBe(false);
    expect(v.note).toBeNull();
  });

  it("실거래 기준이면 호가·갭이 없고 추정 표기가 붙는다", () => {
    const v = priceView(
      item({
        price_basis: "trade",
        ask_price_krw: null,
        ask_gap_pct: null,
        est_price_krw: 1_400_000_000,
        price_estimated: true,
        price_note: "현재 등록된 매물이 없습니다 — 최근 실거래 기준 추정가입니다.",
      }),
    );
    expect(v.askKrw).toBeNull();
    expect(v.gapPct).toBeNull();
    expect(v.krw).toBe(1_400_000_000); // 기준가는 있다(추정으로 표시)
    expect(v.confidence).toBe("estimated");
    expect(v.estimated).toBe(true);
    expect(v.note).toContain("최근 실거래 기준");
  });

  it("서버가 실수로 trade 에 호가를 실어 보내도 화면에는 나가지 않는다", () => {
    // 계약을 믿고 그대로 그리면, 계약이 깨진 날 사용자가 속는다.
    const v = priceView(
      item({ price_basis: "trade", ask_price_krw: 9_990_000_000, ask_gap_pct: 42 }),
    );
    expect(v.askKrw).toBeNull();
    expect(v.gapPct).toBeNull();
  });
});

/**
 * CR33-3 — 밴드 중위는 **언제의 가격인가**.
 *
 * 서버는 창 안의 거래를 기준월로 환산한 뒤 밴드를 낸다. 환산된 값을 그냥
 * "국토교통부 실거래가"라고 부르면 원본 체결가로 읽힌다 — 다른 숫자다.
 * 반대로 필드가 없는 응답에서 "보정됨"이라 말하면 **없는 걸 있다고 하는 것**이다.
 */
function band(over: Partial<PriceBand> = {}): PriceBand {
  return {
    p25_krw: 1_380_000_000,
    median_krw: 1_400_000_000,
    p75_krw: 1_450_000_000,
    sample_size: 37,
    period_months: 6,
    expanded: false,
    source: "국토교통부 실거래가",
    ...over,
  };
}

const ADJUSTED = band({
  as_of_ym: "2026-06",
  time_adjusted: true,
  time_adjustment: {
    applied: true,
    reference_ym: "2026-06",
    scope: "sigungu",
    region_code: "11680",
    shift_pct: 4.2,
    coverage_pct: 96.7,
    sample_size: 37,
    basis: "trade_time_adjusted",
    reason: null,
  },
});

const NOT_ADJUSTED = band({
  as_of_ym: null,
  time_adjusted: false,
  time_adjustment: {
    applied: false,
    reference_ym: "2026-06",
    scope: "sido",
    coverage_pct: 41.2,
    reason: "거래 시점의 지수 확보율이 낮아 시점 보정을 하지 않았습니다",
  },
});

describe("bandTimeView — 보정됨 / 보정 안 됨 / 모름", () => {
  it("보정됐으면 기준월을 밝힌다", () => {
    const v = bandTimeView(ADJUSTED);
    expect(v.adjusted).toBe(true);
    expect(v.unknown).toBe(false);
    expect(v.asOfYm).toBe("2026-06");
    expect(v.label).toBe("2026-06 시점 환산");
  });

  it("⛔ '현재 시세'라고 쓰지 않는다 — 기준월은 오늘이 아니라 완결된 가장 최근 달이다", () => {
    expect(bandTimeView(ADJUSTED).label).not.toContain("현재");
    expect(bandTimeView(ADJUSTED).label).not.toContain("시세");
  });

  it("보정 안 됐으면 그 사실과 사유를 말한다", () => {
    const v = bandTimeView(NOT_ADJUSTED);
    expect(v.adjusted).toBe(false);
    expect(v.unknown).toBe(false);
    expect(v.label).toBe("시점 보정 없음");
    expect(v.detail).toContain("특정 시점의 가격이 아닙니다");
    expect(v.detail).toContain("지수 확보율이 낮아");
  });

  it("사유가 없어도 '어느 시점도 아니다'라는 사실은 말한다", () => {
    const v = bandTimeView(band({ time_adjusted: false, time_adjustment: { applied: false } }));
    expect(v.label).toBe("시점 보정 없음");
    expect(v.detail).toBe("기간 내 거래를 시점 구분 없이 섞은 값이라 특정 시점의 가격이 아닙니다.");
  });

  it("★ 필드가 아예 없으면(구버전 응답) 아무것도 주장하지 않는다", () => {
    const v = bandTimeView(band());
    expect(v.unknown).toBe(true);
    expect(v.adjusted).toBe(false);
    expect(v.label).toBeNull();
    expect(v.detail).toBeNull();
  });

  it("밴드 자체가 없어도 같다(침묵)", () => {
    expect(bandTimeView(null).unknown).toBe(true);
    expect(bandTimeView(undefined).adjusted).toBe(false);
  });

  it("두 필드가 어긋나면 보정을 주장하지 않는다(서버 결함 방어)", () => {
    // time_adjusted 만 true, 실제 결과는 미적용 → 안 한 보정을 했다고 말하면 안 된다
    const v = bandTimeView(
      band({ as_of_ym: "2026-06", time_adjusted: true, time_adjustment: { applied: false } }),
    );
    expect(v.adjusted).toBe(false);
    expect(v.asOfYm).toBeNull();
  });

  it("time_adjustment 없이 time_adjusted 만 와도 보정 사실은 인정한다(기준월은 as_of_ym)", () => {
    const v = bandTimeView(band({ as_of_ym: "2026-05", time_adjusted: true }));
    expect(v.adjusted).toBe(true);
    expect(v.label).toBe("2026-05 시점 환산");
  });

  it("보정됐는데 기준월이 이상하면 월을 지어내지 않는다", () => {
    const v = bandTimeView(
      band({ as_of_ym: "언젠가", time_adjusted: true, time_adjustment: { applied: true } }),
    );
    expect(v.adjusted).toBe(true);
    expect(v.asOfYm).toBeNull();
    expect(v.label).toBe("시점 환산(기준월 미상)");
  });

  it("as_of_ym 이 비어도 time_adjustment.reference_ym 으로 기준월을 찾는다", () => {
    const v = bandTimeView(
      band({ time_adjusted: true, time_adjustment: { applied: true, reference_ym: "2026-06" } }),
    );
    expect(v.label).toBe("2026-06 시점 환산");
  });

  it("사유가 내부 코드면 화면에 내지 않는다(plainReason 경유)", () => {
    const v = bandTimeView(
      band({ time_adjusted: false, time_adjustment: { applied: false, reason: "IDX_ERR_42" } }),
    );
    expect(v.detail).not.toContain("IDX_ERR_42");
  });
});

describe("priceView 라벨 — 보정값을 원본 실거래가라 부르지 않는다", () => {
  const trade = (b: PriceBand | null) =>
    item({
      price_basis: "trade",
      ask_price_krw: null,
      ask_gap_pct: null,
      est_price_krw: 1_400_000_000, // = 밴드 중위(서버 reference_price_krw)
      price_estimated: true,
      price_band: b,
    });

  it("★ 보정된 중위가 기준가면 라벨도 기준월을 말한다", () => {
    expect(priceView(trade(ADJUSTED)).label).toBe("2026-06 시점 환산 추정가");
  });

  it("보정 안 됐으면 예전 문구 그대로다", () => {
    expect(priceView(trade(NOT_ADJUSTED)).label).toBe("최근 실거래 기준 추정가");
  });

  it("★ 필드가 없으면 보정을 주장하지 않는다", () => {
    expect(priceView(trade(band())).label).toBe("최근 실거래 기준 추정가");
    expect(priceView(trade(null)).label).toBe("최근 실거래 기준 추정가");
  });

  it("기준가가 밴드 중위가 아니면 그 숫자에 대해 환산을 주장하지 않는다", () => {
    // 라벨은 **화면에 뜬 숫자**에 대한 주장이다 — 근거를 잃으면 조용히 물러선다
    const v = priceView({ ...trade(ADJUSTED), est_price_krw: 1_230_000_000 });
    expect(v.label).toBe("최근 실거래 기준 추정가");
  });

  it("호가 기준 후보는 밴드가 환산돼도 여전히 '호가'다(호가는 환산 대상이 아니다)", () => {
    expect(priceView(item({ price_band: ADJUSTED })).label).toBe("호가");
  });
});

describe("scoreView — 0(나쁨)과 null(모름)은 다르다", () => {
  it("점수가 없으면 '점수 없음' 이고 0 이 아니다", () => {
    const v = scoreView(item({ total_score: null, score_basis: null }));
    expect(v.known).toBe(false);
    expect(v.value).toBeNull();
    expect(v.text).toBe("점수 없음");
    expect(v.text).not.toContain("0");
  });

  it("0 점은 '모름'이 아니라 그대로 0 점이다", () => {
    const v = scoreView(item({ total_score: 0 }));
    expect(v.known).toBe(true);
    expect(v.text).toBe("0.0점");
  });

  it("점수가 있으면 소수 한 자리로 표기한다", () => {
    expect(scoreView(item({ total_score: 82.44 })).text).toBe("82.4점");
  });
});

describe("dongView — 실측/추정/보류를 구분한다 (F4)", () => {
  it("basis=trade_measured 면 실측", () => {
    const v = dongView({
      available: true,
      method: "실측(aptDong)",
      basis: "trade_measured",
      confidence: 0.85,
      coverage_pct: 87,
      dongs: [{ dong: "101", vs_complex_pct: 5.2, sample: 12, median_ppm_krw: 16_800_000 }],
    });
    expect(v.measured).toBe(true);
    expect(v.label).toContain("실측");
    expect(v.dongs).toHaveLength(1);
  });

  it("available=false 면 판단 보류 — 서버가 준 사유를 그대로 쓴다", () => {
    const v = dongView({
      available: false,
      method: "동표본부족",
      confidence: 0,
      reason: "동별 표본이 3건 미만입니다",
    });
    expect(v.available).toBe(false);
    expect(v.measured).toBe(false);
    expect(v.detail).toBe("동별 표본이 3건 미만입니다");
  });

  it("아예 없으면(null) 근거 없음으로 본다 — 추정하지 않는다", () => {
    expect(dongView(null).available).toBe(false);
    expect(dongView(null).measured).toBe(false);
  });

  it("available 이어도 실측 basis 가 아니면 추정으로 낮춰 표기한다", () => {
    const v = dongView({
      available: true,
      method: "좌표추정",
      basis: "estimated_from_location",
      confidence: 0.5,
    });
    expect(v.measured).toBe(false);
    expect(v.label).toContain("추정");
  });
});

describe("근거 — 출처 없는 주장은 근거가 아니다 (G2)", () => {
  it("source 도 data_rows 도 없으면 버린다", () => {
    const kept = usableEvidence([
      { claim: "취득세 1.1%", source: "지방세법 §11" },
      { claim: "그냥 좋음" },
      { claim: "중위 14억", data_rows: 37 },
    ]);
    expect(kept.map((e) => e.claim)).toEqual(["취득세 1.1%", "중위 14억"]);
  });

  it("missing 이 있는 finding 은 판단 보류로 표시된다", () => {
    const f: Finding = {
      agent_id: "location-analyst",
      verdict: "판단 보류",
      rationale: "판단에 필요한 데이터가 부족합니다",
      evidence: [],
      risks: [],
      score: null,
      confidence: 0,
      basis: null,
      missing: ["입지 데이터(학군·교통·인프라) 미수집"],
    };
    const v = findingView(f);
    expect(v.pending).toBe(true);
    expect(v.scoreText).toBe("점수 없음");
    expect(v.missing[0]).toContain("미수집");
  });
});

describe("resolvePollPath — 응답이 요청 목적지를 정하게 두지 않는다", () => {
  it("정상 poll_url 은 BASE 를 떼고 쓴다", () => {
    expect(resolvePollPath("/api/v1/recommendations/rec_abc", "rec_abc")).toBe(
      "/recommendations/rec_abc",
    );
  });

  it("외부 URL·경로 이탈은 무시하고 job_id 로 되돌린다", () => {
    for (const bad of [
      "https://evil.example/api/v1/recommendations/rec_abc",
      "/api/v1/recommendations/../../auth/logout",
      "//evil.example/x",
      "",
      undefined,
    ]) {
      expect(resolvePollPath(bad, "rec_abc")).toBe("/recommendations/rec_abc");
    }
  });

  it("job_id 형식이 이상하면 요청을 만들지 않는다", () => {
    expect(() => resolvePollPath(undefined, "../auth/logout")).toThrow();
  });
});

describe("진행 상태", () => {
  it("모르는 status 는 진행 중으로 본다(멈춘 화면을 만들지 않는다)", () => {
    expect(jobPhase("running")).toBe("running");
    expect(jobPhase("weird")).toBe("running");
    expect(jobPhase("queued")).toBe("queued");
    expect(jobPhase("done")).toBe("done");
    expect(jobPhase("error")).toBe("error");
    expect(jobPhase(null)).toBe("idle");
  });

  it("★JOB-1 회귀: 서버의 실패 상태 'failed' 를 실패로 받는다", () => {
    // DB 제약(001_init.sql)이 허용하는 실패 값은 **"failed"** 다.
    // 이 매핑이 없으면 default 로 떨어져 "running" 이 되고, 실패한 분석이
    // 화면에서 **"분석 중…" 으로 무한히** 보인다(폴링 타임아웃 전까지).
    // 백엔드만 고치고 여기를 빠뜨리면 증상이 똑같이 남는다.
    expect(jobPhase("failed")).toBe("error");
  });

  it("서버가 progress 를 안 주면 진행률을 지어내지 않는다", () => {
    expect(progressText({ status: "running" })).toBe("분석 중…");
    expect(progressText({ status: "running" })).not.toMatch(/%|\d\/\d/);
  });

  it("progress 가 오면 단계와 담당을 한국어로 보여준다", () => {
    expect(
      progressText({ status: "running", progress: { done: 3, total: 5, current_agent: "valuation-trader" } }),
    ).toBe("분석 중… (3/5 · 매매 전문가)");
  });
});
