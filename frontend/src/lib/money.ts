/**
 * 금액 입력 변환 — **순수 함수**. 뷰·DOM 에 의존하지 않으므로 RN 에서 그대로 쓴다.
 *
 * 왜 별도 모듈인가
 * ----------------
 * 화면은 **만원** 단위로 받고 서버는 **원 단위 정수**로 받는다(api-spec §0).
 * 이 변환이 컴포넌트 안에 흩어지면 어딘가에서 반드시 10,000 을 한 번 더 곱하거나 빠뜨린다.
 * 세금·대출 한도가 걸린 값이라 그 실수는 조용히 틀린 답을 만든다.
 *
 * ⚠️ 이 모듈은 값을 **로그·저장소에 남기지 않는다**(개인 금융정보, security.md §3.3).
 */

/** 만원 → 원 배수. */
export const MAN = 10_000;

/** 입력 상한(만원 기준 12자리 = 1경). 그 이상은 오타지 금액이 아니다. */
export const MAX_INPUT_DIGITS = 12;

/**
 * 사용자가 친 문자열에서 **숫자만** 남긴다.
 *
 * 콤마·공백·"억"·붙여넣기한 원화기호를 모두 흘려보내고, 선행 0 은 지운다.
 * (`007` 을 7 로 읽지 않으면 자릿수 검사가 엉킨다)
 */
export function normalizeDigits(raw: string, maxDigits = MAX_INPUT_DIGITS): string {
  const digits = (raw ?? "").replace(/\D/g, "").slice(0, maxDigits);
  const trimmed = digits.replace(/^0+(?=\d)/, "");
  return trimmed;
}

/** "1234567" → "1,234,567". 빈 문자열은 그대로. */
export function groupDigits(digits: string): string {
  if (!digits) return "";
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** 만원 입력(숫자문자열) → 원 단위 정수. 빈 입력은 null(= 미입력, 0 이 아니다). */
export function manwonDigitsToKrw(digits: string): number | null {
  if (!digits) return null;
  return Number(digits) * MAN;
}

/**
 * 원 → 만원 숫자문자열.
 *
 * 만원 미만 잔돈은 **버림**이 아니라 반올림한다 — 서버가 준 값을 다시 보여줄 때
 * 1원 차이로 표시가 바뀌는 게 더 혼란스럽다. (입력값은 항상 만원 배수라 실제로는 무손실)
 */
export function krwToManwonDigits(krw: number | null | undefined): string {
  if (krw === null || krw === undefined || Number.isNaN(krw)) return "";
  return String(Math.round(krw / MAN));
}

/**
 * 콤마를 다시 넣은 뒤 캐럿을 어디에 둘지 계산한다.
 *
 * 왜 필요한가: 포맷팅 후 캐럿을 그냥 두면 콤마가 삽입될 때마다 커서가 한 칸씩 튄다.
 * "앞쪽에 남은 **숫자 개수**"를 보존하면 사람이 보기에 커서가 제자리에 있다.
 */
export function caretForDigitCount(formatted: string, digitsBeforeCaret: number): number {
  if (digitsBeforeCaret <= 0) return 0;
  let seen = 0;
  for (let i = 0; i < formatted.length; i += 1) {
    if (formatted[i] !== ",") seen += 1;
    if (seen === digitsBeforeCaret) return i + 1;
  }
  return formatted.length;
}

/** 문자열의 앞 `caret` 글자 중 숫자 개수. 포맷 전후 캐럿 매핑에 쓴다. */
export function countDigitsBefore(value: string, caret: number): number {
  let n = 0;
  for (let i = 0; i < Math.min(caret, value.length); i += 1) {
    if (/\d/.test(value[i])) n += 1;
  }
  return n;
}
