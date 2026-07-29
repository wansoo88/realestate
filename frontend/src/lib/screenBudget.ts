/**
 * 지도 항목에 **예산 판정을 실어 주는 유일한 자리**.
 *
 * 무엇이 바뀌었나 (CR38-1)
 * ------------------------
 * 예전에 이 파일은 화면이 **한 숫자**(선택 단지의 한도, 없으면 84㎡ 기본값)로 모든
 * 항목을 다시 판정했다. 그게 결함이었다 — 실구매 한도는 취득세 구간(85㎡) 때문에
 * **면적별로 다른 숫자**라서, 면적이 섞인 지도(수도권의 정상적인 모습)에서는
 * 120㎡ 단지의 배지가 84㎡ 한도로 섰다. 리뷰 재현: 세 상태(단지 미선택 · 85㎡ 이하
 * 선택 · 85㎡ 초과 선택) 전부에서 서버와 2건씩 갈렸다.
 *
 * 이제 **판정은 서버가 한다.** 서버는 항목마다 그 항목 거래의 면적으로 상한을 세우고,
 * 면적을 모르면 84 를 가정하지 않고 `null` 로 둔다. 화면은 그 값을 **옮기기만** 한다.
 *
 * 그러면 이 파일은 왜 아직 있나 — **관문의 목적이 바뀌었을 뿐 위험은 그대로다.**
 *
 * `over_budget` 은 3값이다(`true` 초과 · `false` 예산 안 · **`null` 판정 못 함**).
 * 그리고 **`null` 과 `false` 는 화면에서 픽셀 단위로 동일하다** — 마커도 카드도 배지를
 * `=== true` 일 때만 달기 때문이다. 즉 어디선가 `?? false` 로 접어도 화면 테스트로는
 * 영영 못 잡는다. 그래서 접힘이 일어날 수 있는 자리를 **한 곳으로 좁혀** 둔다.
 *
 * 관문이 지키는 명제 두 가지:
 *   ㉠ **화면은 예산 판정을 만들지 않는다** — 서버 값을 옮기거나, 표시가 꺼졌으면 비운다.
 *   ㉡ **`null`(모름)은 절대 `false`(예산 안)가 되지 않는다.**
 *
 * 셋으로 쌓아 둔 방어는 그대로다(하나만 뚫어서는 통과하지 못한다):
 *  ① **브랜드 타입** — `ScreenComplexItem` 은 `unique symbol` 키를 갖는다. 그 심볼은
 *     이 모듈 밖으로 나가지 않으므로 **객체 리터럴로 만들 수 없다**. `MapView` 가 이
 *     타입만 받으므로, 손으로 `{ ...item, over_budget: … }` 를 만들어 넘기면 tsc 가 죽는다.
 *  ② **생산 지점 하나** — 규칙이 이 파일 한 줄(`relayServerVerdict`)에만 있다.
 *  ③ **전수 검사** — `src/test/apiContract.test.ts` 가 src 전체에서 `over_budget:` 를
 *     쓰는 자리를 세어 여기 한 곳뿐인지, 값이 `relayServerVerdict(` 인지 확인한다.
 *     그리고 이 파일이 **금액으로 판정을 만들지 않는지**(`budgetVerdict(` 부재)까지 본다.
 */
import type { ComplexItem } from "../api/client";
import type { BudgetVerdict } from "./listFilter";

/**
 * 브랜드 키. **export 하지 않는다** — 다른 모듈은 이 심볼을 적을 수 없으므로
 * `ScreenComplexItem` 을 객체 리터럴로 위조할 수 없다(타입만 빌려 쓸 수 있다).
 * `declare` 라 런타임 값은 생기지 않는다(번들에 아무것도 안 남는다).
 */
declare const SCREEN_BUDGET: unique symbol;

/**
 * **표시 스위치를 통과한** 지도 항목.
 *
 * 계약 필드(`over_budget`)의 모양도 값도 서버 것 그대로지만, "예산 칩이 꺼져 있으면
 * 비운다"는 화면 규칙이 이미 적용됐다는 사실이 타입에 박혀 있다.
 * `applyScreenBudget` 만 이 타입을 만든다.
 */
export type ScreenComplexItem = ComplexItem & { readonly [SCREEN_BUDGET]: true };

/**
 * 서버 3값 → 화면 판정 3값. **`null`·`undefined` 는 `"unknown"`** 이다.
 *
 * 목록 카드·예산 토글이 쓰는 변환이다. 여기서 `"within"` 으로 접으면 "모른다"가
 * "예산 안"이 되어 `예산 내` 토글이 판정 못 한 단지를 예산 내로 세어 버린다.
 */
export function serverBudgetVerdict(over: boolean | null | undefined): BudgetVerdict {
  if (over === true) return "over";
  if (over === false) return "within";
  return "unknown";
}

/**
 * 서버 판정을 화면 항목으로 **옮긴다**(만들지 않는다).
 *
 * `display` 가 꺼져 있으면(사용자가 '내 조건'의 예산 칩을 껐으면) 전부 `null` 이다 —
 * `false` 가 아니다. 그래야 "예산 안이라고 판정했다"와 구분된다. 서버 응답을 기다리지
 * 않고 화면에서 비우는 이유: 칩은 즉시 반응해야 하는 스위치인데, 재조회가 돌아오기
 * 전까지 옛 배지가 남아 있으면 "눌러도 아무 일 없는 스위치"로 보인다.
 */
function relayServerVerdict(item: ComplexItem, display: boolean): boolean | null {
  // ⚠️ `?? false` 금지. 구버전 응답이 필드를 빼먹어도 "예산 안"이라고 말하지 않는다.
  return display ? (item.over_budget ?? null) : null;
}

/**
 * 서버 항목 → 지도·목록에 그릴 항목.
 *
 * @param display 초과 표시가 켜져 있는가(`mapFilters.displayBudget` 과 같은 스위치).
 */
export function applyScreenBudget(
  items: readonly ComplexItem[],
  display: boolean,
): ScreenComplexItem[] {
  return items.map(
    (item) =>
      ({
        ...item,
        over_budget: relayServerVerdict(item, display),
        // 브랜드는 **타입에만** 있다. 런타임 키를 만들지 않으므로 JSON·DOM 어디에도 안 샌다.
      }) as ScreenComplexItem,
  );
}
