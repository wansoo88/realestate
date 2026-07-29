/**
 * 목록 필터 — **예산 토글 + 특성 칩**을 한 번에 계산하는 순수 함수.
 *
 * 이 모듈이 지키는 약속 세 가지
 * ------------------------------
 *  ① **조용히 사라지지 않는다.** 무엇을 몇 건 숨겼는지 항상 숫자로 돌려준다.
 *     화면은 그 숫자를 반드시 적는다("예산 초과 7건 숨김").
 *  ② **모름을 아님으로 접지 않는다.** 예산 판정을 못 하면 "예산 내"도 "예산 초과"도 아니고,
 *     세대수를 모르면 "대단지 아님"이 아니다. 판정 불가는 판정 불가로 세어 돌려준다.
 *  ③ **순위를 다시 매기지 않는다.** 걸러내되 순서와 원본(rank)은 건드리지 않는다 —
 *     필터 결과에 1,2,3 을 새로 붙이면 그건 새 순위처럼 읽히는 거짓 정보다.
 *
 * 계산 순서(중요): **예산 → 태그 개수 → 태그 필터**.
 * 칩의 개수는 "예산 필터가 걸린 뒤" 기준이어야 한다. 그러지 않으면 칩이 5라고 적혀
 * 있는데 눌러보면 2건이 나오는, 화면이 거짓말하는 상태가 된다.
 *
 * ⚠️ **이 모듈은 예산을 판정하지 않는다** (CR38-1). 판정(`BudgetVerdict`)은 호출부가
 *    실어 준다. 예전에는 여기서 `가격 ≤ 예산` 을 계산했는데, 그 "예산"이 목록 전체에
 *    **한 숫자**여서 지도처럼 면적이 섞인 목록에서 틀렸다 — 취득세 구간이 85㎡ 를
 *    가로지르면 같은 가격이라도 단지마다 상한이 다르다(실측 차이 198만원).
 *    누가 판정하는지는 목록마다 다르므로(지도 = 서버, 추천 = 화면) **입력으로 받는다.**
 */
import { tagVerdict, TAG_DEFS, tagsOf, type TagFacts, type TagId } from "./tags";

/** 예산 판정. `unknown` = 판정 불가(예산을 모르거나 가격을 모른다). */
export type BudgetVerdict = "within" | "over" | "unknown";

function positive(v: number | null | undefined): v is number {
  return typeof v === "number" && Number.isFinite(v) && v > 0;
}

/**
 * **금액 하나**로 판정한다 — 서버가 판정을 주지 않는 목록에서만 쓴다.
 *
 * ⚠️ **가격 미상은 "예산 내"가 아니다.** 예산 자체를 모를 때(자산 미입력)도 마찬가지로
 *    판정하지 않는다. 서버도 같은 규칙을 쓴다(api-spec §4 — `over_budget: null`).
 *
 * ⚠️ **지도·목록에는 쓰지 않는다** (CR38-1). 실구매 한도는 취득세 구간(85㎡) 때문에
 *    **면적별로 다른 숫자**인데 이 함수는 하나만 받는다. 지도처럼 면적이 섞인 목록에
 *    쓰면 120㎡ 단지의 배지가 84㎡ 한도로 서게 된다. 그런 목록은 항목마다 그 면적의
 *    한도로 판정한 서버 값(`over_budget`)을 쓴다 — `lib/screenBudget.ts`.
 *
 *    지금 이 함수가 남아 있는 자리는 **AI 추천 목록** 하나다. 추천 응답에는 항목별
 *    판정이 없고, 카드가 보여주는 금액(`est_price_krw`)도 지도와 다른 양이라
 *    화면이 그 카드의 금액으로 판정하는 수밖에 없다(근거는 `lib/budgetStatus` 머리말).
 */
export function budgetVerdict(
  priceKrw: number | null | undefined,
  budgetKrw: number | null | undefined,
): BudgetVerdict {
  if (!positive(budgetKrw)) return "unknown";
  if (!positive(priceKrw)) return "unknown";
  return priceKrw <= budgetKrw ? "within" : "over";
}

