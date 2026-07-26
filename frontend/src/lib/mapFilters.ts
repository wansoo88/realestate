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
  /** `/affordability` 로 계산한 실구매 가능 금액. 모르면 null. */
  budgetKrw: number | null;
  /** 예산 필터를 켜 두었는가(사용자가 끌 수 있다). */
  budgetApplied: boolean;
  prefer: Preferences["prefer"] | null;
  /** 선호(면적·연식) 필터를 켜 두었는가. */
  preferApplied: boolean;
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
    const budget = positive(f.budgetKrw);
    if (budget !== undefined) q.max_price_krw = budget;
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

  if (positive(f.budgetKrw) !== undefined) {
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
