/**
 * 추천 결과를 **정직하게** 화면에 옮기기 위한 순수 변환.
 *
 * 왜 컴포넌트가 아니라 여기인가
 * -----------------------------
 * "호가인가 추정인가", "점수가 0인가 없는가" 같은 판단이 JSX 안에 흩어지면
 * 화면마다 규칙이 갈라진다. 이 제품에서 그 갈라짐은 **거짓말**이 된다
 * (실거래 중위가가 호가로 둔갑하는 순간 사용자는 "지금 이 값에 살 수 있다"로 읽는다).
 * 그래서 판단은 전부 이 파일의 순수 함수에 모으고, 컴포넌트는 결과만 그린다.
 *
 * 계약 근거: `docs/02-design/api-spec.md` §5.1 (price_basis) · §5 (total_score)
 */
import type {
  DongValuation,
  Evidence,
  Finding,
  RecommendationItem,
} from "../api/client";
import { agentLabel } from "./agentLabels";
import type { Confidence } from "./format";

/* ─────────────────────────────────────────────────────────────────────────
 * 가격 — 호가와 실거래는 같은 숫자가 아니다
 * ───────────────────────────────────────────────────────────────────────── */

export interface PriceView {
  /** 화면에서 가장 큰 숫자로 나갈 기준가. 근거가 없으면 null(= 데이터 없음). */
  krw: number | null;
  /** 이 금액이 **무엇인지** 말하는 라벨. 라벨 없이 숫자만 두면 전부 호가로 읽힌다. */
  label: string;
  confidence: Confidence;
  estimated: boolean;
  /** 호가. `price_basis === "trade"` 면 **항상 null** — est 로 대체하지 않는다. */
  askKrw: number | null;
  /** 호가 갭(%). 호가가 없으면 비교 대상이 없으므로 null. */
  gapPct: number | null;
  /** 서버가 준 실거래 기준 안내 문구(있으면 반드시 노출). */
  note: string | null;
}

/**
 * 가격 표기 결정.
 *
 * ⚠️ **이 함수의 존재 이유가 아래 한 줄이다.** `price_basis === "trade"` 면
 * 호가·호가갭을 **버린다**. 서버가 실수로 값을 실어 보내도 화면에는 나가지 않는다.
 * (계약상 null 이지만, 계약을 믿고 그대로 그리면 계약이 깨진 날 사용자가 속는다)
 */
export function priceView(item: RecommendationItem): PriceView {
  const isListing = item.price_basis === "listing";
  const askKrw = isListing ? (item.ask_price_krw ?? null) : null;
  const gapPct = isListing ? (item.ask_gap_pct ?? null) : null;

  return {
    krw: item.est_price_krw ?? askKrw,
    label: isListing ? "호가" : "최근 실거래 기준 추정가",
    // 호가는 "지금 이 값에 살 수 있다"는 사실, 실거래 중위는 추정 — 농도를 다르게 준다.
    confidence: isListing ? "confirmed" : "estimated",
    estimated: !isListing || item.price_estimated === true,
    askKrw,
    gapPct,
    note: isListing ? null : (item.price_note ?? null),
  };
}

/* ─────────────────────────────────────────────────────────────────────────
 * 점수 — 0(나쁨)과 null(모름)은 다르다
 * ───────────────────────────────────────────────────────────────────────── */

export interface ScoreView {
  known: boolean;
  value: number | null;
  /** 화면 문구. 모를 때 "0" 이 절대 들어가지 않는다. */
  text: string;
  /** 왜 점수가 없는지(있으면 표시). */
  reason: string | null;
}

export function scoreView(item: RecommendationItem): ScoreView {
  const raw = item.total_score;
  if (raw === null || raw === undefined || Number.isNaN(raw)) {
    return {
      known: false,
      value: null,
      text: "점수 없음",
      reason: "점수를 매길 근거(호가 갭·입지 실측)가 없습니다",
    };
  }
  return { known: true, value: raw, text: `${raw.toFixed(1)}점`, reason: null };
}

/* ─────────────────────────────────────────────────────────────────────────
 * 동(棟)별 — 실측인지 추정인지 구조적으로 구분한다 (F4)
 * ───────────────────────────────────────────────────────────────────────── */

export interface DongView {
  available: boolean;
  /** 실거래 aptDong 으로 **직접 측정**한 값인가. */
  measured: boolean;
  label: string;
  detail: string | null;
  confidence: number;
  dongs: NonNullable<DongValuation["dongs"]>;
}

