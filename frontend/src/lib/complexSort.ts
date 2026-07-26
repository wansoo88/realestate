/**
 * 목록 정렬 — **순수 함수**.
 *
 * 왜 필요한가: 서버는 지도 범위 안의 단지를 조회 순서 그대로 준다(정렬 파라미터가 계약에 없다).
 * 그 상태로 수십 건을 나열하면 사용자는 "무엇부터 볼지"를 스스로 못 정한다 — 목록에 위계가 없다.
 * 정렬은 **화면 범위 안에서만** 도는 클라이언트 연산이므로, 라벨에 "이 화면 범위 기준"을
 * 함께 적어 전국 순위처럼 읽히지 않게 한다(App.tsx).
 *
 * ⚠️ null 은 0 이 아니다. 시세·준공년도·세대수를 **모르는** 단지를 "가장 싼 집"이나
 *    "가장 오래된 집"으로 줄 세우면 화면이 거짓말을 한다. 모르는 값은 **항상 맨 뒤**로 보낸다.
 */
import type { ComplexItem } from "../api/client";

export type SortKey = "default" | "price_asc" | "price_desc" | "built_desc" | "households_desc";

export const SORT_OPTIONS: Array<{ key: SortKey; label: string }> = [
  { key: "default", label: "추천 순" },
  { key: "price_asc", label: "가격 낮은 순" },
  { key: "price_desc", label: "가격 높은 순" },
  { key: "built_desc", label: "최근 준공 순" },
  { key: "households_desc", label: "세대수 많은 순" },
];

export function isSortKey(v: string): v is SortKey {
  return SORT_OPTIONS.some((o) => o.key === v);
}

/** 모르는 값을 뒤로 보내는 비교자. `dir` 이 -1 이면 내림차순. */
function byNumber(
  a: number | null | undefined,
  b: number | null | undefined,
  dir: 1 | -1,
): number {
  const aMissing = a === null || a === undefined;
  const bMissing = b === null || b === undefined;
  // 모르는 값은 정렬 방향과 **무관하게** 뒤다. 0 으로 치환하면 "가장 싼 집"이 되어버린다.
  if (aMissing || bMissing) return aMissing && bMissing ? 0 : aMissing ? 1 : -1;
  return (a - b) * dir;
}

/**
 * 정렬된 **새 배열**을 돌려준다(입력을 뒤집지 않는다 — 리액트 상태 배열이 들어온다).
 *
 * `default`(추천 순)의 정의: AI 추천 순위가 붙은 후보를 순위대로 앞에 세우고,
 * 나머지는 **서버가 준 순서 그대로** 둔다. 순위가 없을 때 몰래 가격순으로 바꾸지 않는다 —
 * "추천 순"이라고 적어 놓고 다른 기준으로 줄 세우면 그것도 화면의 거짓말이다.
 * (Array.prototype.sort 는 ES2019 부터 안정 정렬이라 동점은 원래 순서가 유지된다.)
 */
export function sortComplexes(
  items: ComplexItem[],
  key: SortKey,
  rankById: Record<number, number> = {},
): ComplexItem[] {
  const out = [...items];

  switch (key) {
    case "price_asc":
      return out.sort((a, b) => byNumber(a.recent_price_krw, b.recent_price_krw, 1));
    case "price_desc":
      return out.sort((a, b) => byNumber(a.recent_price_krw, b.recent_price_krw, -1));
    case "built_desc":
      return out.sort((a, b) => byNumber(a.built_year, b.built_year, -1));
    case "households_desc":
      return out.sort((a, b) => byNumber(a.households, b.households, -1));
    default:
      return out.sort((a, b) => byNumber(rankById[a.id], rankById[b.id], 1));
  }
}
