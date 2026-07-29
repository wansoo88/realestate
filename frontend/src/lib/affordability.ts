/**
 * 희망 매매가 · 자금계획 — **순수 함수**. 뷰·DOM 에 의존하지 않으므로 RN 에서 그대로 쓴다.
 *
 * 이 모듈이 존재하는 이유
 * ----------------------
 * ① 슬라이더의 **범위**를 한 곳에서 정한다. "최대 실구매 가능 금액"을 기준으로 잡되
 *    **그보다 높은 값도 고를 수 있어야 한다** — 한도를 넘는 집을 봐야 "얼마가 더 필요한가"를
 *    알 수 있고, 그게 이 기능의 목적이다. 상한을 한도에서 끊으면 질문 자체가 사라진다.
 * ② 저장된 값을 **읽을 때 검증**한다. `prefer` 는 서버에서 열린 dict 라 무엇이든 들어올 수
 *    있다(문자열·음수·NaN·1경). 화면이 그걸 그대로 믿으면 슬라이더가 깨지거나 요청에
 *    쓰레기가 실린다.
 * ③ 서버 `plan` 을 **쓸 수 있는지 판정**한다. 계산은 서버가 한다(여기서 다시 계산하면
 *    진실이 두 개가 된다). 대신 필수 숫자가 빠진 응답은 렌더링하지 않는다 —
 *    화면에 `NaN원`·`—` 이 뜨는 것보다 "아직 계산되지 않았습니다"가 정직하다.
 *
 * 🔐 값은 개인 금융정보에 준해 다룬다. 로그·저장소·URL 에 쓰지 않는다.
 */
import type { AffordabilityPlan, Preferences, TargetPriceRef } from "../api/client";
import { plainReason } from "./plainTerms";

/** 슬라이더 눈금 — 500만원. 억 단위 미세조정은 슬라이더로 안 되므로 직접 입력을 함께 둔다. */
export const TARGET_STEP_KRW = 5_000_000;

/** 슬라이더 하한 — 5,000만원. 이보다 싼 수도권 아파트는 사실상 없다. */
export const TARGET_MIN_KRW = 50_000_000;

/** 한도를 모를 때 쓰는 기준값(10억). 자산 미입력 상태에서도 슬라이더가 죽지 않게. */
export const TARGET_FALLBACK_BASE_KRW = 1_000_000_000;

/**
 * 슬라이더 상한 = 최대 실구매 가능 금액 × 이 배수.
 * 1.5 인 이유: "조금 더 모으면 되는" 구간(한도의 1~1.5배)이 사용자가 실제로 궁금해하는
 * 범위다. 더 키우면 눈금 하나가 커져 정작 한도 근처를 맞추기 어려워진다
 * (그 위쪽은 **직접 입력**이 담당한다 — 상한은 슬라이더의 한계지 값의 한계가 아니다).
 */
export const TARGET_HEADROOM = 1.5;

/** 직접 입력 상한(1,000억). 그 이상은 금액이 아니라 오타다. */
export const TARGET_ABS_MAX_KRW = 100_000_000_000;

export interface TargetPriceRange {
  min: number;
  max: number;
  step: number;
  /** 최대 실구매 가능 금액(있으면). 슬라이더 위에 "여기까지가 내 한도" 표시로 쓴다. */
  limitKrw: number | null;
}

function roundToStep(krw: number, mode: "up" | "down" | "near" = "near"): number {
  const n = krw / TARGET_STEP_KRW;
  const r = mode === "up" ? Math.ceil(n) : mode === "down" ? Math.floor(n) : Math.round(n);
  return r * TARGET_STEP_KRW;
}

/**
 * 슬라이더 범위. 한도를 모르면(자산 미입력·계산 실패) 기준값으로 대신하되,
 * `limitKrw` 는 **null 로 남긴다** — 모르는 한도를 아는 척 그리지 않는다.
 */
export function targetPriceRange(maxPurchaseKrw: number | null | undefined): TargetPriceRange {
  const limit =
    typeof maxPurchaseKrw === "number" && Number.isFinite(maxPurchaseKrw) && maxPurchaseKrw > 0
      ? maxPurchaseKrw
      : null;
  const base = limit ?? TARGET_FALLBACK_BASE_KRW;
  const max = Math.max(roundToStep(base * TARGET_HEADROOM, "up"), TARGET_MIN_KRW + TARGET_STEP_KRW);
  return { min: TARGET_MIN_KRW, max, step: TARGET_STEP_KRW, limitKrw: limit };
}

