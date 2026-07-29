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
import type { BudgetBasis, Preferences } from "../api/client";
import { formatKrwShort } from "./format";
import type { Purpose } from "./purpose";

export interface MapFilterState {
  /** `/affordability` 로 계산한 **최대** 실구매 가능 금액. 모르면 null. */
  budgetKrw: number | null;
  /** 예산 필터를 켜 두었는가(사용자가 끌 수 있다). */
  budgetApplied: boolean;
  /**
   * 한도 산정 가정 — **자금계획(`/affordability`)과 반드시 같은 값**이어야 한다.
   *
   * 옵셔널로 두지 않는 이유: 빠뜨리면 서버 기본값(`live`)이 조용히 쓰이고, 투자 목적
   * 사용자는 지도 배지(live 기준)와 자금 패널(invest 기준)이 어긋난 채로 본다 —
   * 목적에 따라 대출 절대한도·스트레스 가산이 **달라질 수 있어** 한도가 갈릴 수 있다.
   *
   * ⚠️ **오늘은 아직 안 갈린다** (CR38-4): 운영 데이터에 `purpose` 조건 규칙이 0개라
   *    `live == invest` 다(백엔드 `test_tax_rules_real.py` 가 못박는다). 그래도 값을
   *    싣는 이유는 `lib/purpose.ts` 머리말 참고 — 값은 거기 한 곳에서 온다.
   */
  purpose: Purpose;
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

/** 실효 예산 = **금액 + 그 금액이 무엇인지**. 둘은 항상 같이 정해진다. */
export interface EffectiveBudget {
  /** 상한(원). 모르면 null. */
  krw: number | null;
  /**
   * 그 금액의 정체. 서버 응답 `budget.basis` 와 **같은 어휘**를 쓴다 —
   * 같은 말을 써야 "서버는 한도로, 화면은 희망가로 판정 중"을 대조해 잡아낼 수 있다.
   */
  basis: BudgetBasis | null;
}

/**
 * 지도·추천·목록이 함께 쓰는 실효 예산 상한. 희망가가 있으면 그것, 없으면 한도.
 *
 * ⚠️ 이 우선순위는 **서버 `conditions.resolve_budget_override` 와 같아야 한다**
 *    (api-spec §4). 한쪽만 바뀌면 화면 칩("희망가 9.00억")과 서버 판정이 갈라지고,
 *    그 어긋남은 `lib/budgetStatus` 가 대조해 화면에 말한다.
 *
 * 🔐 **이 숫자는 메모리 밖으로 나가지 않는다**(SR32-1). 화면 문구(칩·배지)와 목록
 *    필터에만 쓴다. 서버로 보낼 때는 `budget=mine` 플래그뿐이고 금액은 서버가 만든다.
 */
export function effectiveBudget(f: MapFilterState): EffectiveBudget {
  const target = positive(f.targetPriceKrw);
  if (target !== undefined) return { krw: target, basis: "target_price" };
  const budget = positive(f.budgetKrw);
  if (budget !== undefined) return { krw: budget, basis: "max_purchase" };
  return { krw: null, basis: null };
}

/** 금액만 필요할 때. `effectiveBudget` 과 갈라질 수 없게 그것을 통해서만 만든다. */
export function effectiveBudgetKrw(f: MapFilterState): number | null {
  return effectiveBudget(f).krw;
}

/**
 * 화면이 **초과 표시에 실제로 쓰는** 상한. 칩(`budgetApplied`)을 끄면 `null` 이다.
 *
 * `effectiveBudget` 과 나눈 이유 (CR37-7)
 * ---------------------------------------
 * 예산 칩은 **꺼도 아무 일이 안 일어났다.** 배지도 그대로, 목록도 그대로 — 남는 변화가
 * 없으니 켜진 상태를 믿을 근거도 없었다("눌러도 무반응인 스위치"의 정확한 형태다).
 * 이제 칩은 **초과 표시를 켜고 끈다**: 끄면 이 값이 `null` 이 되어 마커 빨간 표시·카드
 * 배지·초과 집계가 함께 사라지고, 그 사실을 목록 위 문장이 말한다.
 *
 * ⚠️ **거르지는 않는다.** 예산 밖 단지를 지도에서 지우면 "얼마나 모자란가"라는 이 제품의
 *    핵심 정보가 사라진다(`ux/README §4`). 숨기는 스위치는 목록의 `예산 내` 토글이고,
 *    그건 **몇 건을 숨겼는지**까지 말한다. 둘은 하는 일이 다르다:
 *      · 칩(내 조건)   = 초과를 **표시할지**
 *      · 토글(목록 위) = 초과를 **숨길지** (표시가 켜져 있어야 의미가 있다)
 *
 * `effectiveBudget` 은 그대로 둔다 — AI 추천 조건 문구(`recommendConditions`)와
 * 서버 요청 판정(`budgetRequested`)은 "무엇이 기준인가"를 물을 뿐, 표시 여부와 무관하다.
 */
export function displayBudget(f: MapFilterState): EffectiveBudget {
  return f.budgetApplied ? effectiveBudget(f) : { krw: null, basis: null };
}

/**
 * 화면이 `budget=mine` 을 **실제로 보내는가**.
 *
 * 이 판정을 buildMapQuery 밖에서 다시 쓰기 때문에 함수로 뺐다 — 응답의 `budget` 블록을
 * 해석하려면 "우리가 요청하긴 했는가"를 알아야 하는데, 조건을 두 벌로 적으면
 * 언젠가 한쪽만 바뀌어 "안 켰는데 켰다고 말하는" 화면이 된다.
 */
export function budgetRequested(f: MapFilterState): boolean {
  return f.budgetApplied && effectiveBudget(f).krw !== null;
}

/**
 * "예산 필터를 켰다"를 나타내는 **비민감 플래그**.
 *
 * 금액이 아니라 이 문자열을 보내는 이유(SR32-1)
 * ---------------------------------------------
 * 예전에는 `max_price_krw=1314310000` 을 URL 에 실었다. 그 숫자는 사용자가 입력한 값이
 * 아니라 **암호화 저장된 자산·소득·대출을 복호화해 계산한 실구매 가능 금액**이고,
 * URL 은 nginx·uvicorn 접근 로그에 평문으로 쌓인다(로테이션 파일이 0644 였다).
 *
 * `/map/complexes` 는 인증된 경로이고 서버는 이미 그 사용자의 프로필과 저장된
 * 희망 매매가를 갖고 있다 — 화면이 금액을 계산해 되돌려 줄 이유가 없다.
 *
 * ⚠️ **희망가(사용자가 슬라이더로 정한 값)도 싣지 않는다.** 자산 파생값보다 민감도가
 *    낮은 건 맞지만 ① 여전히 "이 사람이 집에 얼마를 쓸 수 있는가"라는 개인 금융정보이고,
 *    ② 서버가 이미 `user_preference.prefer.target_price_krw` 로 갖고 있어 보내도 얻는 게
 *    없으며, ③ URL 만 봐서는 희망가인지 한도인지 구분되지 않아 "희망가는 괜찮다"는 예외를
 *    두는 순간 같은 통로가 다시 열린다. 대신 추천 요청은 **본문**이라 그대로 실어 보낸다
 *    (`budget_override_krw` — 본문은 접근 로그에 남지 않는다).
 */
export const BUDGET_SCOPE_MINE = "mine";

export interface MapQuery {
  bbox: string;
  zoom: number;
  /**
   * `"mine"` = 내 예산(희망가 우선, 없으면 실구매 한도) 기준으로 **초과를 표시해 달라**.
   * **서버가 저장된 프로필로 상한을 산출한다.** 화면과 서버가 같은 우선순위를 써야
   * 칩 문구("희망가 9.00억 초과 표시")와 서버 판정이 어긋나지 않는다 — api-spec 계약.
   * (거르지는 않는다 — 서버도 이 값으로 후보를 줄이지 않고 `over_budget` 만 채운다.)
   */
  budget?: typeof BUDGET_SCOPE_MINE;
  /**
   * 한도 산정 가정. **항상 싣는다**(기본값에 기대지 않는다).
   *
   * 서버 기본값도 `live` 이고 오늘은 두 목적의 한도가 같아서(CR38-4) 보내나 마나로
   * 보이지만, 투자 모드가 생기는 날 "안 보냈으니 live 겠지"가 곧바로 어긋남이 된다 —
   * 그리고 그 어긋남은 화면 어디에도 표시가 없다(같은 단지의 배지와 자금계획이 다른
   * 말을 할 뿐이다).
   */
  purpose: Purpose;
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
  // 🔐 금액은 없고 열거값만 있다. `purpose` 는 자산이 아니라 **가정**이라 URL 에 실린다.
  const q: MapQuery = { bbox, zoom, purpose: f.purpose };

