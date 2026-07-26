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
import type { AffordabilityPlan, Preferences } from "../api/client";

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
