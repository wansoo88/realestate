/**
 * "내 조건이 점수에 얼마나 반영됐나" — **구조화된 필드에서** 사람이 읽을 문장을 만든다.
 *
 * 왜 이 파일이 생겼나
 * -------------------
 * 화면에 이런 다섯 줄이 같은 무게로 나열되고 있었다:
 *   "가격 가중치 30.8%가 반영되지 않았습니다 — 활성 호가가 없어…"
 *   "가치(시세) 축은 12개월 거래회전율 기반 환금성(liquidity.turnover_12m_pct)까지만…"
 *   "반영된 가중치는 52.3% 입니다 — 나머지 47.7%는 …재정규화했습니다."
 * ① 내부 식별자가 새어 나갔고 ② 무엇이 중요한지 알 수 없었다.
 *
 * 이 모듈의 규칙
 *  · **문자열을 파싱하지 않는다.** 반영/미반영·비율·상태는 전부 `score_axes` 의
 *    구조화된 필드(`status`·`weight`·`applied_weight`)에서 계산한다. 서버가 문구를
 *    바꿔도 이 계산은 그대로 맞는다.
 *  · 사유 문장(`missing`·`coverage_gap`)만은 서버 원문을 쓴다 — 사유는 우리가 만들어낼 수
 *    없다. 대신 내부 식별자만 걷어낸다(lib/plainTerms). 서버가 사유 **코드**를 주면
 *    그때 우리 문장으로 바꿀 수 있다(보고 참조).
 *  · **반영률은 상세가 아니라 헤드라인이다.** 접지 않는다 — 접으면 사용자는 지금 순위를
 *    "내가 설정한 대로 나온 순위"로 오해한다.
 */
import type { RecommendationItem } from "../api/client";
import { plainText } from "./plainTerms";
import { axisViews, coverageView, type AxisView } from "./scoreAxes";

/**
 * 톤 임계값 — **여기 한 곳에만 둔다.**
 * 화면 곳곳에 `pct < 50` 같은 숫자가 흩어지면 기준을 바꿀 때 한 곳이 반드시 남는다.
 */
export const COVERAGE_THRESHOLDS = {
  /** 이 값 이상이면 경고하지 않는다. 항상 뜨는 경고는 아무도 읽지 않는다. */
  full: 100,
  /** 이 값 미만이면 "절반도 반영되지 않았다" — 순위 자체를 의심해야 하는 구간. */
  low: 50,
} as const;

export type CoverageTone = "unknown" | "full" | "partial" | "low";

export function coverageTone(pct: number | null): CoverageTone {
  if (pct === null) return "unknown";
  if (pct >= COVERAGE_THRESHOLDS.full) return "full";
  if (pct < COVERAGE_THRESHOLDS.low) return "low";
  return "partial";
}

export interface AxisWeightRow {
  axis: string;
  label: string;
  weightPct: number;
}

export interface CoverageDetail {
  tone: CoverageTone;
  /** 서버가 준 반영률(%). 없으면 null — 단정하지 않는다. */
  pct: number | null;
  /** 경고 줄을 띄울 것인가(100% 면 띄우지 않는다). */
  warn: boolean;
  /** 항상 보이는 한 줄. 접으면 안 되는 문장이다. */
  headline: string | null;
  /** 왜 그렇게 됐는지 한 줄(축 이름 기반 — 서버 문장을 파싱하지 않는다). */
  reason: string | null;

  applied: AxisWeightRow[];
  dropped: AxisWeightRow[];
  zeroWeight: AxisWeightRow[];
  appliedSumPct: number | null;
  droppedSumPct: number | null;