  // 🔐 금액이 아니라 플래그. 그리고 **칩이 뜨는 조건과 같을 때만** 보낸다 —
  //    화면에 "내 예산 …" 칩이 없는데 서버만 조용히 예산으로 거르면, 사용자는
  //    무엇 때문에 단지가 안 보이는지 알 길이 없다(이 파일 머리말의 원칙).
  if (budgetRequested(f)) q.budget = BUDGET_SCOPE_MINE;

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

/**
 * "조건이 바뀌었으니 지도를 다시 조회하라"를 판정하는 키. **요청이 아니라 비교용**이다.
 *
 * 쿼리만 비교하면 안 되는 이유(SR32-1 이후 생긴 함정)
 * ---------------------------------------------------
 * 이제 쿼리에는 금액이 없고 `budget=mine` 플래그만 실린다. 그래서 사용자가 희망가를
 * 9억 → 7억으로 바꿔도 **쿼리는 글자 하나 안 바뀐다** — 쿼리로만 비교하면 지도가
 * 옛 결과 그대로 남는다(서버가 산출할 상한은 바뀌었는데 화면은 모른다).
 * 그래서 여기서는 실효 금액까지 본다.
 *
 * ⚠️ 이 문자열은 `useEffect` 의존성 비교에만 쓴다 — **URL·저장소·로그로 나가지 않는다.**
 */
export function mapFilterKey(f: MapFilterState): string {
  return JSON.stringify([
    buildMapQuery("", 0, f),
    f.budgetApplied ? effectiveBudgetKrw(f) : null,
  ]);
}

export interface FilterChip {
  id: "budget" | "area" | "built";
  /** 켜져 있을 때 화면에 뜨는 문구. "면적 59~85㎡" 처럼 **무엇이 걸렸는지** 말한다. */
  label: string;
  active: boolean;
}

/**
 * 지금 무엇이 적용됐는지 보여줄 칩 목록.
 *
 * 끌 수 있는 것만 칩으로 만든다(값이 아예 없는 조건은 칩도 만들지 않는다 —
 * 끌 게 없는 스위치를 보여주면 사용자는 그걸 켜면 뭔가 될 거라고 오해한다).
 *
 * ⚠️ 예산 칩 문구는 **"이하"가 아니다** (CR37-7). 예전엔 "희망가 9.00억 이하"였는데
 *    지도·목록은 예산으로 **거르지 않는다** — 9억을 넘는 단지도 그대로 나온다(의도된 결정:
 *    `ux/README §4`, "왜 후보에 없는지 보이게 한다"). 라벨이 하는 일과 다른 말을 하면
 *    사용자는 결과를 잘못 읽는다("이하만 보고 있구나").
 *    이 칩이 실제로 하는 일은 **초과 표시를 켜고 끄는 것**이라 그대로 적는다
 *    (`displayBudget`). 거르는 스위치는 목록 위 `예산 내` 토글이고 숨긴 건수까지 말한다.
 */
export function filterChips(f: MapFilterState): FilterChip[] {
  const chips: FilterChip[] = [];

  const target = positive(f.targetPriceKrw);
  if (target !== undefined) {
    // 희망가를 정했으면 칩도 그렇게 말해야 한다 — "내 예산"이라고 쓰면 사용자가 정한 값이
    // 아니라 서버가 계산한 한도로 읽힌다(둘은 다른 숫자다).
    chips.push({
      id: "budget",
      label: `희망가 ${formatKrwShort(target)} 초과 표시`,
      active: f.budgetApplied,
    });
  } else if (positive(f.budgetKrw) !== undefined) {
    chips.push({
      id: "budget",
      // 두 갈래가 **같은 어법**을 쓴다 — 기준 이름만 다르고 하는 일은 똑같기 때문이다.
      label: `내 예산 ${formatKrwShort(f.budgetKrw)} 초과 표시`,
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
