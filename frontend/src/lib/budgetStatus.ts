/**
 * 서버가 말한 **예산 기준**(`/map/complexes` 응답의 `budget` 블록)을 화면 문장으로 옮긴다.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * 정본은 무엇인가 — **지도·목록의 표시는 서버 판정(`over_budget`)이 정본이다.** (CR38-1)
 *
 * 직전까지는 화면 판정이 정본이었고, 근거가 셋이었다. 서버가 **항목별 면적으로**
 * 판정하도록 고쳐지면서 그 셋 중 둘의 전제가 무너졌다. 다시 따져 적는다.
 *
 *  ① *"화면이 보여주는 숫자로 판정해야 한다"* — **지금도 맞고, 이제 서버가 그렇다.**
 *     서버는 카드에 찍히는 바로 그 값(`recent_price_krw`)으로 판정하고, 비교 방향도
 *     같다(`price > cap`). 다른 것은 **상한**뿐인데, 취득세 구간(85㎡) 때문에 상한은
 *     원래 면적별로 다른 숫자다. 화면은 그 여러 숫자를 알지 못한다(금액을 응답에
 *     싣지 않는다 — SR32-1). 그래서 이 근거는 이제 **서버 쪽을 가리킨다.**
 *
 *  ② *"판정이 필요한 자리가 지도만이 아니다"* — **범위가 줄었다.** 목록 카드와 예산
 *     토글은 지도와 **같은 응답**(`map.items`)을 쓴다. 서버 판정이 지도 응답에만 있다는
 *     사실은 이 셋에게는 제약이 아니다. 남는 자리는 **AI 추천 목록** 하나다.
 *
 *  ③ *"서버 판정은 되짚을 수 없다"* — **사실이지만 값을 정한다.**
 *     되짚을 수 있으나 **틀린 숫자**보다 불투명하지만 **맞는 숫자**가 낫다.
 *     그리고 되짚기의 알맹이(무엇을 기준으로 삼았는가)는 `budget.basis` 로 오고,
 *     아래 `basisMismatch` 가 그걸 화면 칩과 대조해 사유 문장까지 붙인다.
 *
 * 서버가 침묵하는 자리는 어떻게 하나 — **AI 추천 목록.**
 * 추천 응답에는 항목별 판정이 없다. 그 목록은 화면이 `est_price_krw`(그 카드가 보여주는
 * 금액)로 판정한다. 두 목록이 서로 다른 말을 하지 않는 이유:
 *   · 추천 카드에는 **예산 배지가 없다**(`ReportCard`). 화면 판정은 그 목록의
 *     `예산 내` 토글이 몇 건을 숨겼는지 세는 데만 쓰이고 지도 배지와 섞이지 않는다.
 *   · 두 목록은 애초에 **다른 금액**을 말한다(지도 = 최근 체결 1건, 추천 = 창 중위를
 *     기준월로 환산한 추정가 — CR35-4). 각자 자기가 보여주는 금액으로 판정하는 것이
 *     ①의 원칙이다.
 *
 * ⚠️ `over_budget` 은 **3값**이다(boolean | null). `null` = 판정 못 함.
 *    `?? false` 로 접으면 "예산 내"와 "모른다"가 같은 값이 된다 — 그 접힘을 한 자리로
 *    좁혀 막는 것이 `lib/screenBudget.ts` 다.
 * ─────────────────────────────────────────────────────────────────────────────
 */
import type { BudgetBasis, MapBudget } from "../api/client";
import { plainReason } from "./plainTerms";

/** 서버가 준 사유 문장의 길이 상한. 잘라 쓰되 **내용을 지어내지 않는다**. */
const REASON_MAX = 200;

/** 제어문자(줄바꿈·탭 포함)인가 — 한 줄 안내가 레이아웃을 깨지 않게 공백으로 바꾼다. */
function isControl(ch: string): boolean {
  const code = ch.codePointAt(0) ?? 32;
  return code < 0x20 || code === 0x7f;
}

/**
 * 서버 문장을 화면에 싣기 전 손질 — 제어문자 제거 · 공백 정리 · 길이 상한.
 * (HTML 이스케이프는 React 가 한다. 이 문자열이 `innerHTML` 로 나가는 경로는 없다.)
 */
function tidy(text: string): string {
  const flat = Array.from(text)
    .map((ch) => (isControl(ch) ? " " : ch))
    .join("")
    .replace(/\s{2,}/g, " ")
    .trim();
  return flat.length > REASON_MAX ? `${flat.slice(0, REASON_MAX)}…` : flat;
}

/** 예산 기준의 사람 말. 모르는 값은 지어내지 않고 "알 수 없는 기준"이라고 한다. */
export function basisLabel(basis: BudgetBasis | null): string {
  switch (basis) {
    case "target_price":
      return "저장한 희망 매매가";
    case "max_purchase":
      return "자산으로 계산한 한도";
    default:
      // 계약에 없는 값이 오면(서버가 어휘를 늘리면) 이름을 지어내지 않는다.
      return "알 수 없는 기준";
  }
}