  /** 왜 못 봤나요 — 축별 사유(서버 원문, 내부 식별자 제거). */
  reasons: Array<{ axis: string; label: string; text: string }>;
  /** 아직 못 보는 것 — 반영됐어도 남는 한계(coverage=partial). */
  limits: Array<{ axis: string; label: string; text: string }>;
  /** 점수를 어떻게 냈나요. */
  method: string[];
  /** 서버가 축 정보를 안 줄 때 쓰는 원문 고지(구버전 폴백). */
  rawNotes: string[];
  /** 펼칠 내용이 하나라도 있는가. 없으면 이 블록 자체를 그리지 않는다. */
  hasDetail: boolean;
}

function row(v: AxisView): AxisWeightRow {
  return { axis: v.axis, label: v.label, weightPct: v.weightPct };
}

function sumPct(rows: AxisWeightRow[]): number | null {
  return rows.length === 0 ? null : rows.reduce((a, r) => a + r.weightPct, 0);
}

function labels(rows: AxisWeightRow[]): string {
  return rows.map((r) => r.label).join(" · ");
}

export function coverageDetail(item: RecommendationItem): CoverageDetail {
  const cov = coverageView(item);
  const views = axisViews(item);
  const tone = coverageTone(cov.pct);

  const applied = views.filter((v) => v.applied).map(row);
  // "내가 0% 로 둔 축"은 빠진 게 아니라 **안 본** 것이다 — 미반영과 절대 섞지 않는다.
  const dropped = views.filter((v) => !v.applied && !v.zeroWeight).map(row);
  const zeroWeight = views.filter((v) => v.zeroWeight).map(row);

  const warn = tone === "partial" || tone === "low";
  const headline = warn
    ? tone === "low"
      ? `설정하신 가중치의 ${cov.pct}%만 반영됐습니다 — 절반도 반영되지 않았습니다`
      : `설정하신 가중치의 ${cov.pct}%만 반영됐습니다`
    : null;

  // 한 줄 사유는 **축 이름**으로 만든다(서버 문장을 잘라 붙이지 않는다).
  const reason =
    warn && dropped.length > 0
      ? `${labels(dropped)} 항목을 판단할 근거가 없어서입니다`
      : null;

  const reasons = views
    .filter((v) => !v.applied && !v.zeroWeight)
    .map((v) => ({
      axis: v.axis,
      label: v.label,
      text: plainText(v.missing.join(" · ")) || "근거 없음",
    }));

  const limits = views
    .filter((v) => v.coverageGap)
    .map((v) => ({ axis: v.axis, label: v.label, text: plainText(v.coverageGap as string) }));

  const method: string[] = [];
  if (applied.length > 0 && dropped.length > 0) {
    method.push(
      `근거가 있는 ${applied.length}개 항목(${labels(applied)})만으로 다시 100% 기준을 잡아 계산했습니다.`,
    );
  }
  if (applied.length > 0 && dropped.length === 0 && views.length > 0) {
    method.push("설정하신 가중치를 그대로 점수에 반영했습니다.");
  }
  if (views.length > 0 && applied.length === 0) {
    // 반영된 축이 하나도 없으면 총점은 0 이 아니라 **없음**이다.
    method.push("반영할 근거가 하나도 없어 점수를 매기지 않았습니다 — 0점이 아니라 '모름'입니다.");
  }
  if (!cov.userWeighted && item.total_score !== null) {
    method.push("이 점수는 내 가중치가 아니라 전문가 신뢰도 평균으로 매겨졌습니다.");
  }

  // 축 정보가 있으면 그것이 정본이다. 없을 때만 서버 원문 고지를 그대로 보여준다
  // (구버전 서버에서도 "무엇이 반영되지 않았는지"가 사라지지 않게).
  const rawNotes = views.length === 0 ? (item.score_notes ?? []).map(plainText) : [];

  return {
    tone,
    pct: cov.pct,
    warn,
    headline,
    reason,
    applied,
    dropped,
    zeroWeight,
    appliedSumPct: sumPct(applied),
    droppedSumPct: sumPct(dropped),
    reasons,
    limits,
    method,
    rawNotes,
    hasDetail: views.length > 0 || rawNotes.length > 0,
  };
}
