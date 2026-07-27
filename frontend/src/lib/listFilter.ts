/**
 * 목록 필터 — **예산 토글 + 특성 칩**을 한 번에 계산하는 순수 함수.
 *
 * 이 모듈이 지키는 약속 세 가지
 * ------------------------------
 *  ① **조용히 사라지지 않는다.** 무엇을 몇 건 숨겼는지 항상 숫자로 돌려준다.
 *     화면은 그 숫자를 반드시 적는다("예산 초과 7건 숨김").
 *  ② **모름을 아님으로 접지 않는다.** 가격을 모르면 "예산 내"도 "예산 초과"도 아니고,
 *     세대수를 모르면 "대단지 아님"이 아니다. 판정 불가는 판정 불가로 세어 돌려준다.
 *  ③ **순위를 다시 매기지 않는다.** 걸러내되 순서와 원본(rank)은 건드리지 않는다 —
 *     필터 결과에 1,2,3 을 새로 붙이면 그건 새 순위처럼 읽히는 거짓 정보다.
 *
 * 계산 순서(중요): **예산 → 태그 개수 → 태그 필터**.
 * 칩의 개수는 "예산 필터가 걸린 뒤" 기준이어야 한다. 그러지 않으면 칩이 5라고 적혀
 * 있는데 눌러보면 2건이 나오는, 화면이 거짓말하는 상태가 된다.
 */
import { tagVerdict, TAG_DEFS, tagsOf, type TagFacts, type TagId } from "./tags";

/** 예산 판정. `unknown` = 판정 불가(예산을 모르거나 가격을 모른다). */
export type BudgetVerdict = "within" | "over" | "unknown";

function positive(v: number | null | undefined): v is number {
  return typeof v === "number" && Number.isFinite(v) && v > 0;
}

/**
 * 이 가격이 예산 안인가.
 *
 * ⚠️ **가격 미상은 "예산 내"가 아니다.** 서버의 `over_budget` 은 가격을 모르면 false 를
 *    주는데(파이썬 `bool(max and price and price > max)`), 그걸 그대로 믿으면
 *    12억짜리일 수도 있는 단지가 "예산 내"로 둔갑한다. 그래서 여기서 다시 판정한다.
 *    예산 자체를 모를 때(자산 미입력)도 마찬가지로 판정하지 않는다.
 */
export function budgetVerdict(
  priceKrw: number | null | undefined,
  budgetKrw: number | null | undefined,
): BudgetVerdict {
  if (!positive(budgetKrw)) return "unknown";
  if (!positive(priceKrw)) return "unknown";
  return priceKrw <= budgetKrw ? "within" : "over";
}

/** 필터에 넣을 항목 하나. 화면 타입(T)과 판정에 필요한 사실을 분리해 둔다. */
export interface FilterSource<T> {
  item: T;
  /** 비교에 쓸 가격(원). 모르면 null. */
  priceKrw: number | null;
  facts: TagFacts;
}

export interface FilterState {
  /** 예산 내만 보기. */
  budgetOnly: boolean;
  /** 실효 예산(희망가 우선, 없으면 실구매 한도). 모르면 null → 판정 불가. */
  budgetKrw: number | null;
  /** 고른 특성 칩. 2개 이상이면 **교집합**이다. */
  tags: TagId[];
  /** 판정 불가 항목을 함께 볼 것인가(기본 false — 확실한 것만 보여준다). */
  includeUnknownTag: boolean;
}

export interface FilteredEntry<T> {
  item: T;
  /** 이 항목이 **확실히** 만족하는 태그. 배지의 유일한 근거. */
  tags: TagId[];
  /** 고른 태그 중 이 항목에서 판정할 수 없는 것. 비어 있지 않으면 "판정 불가로 함께 보인" 항목. */
  unknownTags: TagId[];
  budget: BudgetVerdict;
}

export interface TagChip {
  id: TagId;
  icon: string;
  label: string;
  criterion: string;
  /** 확실히 해당하는 건수(예산 필터 적용 후 기준). */
  count: number;
  /** 판정 불가 건수. `count === 0 && unknown > 0` 이면 "없다"가 아니라 "모른다"이다. */
  unknown: number;
  selected: boolean;
  /** 누를 게 없는 칩. 숨기지는 않는다 — "이 지역엔 대단지가 없다"도 정보다. */
  disabled: boolean;
}