/**
 * 슬라이더가 다룰 수 있는 값으로 맞춘다(슬라이더 전용).
 * 직접 입력은 이걸 쓰지 않는다 — 상한을 넘겨 적고 싶은 사용자를 막으면 안 된다.
 */
export function clampToRange(krw: number, range: TargetPriceRange): number {
  if (!Number.isFinite(krw)) return range.min;
  return Math.min(range.max, Math.max(range.min, roundToStep(krw)));
}

/** 직접 입력 값의 최종 검증. 범위를 벗어난 오타만 막고, 한도 초과는 **막지 않는다**. */
export function normalizeTargetPrice(krw: number | null | undefined): number | null {
  if (krw === null || krw === undefined) return null;
  if (!Number.isFinite(krw) || krw <= 0) return null;
  return Math.min(TARGET_ABS_MAX_KRW, Math.round(krw));
}

/**
 * 저장된 선호에서 희망가를 읽는다. 서버가 무엇을 돌려주든 **숫자로 검증**해서 통과시킨다.
 * (문자열 "9억", 음수, NaN 은 없는 것으로 본다 — 지어내지 않는다)
 */
export function readTargetPrice(prefer: Preferences["prefer"] | null | undefined): number | null {
  const raw = prefer?.target_price_krw;
  return typeof raw === "number" ? normalizeTargetPrice(raw) : null;
}

/**
 * 선호에 희망가를 담는다. null 이면 **키를 지운다** — 0 이나 null 을 남기면
 * "0원을 원한다"와 "정하지 않았다"가 구분되지 않는다.
 */
export function withTargetPrice(
  prefer: Preferences["prefer"],
  krw: number | null,
): Preferences["prefer"] {
  const next = { ...prefer };
  const value = normalizeTargetPrice(krw);
  if (value === null) delete next.target_price_krw;
  else next.target_price_krw = value;
  return next;
}

/* ─────────────────────────────────────────────────────────────────────────
 * 단지 기준 계획의 **면적** (CR35-4)
 *
 * 기준가는 면적별 값이다(한 단지가 34~120㎡). 그런데 지도는 대개 면적을 모르고, 서버는
 * 안 보내면 기본값 84㎡ 로 계산한다. 그 사실을 화면이 모르면 "이 집을 사려면"이라는
 * 문장이 **다른 평형의 계획**에 붙는다. 그래서 화면은 항상 면적을 정해 보내고,
 * **무슨 근거로 그 면적을 골랐는지 함께 적는다.**
 * ───────────────────────────────────────────────────────────────────────── */

/** 서버 `AffordabilityIn.area_m2` 기본값과 같은 값(국민평형). */
export const DEFAULT_PLAN_AREA_M2 = 84;

export type PlanAreaBasis =
  /** 지도에 보인 금액이 나온 그 거래의 면적 — 화면에 보이는 숫자와 같은 평형이다. */
  | "map_trade"
  /** 내 조건(전용면적 범위)의 가운데 값. */
  | "my_condition"
  /** 아무 단서도 없어 국민평형으로 계산. **모른다는 사실을 말해야 한다.** */
  | "default";

export interface PlanArea {
  m2: number;
  basis: PlanAreaBasis;
}

function usableArea(v: number | null | undefined): number | null {
  return typeof v === "number" && Number.isFinite(v) && v > 0 && v <= 1000 ? v : null;
}

export function planArea(opts: {
  priceAreaM2?: number | null;
  areaMinM2?: number | null;
  areaMaxM2?: number | null;
}): PlanArea {
  const traded = usableArea(opts.priceAreaM2);
  if (traded !== null) return { m2: traded, basis: "map_trade" };

  const min = usableArea(opts.areaMinM2);
  const max = usableArea(opts.areaMaxM2);
  if (min !== null && max !== null) {
    return { m2: Math.round(((min + max) / 2) * 100) / 100, basis: "my_condition" };
  }
  if (min !== null) return { m2: min, basis: "my_condition" };
  if (max !== null) return { m2: max, basis: "my_condition" };

  return { m2: DEFAULT_PLAN_AREA_M2, basis: "default" };
}

