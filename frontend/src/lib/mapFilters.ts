/**
 * "내 조건"을 지도 조회 파라미터로 옮기는 **순수 변환**.
 *
 * 왜 이게 따로 있나
 * -----------------
 * 이 제품의 핵심은 "수천 건에서 내 조건에 맞는 5~10건으로 좁히기"다. 그런데 필터가
 * **조용히** 걸려 있으면 사용자는 "왜 안 보이지?"가 된다. 그래서 이 모듈은 두 가지를
 * 같은 곳에서 만든다: ① 서버로 보낼 쿼리 ② 화면에 보여줄 "지금 적용된 조건" 칩.
 * 둘이 갈라지면 화면이 거짓말을 하게 되므로 한 함수에서 같은 상태를 읽는다.
 */
import type { Preferences } from "../api/client";
import { formatKrwShort } from "./format";

export interface MapFilterState {
  /** `/affordability` 로 계산한 **최대** 실구매 가능 금액. 모르면 null. */
  budgetKrw: number | null;
  /** 예산 필터를 켜 두었는가(사용자가 끌 수 있다). */
  budgetApplied: boolean;
  /**
   * 사용자가 정한 희망 매매가. 있으면 **이쪽이 지도 상한**이다.
   *
   * 왜 한도가 아니라 희망가를 쓰는가: 같은 희망가가 AI 추천에도
   * `budget_override_krw` 로 나간다. 지도만 한도(8.5억) 기준이고 추천만 희망가(9억)
   * 기준이면, 추천에는 뜨는데 지도에는 없는 단지가 생긴다 — 같은 화면이 두 가지
   * 예산을 말하는 셈이다. 한도를 넘겨 잡았어도 그대로 쓴다(못 사는 집을 **보는 것**은
   * 이 기능의 목적이고, 살 수 있는지는 자금계획이 숫자로 답한다).
   */
  targetPriceKrw?: number | null;
  prefer: Preferences["prefer"] | null;
  /** 선호(면적·연식) 필터를 켜 두었는가. */
  preferApplied: boolean;
}

/** 지도·추천이 함께 쓰는 실효 예산 상한. 희망가가 있으면 그것, 없으면 한도. */
export function effectiveBudgetKrw(f: MapFilterState): number | null {
  const target = positive(f.targetPriceKrw);
  if (target !== undefined) return target;
  const budget = positive(f.budgetKrw);
  return budget ?? null;
}

export interface MapQuery {
  bbox: string;
  zoom: number;
  max_price_krw?: number;
  area_min_m2?: number;
  area_max_m2?: number;
  built_after?: number;
}

/** 0·NaN·null 을 한 번에 걸러낸다. 0 을 "필터 없음"과 구분하지 않는 건 여기서만 허용된다
 *  (면적 0㎡·예산 0원·0년 준공은 존재하지 않는 값이라 필터로 의미가 없다). */
function positive(v: number | null | undefined): number | undefined {
  return typeof v === "number" && Number.isFinite(v) && v > 0 ? v : undefined;
}

export function buildMapQuery(bbox: string, zoom: number, f: MapFilterState): MapQuery {
  const q: MapQuery = { bbox, zoom };

  if (f.budgetApplied) {
    const budget = effectiveBudgetKrw(f);
    if (budget !== null) q.max_price_krw = budget;
  }

  if (f.preferApplied && f.prefer) {
    const min = positive(f.prefer.area_min_m2);
    const max = positive(f.prefer.area_max_m2);
    if (min !== undefined) q.area_min_m2 = min;
    if (max !== undefined) q.area_max_m2 = max;
    const built = positive(f.prefer.built_after);
    if (built !== undefined) q.built_after = built;
  }

  return q;
}

export interface FilterChip {
  id: "budget" | "area" | "built";
  /** 켜져 있을 때 화면에 뜨는 문구. "내 예산 8.5억 기준" 처럼 **무엇이 걸렸는지** 말한다. */
  label: string;
  active: boolean;
}

/**
 * 지금 무엇이 적용됐는지 보여줄 칩 목록.
 *
 * 끌 수 있는 것만 칩으로 만든다(값이 아예 없는 조건은 칩도 만들지 않는다 —
 * 끌 게 없는 스위치를 보여주면 사용자는 그걸 켜면 뭔가 될 거라고 오해한다).
 */
export function filterChips(f: MapFilterState): FilterChip[] {
  const chips: FilterChip[] = [];

  const target = positive(f.targetPriceKrw);
  if (target !== undefined) {
    // 희망가를 정했으면 칩도 그렇게 말해야 한다 — "내 예산"이라고 쓰면 사용자가 정한 값이
    // 아니라 서버가 계산한 한도로 읽힌다(둘은 다른 숫자다).
    chips.push({
      id: "budget",
      label: `희망가 ${formatKrwShort(target)} 이하`,
      active: f.budgetApplied,
    });
  } else if (positive(f.budgetKrw) !== undefined) {
    chips.push({
      id: "budget",
      label: `내 예산 ${formatKrwShort(f.budgetKrw)} 기준`,
      active: f.budgetApplied,
    });
  }

  const min = positive(f.prefer?.area_min_m2);
  const max = positive(f.prefer?.area_max_m2);
  if (min !== undefined || max !== undefined) {
    const range =
      min !== undefined && max !== undefined
        ? `${min}~${max}㎡`
        : min !== undefined
          ? `${min}㎡ 이상`
          : `${max}㎡ 이하`;
    chips.push({ id: "area", label: `면적 ${range}`, active: f.preferApplied });
  }

  const built = positive(f.prefer?.built_after);
  if (built !== undefined) {
    chips.push({ id: "built", label: `${built}년 이후 준공`, active: f.preferApplied });
  }

  return chips;
}