export function dongView(d: DongValuation | null | undefined): DongView {
  if (!d) {
    return {
      available: false,
      measured: false,
      label: "동별 판단 보류",
      detail: "동별 편차를 낼 실거래 근거가 없습니다.",
      confidence: 0,
      dongs: [],
    };
  }
  if (!d.available) {
    return {
      available: false,
      measured: false,
      label: "동별 판단 보류",
      // 서버가 준 사유를 그대로 보여준다 — 우리가 사유를 지어내지 않는다.
      detail: d.reason ?? d.method ?? null,
      confidence: d.confidence ?? 0,
      dongs: [],
    };
  }
  const measured = d.basis === "trade_measured";
  return {
    available: true,
    measured,
    label: measured ? "동별 실측(실거래)" : "동별 추정",
    detail: d.coverage_pct != null ? `동 정보 ${d.coverage_pct}% · ${d.method}` : d.method,
    confidence: d.confidence ?? 0,
    dongs: d.dongs ?? [],
  };
}

/* ─────────────────────────────────────────────────────────────────────────
 * 근거 — 출처 없는 주장은 근거가 아니다 (G2)
 * ───────────────────────────────────────────────────────────────────────── */

/** `source` 도 `data_rows` 도 없는 항목은 **렌더링하지 않는다**(components.md §5.7). */
export function usableEvidence(list: Evidence[] | null | undefined): Evidence[] {
  return (list ?? []).filter((e) => Boolean(e.source) || (e.data_rows ?? 0) > 0);
}

export interface FindingView {
  /** 판단 보류(데이터 부족)인가. 숨기지 않고 **그대로 보여준다**. */
  pending: boolean;
  missing: string[];
  evidence: Evidence[];
  scoreText: string;
}

export function findingView(f: Finding): FindingView {
  const missing = f.missing ?? [];
  return {
    pending: missing.length > 0,
    missing,
    evidence: usableEvidence(f.evidence),
    scoreText: f.score === null || f.score === undefined ? "점수 없음" : `${f.score}점`,
  };
}

/* ─────────────────────────────────────────────────────────────────────────
 * 폴링 경로
 * ───────────────────────────────────────────────────────────────────────── */

/** `/api/v1` 이후의 추천 경로만 허용한다. 그 외 형태는 전부 job_id 로 되돌린다. */
const POLL_URL_RE = /^\/api\/v1(\/recommendations\/[A-Za-z0-9_-]+)$/;
const JOB_ID_RE = /^[A-Za-z0-9_-]+$/;

/**
 * 서버가 준 `poll_url` 을 클라이언트 경로로 바꾼다.
 *
 * 왜 검증하나: 응답 본문의 URL 을 그대로 fetch 하면 **서버 응답이 요청 목적지를 정한다**.
 * 지금은 같은 서버지만, 응답이 오염되면(중간자·주입) 토큰이 붙은 요청이 엉뚱한 곳으로 간다.
 * 형식이 조금이라도 다르면 `job_id` 기반 경로로 되돌린다(계약상 둘은 같은 곳을 가리킨다).
 */
export function resolvePollPath(pollUrl: string | undefined | null, jobId: string): string {
  const m = pollUrl ? POLL_URL_RE.exec(pollUrl) : null;
  if (m) return m[1];
  if (!JOB_ID_RE.test(jobId)) throw new Error("job_id 형식이 올바르지 않습니다");
  return `/recommendations/${jobId}`;
}

/* ─────────────────────────────────────────────────────────────────────────
 * 진행 상태
 * ───────────────────────────────────────────────────────────────────────── */

export type JobPhase = "idle" | "queued" | "running" | "done" | "error";

/** 서버 status 문자열 → 화면 단계. 모르는 값은 "running"(진행 중)으로 본다. */
export function jobPhase(status: string | undefined | null): JobPhase {
  switch (status) {
    case "queued":
      return "queued";
    case "done":
      return "done";
    // ⚠️ 서버(DB 제약)의 실패 상태는 **"failed"** 다. 예전에 백엔드가 "error" 를 쓰려다
    //    DB CHECK 에 막혀 job 이 'queued' 로 멈추는 사고가 있었다. 그때 여기도 "failed" 를
    //    모르는 상태라, 백엔드만 고쳤어도 화면은 default → "running" 으로 떨어져
    //    **"분석 중…" 이 무한히 표시**됐을 것이다. 두 값 모두 실패로 받는다.
    case "failed":
    case "error":
      return "error";
    case undefined:
    case null:
      return "idle";
    default:
      return "running";
  }
}

/**
 * 진행 문구. **진행률을 지어내지 않는다** — 서버가 progress 를 안 주면 단계만 말한다.
 * (가짜 퍼센트 바는 이 제품에서 가장 싼 거짓말이다)
 */
export function progressText(job: {
  status?: string | null;
  progress?: { done: number; total: number; current_agent?: string | null } | null;
}): string {
  const phase = jobPhase(job.status);
  if (phase === "queued") return "분석 대기 중…";
  if (phase === "error") return "분석에 실패했습니다.";
  if (phase === "done") return "분석 완료";
  const p = job.progress;
  if (p && p.total > 0) {
    const who = p.current_agent ? ` · ${agentLabel(p.current_agent)}` : "";
    return `분석 중… (${p.done}/${p.total}${who})`;
  }
  return "분석 중…";
}