/** 왜 이 면적으로 계산했는지 한 줄. **모르면 모른다고 적는다.** */
export function planAreaNote(area: PlanArea): string {
  switch (area.basis) {
    case "map_trade":
      return `${area.m2}㎡ 기준 — 지도에 보인 체결가와 같은 면적입니다.`;
    case "my_condition":
      return `${area.m2}㎡ 기준 — 내 조건의 전용면적으로 계산했습니다.`;
    default:
      return `${area.m2}㎡ 기준 — 면적을 정하지 않아 국민평형으로 계산했습니다. 다른 평형이면 금액이 달라집니다.`;
  }
}

/* ─────────────────────────────────────────────────────────────────────────
 * 기준가 근거 (`target_price`) — **무엇을 기준으로 계산했는지 화면이 말해야 한다**
 *
 * 같은 단지가 화면마다 다른 금액으로 보이던 문제(CR34-3·CR35-4)의 마지막 조각이다.
 * 서버는 `basis` 를 **기계용 코드**로 준다("프론트가 화면에 그대로 이름 붙일 수 있게
 * 서버가 정한다" — recommend.py). 그 코드 → 사람 말 번역은 **여기 한 곳에서만** 한다.
 * 모르는 코드는 번역하지 않고 "확인하지 못했다"고 말한다(지어내지 않는다).
 * ───────────────────────────────────────────────────────────────────────── */

export const PRICE_BASIS_TIME_ADJUSTED = "time_adjusted_band";
export const PRICE_BASIS_TRADE_BAND = "trade_band";
export const PRICE_BASIS_CLIENT = "client_supplied";

export interface TargetPriceView {
  /** 계획을 세울 금액이 있는가. false 면 **0 으로 채우지 말고 사유를 보인다.** */
  known: boolean;
  krw: number | null;
  /** 이 금액이 무엇인가(짧은 이름) */
  label: string;
  /** 표본·기간·기준월 같은 근거 한 줄. 없으면 null. */
  detail: string | null;
  /** 실거래에서 유도한 **추정치**인가 — 그러면 "지금 살 수 있는 호가가 아니다"를 말한다. */
  estimated: boolean;
  /** 못 만든 사유 또는 시점 보정 실패 사유. 내부 코드는 걸러진다. */
  reason: string | null;
}

/**
 * 이 기준가가 **무엇과 같은 값인가**를 말할 때 필요한 맥락 (CR36-5).
 *
 * 예전 문구는 *"추천 카드와 같은 값입니다"* 였다. 어느 카드인지 말하지 않으니
 * ① 추천을 한 번도 안 돌린 사용자에게는 **존재하지 않는 카드**를 가리키고,
 * ② 추천 결과가 10건일 때는 그중 무엇과 비교하라는 건지 알 수 없다.
 * 그래서 단지·면적을 받아 **무엇에 대한 값인지** 이름으로 말한다.
 */
export interface TargetPriceContext {
  /** 어느 단지의 기준가인가. 모르면 생략(그러면 이름 없이 말한다). */
  complexName?: string | null;
  /** 어느 전용면적(㎡)의 기준가인가. 한 단지가 34~120㎡ 라 면적이 빠지면 값이 달라진다. */
  areaM2?: number | null;
}

/** "AI 추천도 '가나아파트 84.97㎡' 를 같은 기준으로 계산합니다." 한 줄. */
function sameBasisNote(ctx: TargetPriceContext): string {
  const name = typeof ctx.complexName === "string" ? ctx.complexName.trim() : "";
  const area =
    typeof ctx.areaM2 === "number" && Number.isFinite(ctx.areaM2) && ctx.areaM2 > 0
      ? `${ctx.areaM2}㎡`
      : "";
  const subject = [name, area].filter((s) => s !== "").join(" ");

  // ⚠️ "같은 **값**" 이 아니라 "같은 **기준**" 이다. 두 숫자를 화면이 실제로 맞대어 본 적은
  //    없고(추천을 아직 안 돌렸을 수도 있다), 서버가 같은 함수를 쓴다는 것이 우리가 아는 전부다.
  return subject === ""
    ? "AI 추천의 추정가와 같은 기준으로 계산한 값입니다."
    : `AI 추천도 '${subject}' 를 같은 기준으로 계산합니다.`;
}

