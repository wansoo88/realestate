/**
 * "내 조건"을 **추천 요청**으로 옮기는 순수 변환 — 지도(`lib/mapFilters`)의 짝이다.
 *
 * 왜 이 파일이 따로 있나 (FE-4)
 * -----------------------------
 * 서버는 추천 요청에 조건 필드가 **없으면** 저장된 내 조건(`user_preference.prefer`)을
 * 폴백으로 쓴다(`app/domain/conditions.py`). 프론트가 한 줄 빠뜨려도 조건이 증발하지
 * 않게 만든 안전장치인데, 그 폴백 때문에 **조건을 끄는 방법이 사라졌다**:
 *
 *   지도에서 면적 칩을 끈다 → 지도는 필터가 풀린다
 *                          → 추천은 "안 보냄"으로 읽고 저장된 면적으로 계속 거른다
 *
 * 같은 화면의 같은 스위치가 두 목록에 정반대로 작동한 것이다. 사용자는 지도에는 있는데
 * 추천에는 없는 단지를 보고도 이유를 알 수 없다.
 *
 * ⚠️ 그래서 이 모듈이 지키는 단 하나의 규칙: **"안 보냄"과 "끔"은 다른 뜻이다.**
 *      · 조건이 켜져 있다 → 아무것도 안 보낸다(저장본 폴백 = 예전 동작 그대로)
 *      · 조건을 껐다     → `use_saved_conditions: false` 를 **명시적으로** 보낸다
 *    그리고 화면이 "지금 어떤 조건으로 돌았는지"를 말할 수 있도록, 요청 필드와 표시
 *    문구를 **같은 상태에서 같은 함수로** 만든다(mapFilters 가 쿼리와 칩을 함께 만드는 것과
 *    같은 이유 — 둘이 갈라지면 화면이 거짓말을 한다).
 */
import { formatKrwShort } from "./format";
import type { MapFilterState } from "./mapFilters";

/** 0·음수·NaN·null 을 한 번에 걸러낸다(면적 0㎡·0세대·0원 상한은 조건이 아니다). */
function positive(v: number | null | undefined): number | undefined {
  return typeof v === "number" && Number.isFinite(v) && v > 0 ? v : undefined;
}

/* ─────────────────────────────────────────────────────────────────────────
 * ① 요청 필드
 * ───────────────────────────────────────────────────────────────────────── */

/** `POST /recommendations` 에 실을 조건 필드. 이름은 **계약 그대로**(snake_case). */
export interface ConditionFields {
  /** 예산 상한. 희망가를 정하지 않았으면 null — 서버가 실구매 가능 금액을 쓴다. */
  budget_override_krw: number | null;
  /** 저장된 내 조건을 이번 요청에 쓸 것인가. **끌 때만** 실린다(생략 = 예전대로 폴백). */
  use_saved_conditions?: false;
  /** 저장본을 끄면서도 살려야 하는 조건(아래 주석 참조). */
  min_households?: number;
}

/**
 * 지금 켜진 조건 → 추천 요청 필드.
 *
 * `min_households` 를 따로 실어 보내는 이유
 * -----------------------------------------
 * `use_saved_conditions:false` 는 **저장된 조건 전부**를 끈다. 그런데 화면의 칩은
 * 예산·면적·연식 셋뿐이라, 칩이 없는 `min_households` 까지 함께 꺼지면 사용자가 끈 적
 * 없는 조건이 조용히 사라진다. 칩이 말하지 않은 것을 칩이 끄면 안 되므로 명시적으로
 * 다시 싣는다. (희망 매매가도 같은 이유로 `budget_override_krw` 에 항상 명시된다.)
 */
export function conditionFields(f: MapFilterState): ConditionFields {
  const fields: ConditionFields = {
    // 희망가는 사용자가 정한 입력이므로 저장본 폴백에 기대지 않고 늘 명시한다.
    // (이게 없으면 `use_saved_conditions:false` 를 보내는 순간 희망가까지 함께 죽는다.)
    budget_override_krw: positive(f.targetPriceKrw) ?? null,
  };
  if (f.preferApplied) return fields; // 켜져 있다 = 예전 동작. 아무것도 덧붙이지 않는다.

  fields.use_saved_conditions = false;
  const households = positive(f.prefer?.min_households);
  if (households !== undefined) fields.min_households = households;
  return fields;
}