export interface BudgetStatusView {
  /**
   * 서버가 예산 기준을 세웠는가.
   * **`null` = 서버가 말하지 않았다**(응답에 `budget` 블록이 없는 구버전) —
   * "적용 안 됨"이 아니다. 둘을 같은 값으로 접지 않는다.
   */
  applied: boolean | null;
  /** 화면에 그대로 적을 문장. `null` = 할 말 없음(할 말 없으면 말하지 않는다). */
  notice: string | null;
  /** 서버와 화면이 **다른 기준**을 쓰고 있는가(희망가 ↔ 자산 한도). */
  basisMismatch: boolean;
}

const SILENT: BudgetStatusView = { applied: null, notice: null, basisMismatch: false };

export function budgetStatusView(args: {
  /** 응답의 `budget` 블록. 없으면(`null`·`undefined`) **서버가 말하지 않은 것**이다. */
  budget: MapBudget | null | undefined;
  /** 화면이 `budget=mine` 을 실제로 보냈는가(`mapFilters.budgetRequested`). */
  requested: boolean;
  /** 화면이 배지·필터에 쓰는 기준(`mapFilters.effectiveBudget().basis`). */
  screenBasis: BudgetBasis | null;
}): BudgetStatusView {
  const { budget, requested, screenBasis } = args;

  // 서버가 블록을 안 실었다 → **어느 쪽도 주장하지 않는다.**
  // 화면 배지는 화면이 만들므로 침묵해도 거짓말이 되지 않고, 서버가 판정하지 못한
  // 사실은 아래 `checkVerdicts` 가 `serverUnknown` 으로 따로 센다.
  if (!budget) return SILENT;

  if (!requested) {
    // 켜지도 않았는데 서버가 판정했다 = 계약 위반. 조용히 넘기면 사용자는 조건을 끈 줄 안다.
    return budget.applied
      ? {
          applied: true,
          notice:
            "예산 조건을 껐는데 서버가 예산 기준으로 판정했습니다 — 표시가 좁혀져 있을 수 있습니다.",
          basisMismatch: false,
        }
      : { applied: false, notice: null, basisMismatch: false };
  }

  if (!budget.applied) {
    // 켰는데 아무 일도 안 일어난 상태. **사유를 말하지 않으면 고장과 구분되지 않는다.**
    const why = plainReason(budget.reason);
    const head = why
      ? `예산 초과 표시가 적용되지 않았습니다. ${tidy(why)}`
      : "예산 초과 표시가 적용되지 않았습니다 — 서버가 사유를 알려주지 않았습니다.";
    // ⚠️ 예전에는 여기서 *"화면이 판정한 값입니다"* 라고 했다. 이제 판정은 서버가 하므로
    //    서버가 못 세우면 **배지가 아예 뜨지 않는다.** 그 사실을 그대로 적는다 —
    //    안 뜨는 이유를 말하지 않으면 사용자는 "예산 안이라서 안 뜨는구나"로 읽는다.
    const tail = screenBasis
      ? ` 그동안 ${basisLabel(screenBasis)} 는 '내 조건' 칩에만 적히고, 목록·지도에는 예산 초과 표시가 뜨지 않습니다.`
      : " 그동안 목록·지도에는 예산 초과 표시가 뜨지 않습니다.";
    return { applied: false, notice: `${head}${tail}`, basisMismatch: false };
  }

  // 적용은 했는데 무엇으로 했는지 안 밝혔다 — 기준을 확인할 방법이 없다는 사실을 말한다.
  if (budget.basis === null) {
    const tail = screenBasis
      ? ` 화면은 '내 조건' 칩에 ${basisLabel(screenBasis)} 라고 적고 있습니다 — 같은 기준인지 확인할 수 없습니다.`
      : "";
    return {
      applied: true,
      notice: `서버가 예산 기준을 적용했지만 무엇을 기준으로 했는지 알려주지 않았습니다.${tail}`,
      basisMismatch: false,
    };
  }

  // 화면이 아직 기준을 못 정했으면(자산·희망가 미상) 비교할 것이 없다.
  if (screenBasis === null) return { applied: true, notice: null, basisMismatch: false };

  if (budget.basis === screenBasis) return { applied: true, notice: null, basisMismatch: false };

  // 기준이 다르다 = **금액이 다르다**. 사용자가 정한 희망가가 서버에 닿지 않은 상황이
  // 가장 흔하므로 그 경우만 사유를 짚어 준다(나머지는 사실만 말한다).
  //
  // 🔔 **이게 진짜 신호다.** 예전 카나리아(`checkVerdicts`)가 잡으려던 사실 —
  //    "저장한 희망 매매가가 서버에 반영되지 않았다" — 을 여기서 **사유 문장까지 붙여**
  //    잡는다. 카나리아는 같은 사실을 건수로만 말했고, 그러면서 면적 구간 차이라는
  //    **사용자가 손댈 수 없는 이유**로도 울었다(CR38-1). 그래서 이쪽만 남긴다.
  const hint =
    screenBasis === "target_price" && budget.basis === "max_purchase"
      ? " 저장한 희망 매매가가 서버에 반영되지 않았을 수 있습니다 — 내 조건에서 다시 저장해 보세요."
      : " 같은 단지가 두 화면에서 다르게 보일 수 있습니다.";
  return {
    applied: true,
    notice:
      `지도는 ${basisLabel(budget.basis)} 기준으로 판정했고, ` +
      `'내 조건' 칩에는 ${basisLabel(screenBasis)} 라고 적혀 있습니다.${hint}`,
    basisMismatch: true,
  };
}