/** 서버가 이 블록을 안 주면(구버전) **null** — 없는 근거를 화면이 지어내지 않는다. */
export function targetPriceView(
  ref: TargetPriceRef | null | undefined,
  ctx: TargetPriceContext = {},
): TargetPriceView | null {
  if (!ref || typeof ref !== "object") return null;

  const reason = plainReason(ref.reason);
  const krw = typeof ref.krw === "number" && Number.isFinite(ref.krw) ? ref.krw : null;
  const n = ref.sample_size ?? 0;
  const months = ref.period_months ?? null;

  if (krw === null || krw <= 0) {
    return {
      known: false,
      krw: null,
      label: "자금계획을 세우지 못했습니다",
      detail: null,
      estimated: false,
      reason,
    };
  }

  switch (ref.basis) {
    case PRICE_BASIS_TIME_ADJUSTED:
      return {
        known: true,
        krw,
        label: "최근 실거래를 한 시점으로 환산한 추정가",
        detail: `최근 ${months ?? "?"}개월 실거래 ${n}건 · ${ref.as_of_ym ?? "기준월 미상"} 시점 환산 — ${sameBasisNote(ctx)}`,
        estimated: true,
        reason,
      };
    case PRICE_BASIS_TRADE_BAND:
      return {
        known: true,
        krw,
        label: "최근 실거래의 중위값 (시점 보정 못 함)",
        detail: `최근 ${months ?? "?"}개월 실거래 ${n}건의 중위값 — 여러 시점의 거래를 섞은 값이라 특정 시점의 가격이 아닙니다.`,
        estimated: true,
        reason,
      };
    case PRICE_BASIS_CLIENT:
      return {
        known: true,
        krw,
        label: "직접 입력하신 금액",
        detail: "서버가 근거를 확인하지 않았습니다 — 추천 카드의 추정가와 다를 수 있습니다.",
        estimated: false,
        reason: null, // 서버 reason 은 위 문장과 같은 말이다(두 번 적지 않는다)
      };
    default:
      return {
        known: true,
        krw,
        label: "기준가의 근거를 확인하지 못했습니다",
        detail: null,
        estimated: false,
        reason,
      };
  }
}

/* ─────────────────────────────────────────────────────────────────────────
 * 서버 자금계획(plan) 검증
 * ───────────────────────────────────────────────────────────────────────── */

const REQUIRED_PLAN_NUMBERS = [
  "target_price_krw",
  "total_needed_krw",
  "own_cash_krw",
  "shortfall_krw",
  "required_loan_krw",
  "loan_limit_krw",
  "monthly_payment_krw",
] as const;

function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/**
 * 렌더링해도 되는 plan 인가.
 *
 * 백엔드가 이 계약을 **동시에** 구현 중이라 배포 순서가 어긋날 수 있다. 필드가 빠진 응답을
 * 그대로 그리면 화면에 `NaN`·`—` 이 섞인 금액이 뜨는데, 그건 "계산했는데 이상한 값"으로
 * 읽힌다. 못 그릴 바엔 **아직 없다고 말하는 편**이 정확하다.
 */
export function usablePlan(plan: AffordabilityPlan | null | undefined): AffordabilityPlan | null {
  if (!plan || typeof plan !== "object") return null;
  for (const key of REQUIRED_PLAN_NUMBERS) {
    if (!isNum(plan[key])) return null;
  }
  if (plan.target_price_krw <= 0) return null;
  return plan;
}

/**
 * 대출이 한도를 넘는가. 서버 `loan_feasible` 이 정본이고, 그 필드가 없는(구) 응답에서만
 * 숫자로 되짚는다 — 프론트가 먼저 판정해 서버와 다른 답을 내지 않게 한다.
 */
export function planOverLimit(plan: AffordabilityPlan): boolean {
  if (typeof plan.loan_feasible === "boolean") return !plan.loan_feasible;
  return plan.required_loan_krw > plan.loan_limit_krw;
}

/** 한도 초과분. 서버가 주면 그 값을, 없으면 계산해 보완한다(음수는 0). */
export function planOverLimitKrw(plan: AffordabilityPlan): number {
  if (isNum(plan.over_limit_krw)) return Math.max(0, plan.over_limit_krw);
  return Math.max(0, plan.required_loan_krw - plan.loan_limit_krw);
}