/* ─────────────────────────────────────────────────────────────────────────
 * ② 화면 문구 — "이 결과는 어떤 조건으로 나왔나"
 * ───────────────────────────────────────────────────────────────────────── */

/** 이 조건이 지도와 추천 중 **어디에** 걸리는가. */
export type ConditionSide =
  /** 지도 목록과 추천 양쪽에 같게 걸린다 */
  | "both"
  /** 추천에만 걸린다 — 지도 목록에는 안 걸리므로 두 목록이 달라진다 */
  | "rec_only";

export interface AppliedCondition {
  id: "budget" | "area" | "built" | "households";
  /** 사용자에게 그대로 보여줄 문구("전용 59~84㎡") */
  label: string;
  side: ConditionSide;
}

export interface ConditionPlan {
  /** 이번 추천에 **실제로** 걸리는 조건 */
  on: AppliedCondition[];
  /** 값은 있지만 사용자가 꺼 둔 조건 — 지도와 추천 **양쪽 모두** 적용하지 않는다 */
  off: AppliedCondition[];
  /** 지도와 추천에 다르게 걸리는 조건이 있는가(있으면 화면이 그 사실을 말해야 한다) */
  diverged: boolean;
}

function areaLabel(min: number | undefined, max: number | undefined): string {
  if (min !== undefined && max !== undefined) return `전용 ${min}~${max}㎡`;
  if (min !== undefined) return `전용 ${min}㎡ 이상`;
  return `전용 ${max}㎡ 이하`;
}

/**
 * 지금 상태 → "무슨 조건으로 추천하는가".
 *
 * `conditionFields` 와 **같은 판단**을 써야 한다 — 요청과 표시가 갈라지면 화면이
 * "면적 조건 없이 분석했습니다"라고 말하는 동안 서버는 면적으로 거를 수 있다.
 */
export function conditionPlan(f: MapFilterState): ConditionPlan {
  const on: AppliedCondition[] = [];
  const off: AppliedCondition[] = [];

  /* 예산 — 다른 조건과 달리 **끌 수 없다.**
     칩을 꺼도 추천은 예산 안에서만 후보를 세운다(못 사는 집은 취향이 아니라 후보 밖이다).
     지도만 풀리므로 그 차이를 rec_only 로 말한다 — 말하지 않으면 "지도엔 보이는데
     추천엔 없는 단지"의 이유가 화면 어디에도 없다. */
  const target = positive(f.targetPriceKrw);
  const budget = positive(f.budgetKrw);
  if (target !== undefined) {
    on.push({
      id: "budget",
      label: `희망가 ${formatKrwShort(target)} 이하`,
      side: f.budgetApplied ? "both" : "rec_only",
    });
  } else if (budget !== undefined) {
    on.push({
      id: "budget",
      label: `내 예산 ${formatKrwShort(budget)} 이내`,
      side: f.budgetApplied ? "both" : "rec_only",
    });
  }

  const min = positive(f.prefer?.area_min_m2);
  const max = positive(f.prefer?.area_max_m2);
  if (min !== undefined || max !== undefined) {
    const item: AppliedCondition = { id: "area", label: areaLabel(min, max), side: "both" };
    (f.preferApplied ? on : off).push(item);
  }

  const built = positive(f.prefer?.built_after);
  if (built !== undefined) {
    const item: AppliedCondition = {
      id: "built",
      label: `${built}년 이후 준공`,
      side: "both",
    };
    (f.preferApplied ? on : off).push(item);
  }

  /* 최소 세대수는 **지도에 없는 조건**이다(`/map/complexes` 에 파라미터 자체가 없다).
     칩도 없으므로 끌 수 없고, 그래서 항상 추천에만 걸린다. 숨기면 "지도엔 있는데
     추천엔 없는 단지"가 또 생긴다. */
  const households = positive(f.prefer?.min_households);
  if (households !== undefined) {
    on.push({
      id: "households",
      label: `${households.toLocaleString("ko-KR")}세대 이상`,
      side: "rec_only",
    });
  }

  return { on, off, diverged: on.some((c) => c.side === "rec_only") };
}

/** 조건 목록 → 한 줄 문구. 걸린 게 없으면 null(할 말이 없다). */
export function conditionText(list: AppliedCondition[]): string | null {
  return list.length === 0 ? null : list.map((c) => c.label).join(" · ");
}