/**
 * 필터에 넣을 항목 하나. 화면 타입(T)과 판정에 필요한 사실을 분리해 둔다.
 *
 * `budget` 은 **이미 내려진 판정**이다(이 모듈은 판정하지 않는다 — 머리말).
 * 지도·목록은 서버 `over_budget` 을 옮겨 담고(`lib/screenBudget.serverBudgetVerdict`),
 * 추천은 화면이 `budgetVerdict(est_price_krw, …)` 로 만든다.
 */
export interface FilterSource<T> {
  item: T;
  budget: BudgetVerdict;
  facts: TagFacts;
}

export interface FilterState {
  /** 예산 내만 보기. */
  budgetOnly: boolean;
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
  /**
   * 이 목록에서 예산 판정이 **실제로 하나라도 내려졌는가**. false 면 토글은 켤 수 없다.
   *
   * 입력이 아니라 판정 결과에서 센다 — 예산을 알아도 아무도 판정되지 않았으면(서버가
   * 기준을 못 세웠거나 가격을 다 모르면) 토글을 켜 봐야 **빈 화면**만 나온다.
   */
  budgetKnown: boolean;
  /** 전체 중 예산 초과 건수(토글 상태와 무관한 사실). */
  overBudget: number;
  /** 전체 중 예산 판정을 못 한 건수(가격 미상·면적 미상·서버가 기준을 못 세움). */
  budgetUnknown: number;
  /** 예산 토글이 **실제로 숨긴** 건수. */
  hiddenOverBudget: number;
  hiddenBudgetUnknown: number;
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
  const selected = TAG_DEFS.filter((t) => state.tags.includes(t.id)).map((t) => t.id);

  // ① 예산 — 판정은 호출부가 실어 준다. 여기서는 세고, 토글이 켜졌을 때만 숨긴다.
  const withBudget = sources;

  const overBudget = withBudget.filter((s) => s.budget === "over").length;
  const budgetUnknown = withBudget.filter((s) => s.budget === "unknown").length;
  /** 판정이 하나라도 있어야 토글이 할 일이 있다(없으면 켜 봐야 전부 사라진다). */
  const budgetKnown = withBudget.length > budgetUnknown;

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
    budgetUnknown,
    hiddenOverBudget: budgetActive ? overBudget : 0,
    hiddenBudgetUnknown: budgetActive ? budgetUnknown : 0,
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
    // ⚠️ 사유를 여기서 단정하지 않는다. "예산을 아직 계산 못 했다"일 수도 있고
    //    "서버가 이 목록을 판정하지 못했다"일 수도 있는데, 그 사유는 각각
    //    `budgetStatusView`(지도)·추천 패널 머리글이 이미 말한다. 여기서 한 가지로
    //    적으면 나머지 경우에 화면이 거짓말을 한다.
    return "예산 판정이 된 항목이 없어 '예산 내'만 보기를 켤 수 없습니다.";
  }

  if (budgetOnly) {
    const parts: string[] = [];
    if (o.hiddenOverBudget > 0) parts.push(`예산 초과 ${o.hiddenOverBudget}건`);
    if (o.hiddenBudgetUnknown > 0) parts.push(`예산 판정 불가 ${o.hiddenBudgetUnknown}건`);
    if (parts.length === 0) return "예산을 넘는 항목이 없습니다 — 숨긴 항목 없음.";
    const tail =
      o.hiddenBudgetUnknown > 0 ? " — 판정하지 못한 항목은 예산 내로 치지 않습니다." : "";
    return `${parts.join(" · ")} 숨김${tail}`;
  }

  const parts: string[] = [];
  if (o.overBudget > 0) parts.push(`예산 초과 ${o.overBudget}건`);
  if (o.budgetUnknown > 0) parts.push(`예산 판정 불가 ${o.budgetUnknown}건`);
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
