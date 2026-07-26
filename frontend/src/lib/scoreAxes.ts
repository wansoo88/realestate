/**
 * 축별 점수 반영 결과를 **화면이 읽을 수 있는 형태로** 정리한다 (api-spec §5.3).
 *
 * 배경: 서버는 근거 있는 축만 총점에 넣고 나머지 가중치를 재정규화한다. 그러면 사용자가
 * 준 30% 가 조용히 사라질 수 있다. 계약이 요구하는 것은 두 가지다.
 *   ① `score_coverage_pct < 100` 이면 **점수 옆에 부분 반영 표기**
 *   ② 반영되지 못한 축은 **비율과 사유**를 함께 말한다
 * 그리고 `coverage=partial` 인 축은 **반영됐든 아니든** "어디까지만 보는지"를 말해야 한다 —
 * "호가가 없어 리스크가 빠졌다"로 끝내면 사용자는 "호가만 들어오면 리스크가 다 반영된다"고
 * 읽는다. 실제로는 risk-auditor 자체가 없다.
 *
 * 순수 함수만 둔다(뷰 비의존 · RN 이식).
 */
import type { RecommendationItem, ScoreAxis } from "../api/client";

export interface AxisView {
  axis: string;
  label: string;
  /** 사용자가 준 비중(%) */
  weightPct: number;
  /** 재정규화 후 실효 비중(%). 반영되지 않았으면 null. */
  appliedPct: number | null;
  score: number | null;
  applied: boolean;
  /** 사용자가 0 을 준 축 — 빠진 게 아니라 안 본 것이다. 다르게 말해야 한다. */
  zeroWeight: boolean;
  /** 반영되지 않은 이유(근거 없음). */
  missing: string[];
  /** partial 축이 무엇을 안 보는지. 반영 여부와 무관하게 노출한다. */
  coverageGap: string | null;
  /** 무엇을 점수로 쓰는지 */
  signal: string;
}

function pct(v: number | null | undefined): number | null {
  if (v === null || v === undefined || Number.isNaN(v)) return null;
  return Math.round(v * 100);
}

export function axisView(a: ScoreAxis): AxisView {
  return {
    axis: a.axis,
    label: a.label,
    weightPct: pct(a.weight) ?? 0,
    appliedPct: pct(a.applied_weight),
    score: a.score ?? null,
    applied: a.status === "applied",
    zeroWeight: a.status === "zero_weight",
    missing: a.missing ?? [],
    coverageGap: a.coverage === "partial" ? a.coverage_gap : null,
    signal: a.signal,
  };
}

export interface CoverageView {
  /** 반영 비율(%). 모르면 null(서버가 안 준 구버전). */
  pct: number | null;
  /** 부분 반영인가 — 100 미만이면 점수 옆 표기가 **계약상 필수**다. */
  partial: boolean;
  /** 사용자 가중치로 계산된 점수인가. `agent_scores` 폴백은 가중치 점수가 아니다. */
  userWeighted: boolean;
  /** 점수 옆에 붙일 짧은 표기. 붙일 게 없으면 null. */
  badge: string | null;
}

export function coverageView(item: RecommendationItem): CoverageView {
  const raw = item.score_coverage_pct;
  const value = raw === null || raw === undefined || Number.isNaN(raw) ? null : Math.round(raw);
  const userWeighted = item.score_basis === "user_weighted";
  const partial = value !== null && value < 100;

  return {
    pct: value,
    partial,
    userWeighted,
    badge: partial ? `내 조건 ${value}%만 반영` : null,
  };
}

/**
 * 축 목록 → 화면 순서. 반영된 축을 먼저, 그다음 반영 못 한 축(사용자가 알아야 할 것),
 * 마지막에 사용자가 0 을 준 축. **아무것도 숨기지 않는다** — 순서만 준다.
 */
export function axisViews(item: RecommendationItem): AxisView[] {
  const rows = (item.score_axes ?? []).map(axisView);
  const rank = (v: AxisView) => (v.applied ? 0 : v.zeroWeight ? 2 : 1);
  return [...rows].sort((a, b) => rank(a) - rank(b));
}

/**
 * 지금 결과에서 **근거가 없어 반영되지 못한** 축 코드들.
 * 조건 화면이 "이 축은 지금 근거가 없습니다"를 말할 때 쓴다(하드코딩 대신 관측값).
 */
export function unscoredAxes(item: RecommendationItem): string[] {
  return (item.score_axes ?? [])
    .filter((a) => a.status === "no_signal")
    .map((a) => a.axis);
}

/* ─────────────────────────────────────────────────────────────────────────
 * 관측 기억 — "지금 어떤 축에 근거가 없는가"
 *
 * 조건 화면(슬라이더)은 추천 결과를 들고 있지 않다. 그렇다고 "입지는 데이터가 없습니다"를
 * 코드에 박아 두면, 데이터가 들어온 날 화면이 **반대 방향으로** 거짓말을 한다.
 * 그래서 마지막 분석 결과에서 관측한 사실만 기억해 두고 그것만 말한다.
 *
 * 🔐 모듈 메모리에만 둔다(저장소 금지 · mapCamera 와 같은 이유). 새로고침하면 사라지고,
 *    그때는 화면이 아무 단정도 하지 않는다 — 모르면 모른다고 두는 편이 맞다.
 * ───────────────────────────────────────────────────────────────────────── */

let observed: Set<string> | null = null;

/**
 * 완료된 결과에서 축 상태를 기억한다.
 *
 * 후보마다 다를 수 있으므로(호가가 있는 후보는 가격 축이 살아 있다) **한 후보에서라도
 * 반영된 축은 "근거 있음"** 으로 본다. 보수적으로 잡으면 "근거 없음"을 과장하게 된다.
 */
export function rememberAxisGaps(items: RecommendationItem[] | null | undefined): void {
  if (!items || items.length === 0) return;
  const rows = items.flatMap((i) => i.score_axes ?? []);
  if (rows.length === 0) return; // 서버가 축 정보를 안 준다 — 기억할 것이 없다

  const applied = new Set(rows.filter((a) => a.status === "applied").map((a) => a.axis));
  observed = new Set(
    rows.filter((a) => a.status === "no_signal" && !applied.has(a.axis)).map((a) => a.axis),
  );
}

/**
 * 이 축이 직전 분석에서 근거가 없었는가.
 * `undefined` = 아직 분석을 돌린 적이 없다(단정하지 않는다).
 */
export function observedNoSignal(axis: string): boolean | undefined {
  if (observed === null) return undefined;
  return observed.has(axis);
}

/** 테스트·로그아웃용. */
export function forgetAxisGaps(): void {
  observed = null;
}
