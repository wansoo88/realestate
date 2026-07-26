/**
 * 선호/기피 조건 관련 **순수 함수**.
 *
 * 가중치는 화면에서 0~100 슬라이더로 다루지만 서버 계약은 합이 1 인 비율이다.
 * 사용자에게 "합을 100 으로 맞추세요"라고 시키면 아무도 안 만진다 → **자동 정규화**한다
 * (components.md §5.4).
 */
import type { Preferences } from "../api/client";

export type Weights = NonNullable<Preferences["weights"]>;

/** api-spec §2 예시값. 사용자가 손대지 않으면 이 값이 나간다. */
export const DEFAULT_WEIGHTS: Required<Weights> = {
  price: 0.3,
  location: 0.3,
  value: 0.25,
  risk: 0.15,
};

export const WEIGHT_KEYS: Array<keyof Required<Weights>> = ["price", "location", "value", "risk"];

export const WEIGHT_LABELS: Record<keyof Required<Weights>, string> = {
  price: "가격",
  location: "입지",
  value: "가치(시세)",
  risk: "리스크",
};

/**
 * 합이 1 이 되게 맞춘다. 전부 0 이면(사용자가 다 내렸으면) 기본값으로 되돌린다 —
 * 합 0 을 그대로 보내면 서버에서 0 나눗셈이거나 "아무것도 중요하지 않다"는 뜻이 된다.
 */
export function normalizeWeights(w: Weights | null | undefined): Required<Weights> {
  const raw = WEIGHT_KEYS.map((k) => {
    const v = w?.[k];
    return typeof v === "number" && Number.isFinite(v) && v > 0 ? v : 0;
  });
  const sum = raw.reduce((a, b) => a + b, 0);
  if (sum <= 0) return { ...DEFAULT_WEIGHTS };

  const out = {} as Required<Weights>;
  WEIGHT_KEYS.forEach((k, i) => {
    // 소수 4자리로 끊는다 — 화면에 8.333333%가 뜨는 것보다 낫고, 서버는 비율만 본다.
    out[k] = Math.round((raw[i] / sum) * 10_000) / 10_000;
  });
  return out;
}

/** 슬라이더 표시용 정수 퍼센트(합 100 이 아닐 수 있음 — 반올림 오차는 표시에만 영향). */
export function weightPercent(w: Weights, key: keyof Required<Weights>): number {
  return Math.round((normalizeWeights(w)[key] ?? 0) * 100);
}