export interface FilterOutcome<T> {
  /** 화면에 그릴 항목. **원래 순서 그대로**(재정렬·재번호 없음). */
  entries: FilteredEntry<T>[];
  /** 필터 전 전체 건수. */
  total: number;
  /** 예산 판정이 가능한가(예산을 알고 있는가). false 면 예산 토글은 켤 수 없다. */
  budgetKnown: boolean;
  /** 전체 중 예산 초과 건수(토글 상태와 무관한 사실). */
  overBudget: number;
  /** 전체 중 가격을 몰라 판정 불가인 건수. */
  priceUnknown: number;
  /** 예산 토글이 **실제로 숨긴** 건수. */
  hiddenOverBudget: number;
  hiddenPriceUnknown: number;
  chips: TagChip[];
  /** 고른 태그를 판정할 수 없어 빠진 건수. */
  hiddenTagUnknown: number;
  /** 판정 불가지만 사용자가 켜서 함께 보이는 건수. */
  shownTagUnknown: number;
  /** 칩 선택 방식. `intersection` 이면 화면이 "모두 만족"이라고 말해야 한다. */
  mode: "all" | "single" | "intersection";
}

/**
 * 고른 태그들에 대한 이 항목의 판정.
 *  · 하나라도 `no` → 확실히 아니다(제외).
 *  · 전부 `yes` → 통과.
 *  · `no` 는 없고 `unknown` 이 있다 → **판정 불가**(모름을 아님으로 접지 않는다).
 */
function matchTags(
  facts: TagFacts,
  selected: TagId[],
): { pass: boolean; unknown: TagId[] } {
  const unknown: TagId[] = [];
  for (const id of selected) {
    const v = tagVerdict(id, facts);
    if (v === "no") return { pass: false, unknown: [] };
    if (v === "unknown") unknown.push(id);
  }
  return { pass: unknown.length === 0, unknown };
}

export function filterList<T>(
  sources: FilterSource<T>[],
  state: FilterState,
): FilterOutcome<T> {
  const budgetKnown = positive(state.budgetKrw);
  const selected = TAG_DEFS.filter((t) => state.tags.includes(t.id)).map((t) => t.id);

  // ① 예산 — 판정은 항상 하고, 숨기는 건 토글이 켜졌을 때만.
  const withBudget = sources.map((s) => ({
    ...s,
    budget: budgetVerdict(s.priceKrw, state.budgetKrw),
  }));

  const overBudget = withBudget.filter((s) => s.budget === "over").length;
  const priceUnknown = withBudget.filter((s) => s.budget === "unknown").length;

  // 예산을 모르면 토글이 아무것도 못 한다 — 전부 숨겨서 빈 화면을 만들지 않는다.
  const budgetActive = state.budgetOnly && budgetKnown;
  const afterBudget = budgetActive
    ? withBudget.filter((s) => s.budget === "within")
    : withBudget;

  // ② 칩 개수 — **예산 필터 적용 후** 기준(칩 숫자와 실제 결과가 어긋나지 않게).
  const chips: TagChip[] = TAG_DEFS.map((def) => {
    let count = 0;
    let unknown = 0;
    for (const s of afterBudget) {
      const v = tagVerdict(def.id, s.facts);
      if (v === "yes") count += 1;
      else if (v === "unknown") unknown += 1;
    }
    return {
      id: def.id,
      icon: def.icon,
      label: def.label,
      criterion: def.criterion,
      count,
      unknown,
      selected: selected.includes(def.id),
      disabled: count === 0,
    };
  });

  // ③ 태그 필터
  let hiddenTagUnknown = 0;
  let shownTagUnknown = 0;
  const entries: FilteredEntry<T>[] = [];

  for (const s of afterBudget) {
    const base = { item: s.item, tags: tagsOf(s.facts), budget: s.budget };
    if (selected.length === 0) {
      entries.push({ ...base, unknownTags: [] });
      continue;
    }
    const { pass, unknown } = matchTags(s.facts, selected);
    if (pass) {
      entries.push({ ...base, unknownTags: [] });
    } else if (unknown.length > 0) {
      // 판정 불가 — 숨기더라도 **몇 건인지 반드시 돌려준다**.
      if (state.includeUnknownTag) {
        shownTagUnknown += 1;
        entries.push({ ...base, unknownTags: unknown });
      } else {
        hiddenTagUnknown += 1;
      }
    }
  }

  return {
    entries,
    total: sources.length,
    budgetKnown,
    overBudget,
    priceUnknown,
    hiddenOverBudget: budgetActive ? overBudget : 0,
    hiddenPriceUnknown: budgetActive ? priceUnknown : 0,
    chips,
    hiddenTagUnknown,
    shownTagUnknown,
    mode: selected.length === 0 ? "all" : selected.length === 1 ? "single" : "intersection",
  };
}

/**
 * 판정에 필요한 사실이 목록 전체에서 **하나도 없는** 태그들.
 *
 * 칩에 "0" 이라고만 적으면 "이 지역엔 대단지가 없다"로 읽힌다. 그런데 세대수를 아무도
 * 모르는 상태라면 그건 "없다"가 아니라 "모른다"다 — 화면이 그 둘을 구분해 말하도록
 * 재료를 따로 돌려준다.
 */
export function unmeasurableTags<T>(outcome: FilterOutcome<T>): TagChip[] {
  return outcome.chips.filter((c) => c.count === 0 && c.unknown > 0);
}

/** 판정 불가 태그 이름(사실 이름 기준) — "세대수 · 역 거리" 처럼 적는다. */
export function missingFactLabels(chips: TagChip[]): string[] {
  return chips.map((c) => TAG_DEFS.find((t) => t.id === c.id)?.factLabel ?? c.label);
}

/* ── 화면에 적을 문장 ─────────────────────────────────────────────────────
 * 문장을 컴포넌트가 아니라 여기서 만드는 이유: **숨긴 건수를 말하는 것이 계약**이라
 * 테스트로 고정해야 하는데, 문장이 JSX 안에 흩어져 있으면 조건 하나를 지워도 아무도
 * 모른다. 숫자를 만든 자리에서 문장까지 만들어 둘이 어긋날 수 없게 한다. */

/**
 * 예산 토글이 지금 무엇을 하고 있는지. `null` = 할 말이 없다(아무것도 숨기지 않았고
 * 초과 항목도 없다). 할 말이 없을 때 말하지 않는 것도 규칙이다(규칙 5).
 */
export function budgetNotice<T>(o: FilterOutcome<T>, budgetOnly: boolean): string | null {
  if (!o.budgetKnown) {
    return "내 예산을 아직 계산하지 못해 예산 내 여부를 판정할 수 없습니다.";
  }

  if (budgetOnly) {
    const parts: string[] = [];
    if (o.hiddenOverBudget > 0) parts.push(`예산 초과 ${o.hiddenOverBudget}건`);
    if (o.hiddenPriceUnknown > 0) parts.push(`가격 미상 ${o.hiddenPriceUnknown}건`);
    if (parts.length === 0) return "예산을 넘는 항목이 없습니다 — 숨긴 항목 없음.";
    const tail =
      o.hiddenPriceUnknown > 0 ? " — 가격을 모르는 항목은 예산 내로 치지 않습니다." : "";
    return `${parts.join(" · ")} 숨김${tail}`;
  }

  const parts: string[] = [];
  if (o.overBudget > 0) parts.push(`예산 초과 ${o.overBudget}건`);
  if (o.priceUnknown > 0) parts.push(`가격 미상 ${o.priceUnknown}건`);
  if (parts.length === 0) return null;
  return `${parts.join(" · ")}도 함께 보는 중`;
}

/** 태그 필터가 판정 불가 항목을 어떻게 했는지. `null` = 그런 항목이 없다. */
export function tagUnknownNotice<T>(o: FilterOutcome<T>): string | null {
  const selected = o.chips.filter((c) => c.selected);
  const facts = missingFactLabels(selected).join(" · ");

  if (o.hiddenTagUnknown > 0) {
    return `${facts} 정보가 없어 판정할 수 없는 ${o.hiddenTagUnknown}건은 제외했습니다 — '아님'이 아니라 '모름'입니다.`;
  }
  if (o.shownTagUnknown > 0) {
    return `${facts} 정보가 없는 ${o.shownTagUnknown}건을 함께 보는 중입니다 — 태그가 없는 건 '아님'이 아니라 '모름'입니다.`;
  }
  return null;
}

/**
 * 목록 전체에서 판정 자체가 불가능한 태그 안내. `null` = 전부 판정 가능하다.
 * "0건"과 "모름"을 구분하는 문장이다 — 이게 없으면 빈 칩이 "이 지역엔 없다"로 읽힌다.
 */
export function unmeasurableNotice<T>(o: FilterOutcome<T>): string | null {
  const rows = unmeasurableTags(o);
  if (rows.length === 0) return null;
  const parts = rows.map((c) => {
    const fact = TAG_DEFS.find((t) => t.id === c.id)?.factLabel ?? c.label;
    return `${c.label}(${fact} 미상 ${c.unknown}건)`;
  });
  return `${parts.join(" · ")} — 해당 단지가 없는 게 아니라 판정할 정보가 없습니다.`;
}
