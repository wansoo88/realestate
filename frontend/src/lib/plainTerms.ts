/**
 * 화면에 나가는 서버 문장에서 **내부 식별자를 걷어낸다.**
 *
 * 왜 필요한가
 * -----------
 * 서버 문구에 개발용 이름이 그대로 섞여 나왔다:
 *   "12개월 거래회전율 기반 환금성(liquidity.turnover_12m_pct)"
 *   "동별 가격 편차(dong_valuation)는 …"
 *   "…분석(risk-auditor)은 2차 기능이라…"
 * 사용자는 `liquidity.turnover_12m_pct` 가 무엇인지 알 필요도, 알 수도 없다.
 *
 * 무엇을 하고 무엇을 하지 않는가
 * ------------------------------
 *  · **하는 것**: 괄호 안이 *ASCII 식별자 하나뿐*일 때 그 괄호를 통째로 지운다.
 *    괄호 앞에 이미 한국어 설명이 있으므로(“환금성”, “동별 가격 편차”) 지워도 뜻이 남는다.
 *  · **하지 않는 것**: 문장을 파싱해 의미를 재조립하지 않는다. 서버가 문구를 바꾸면
 *    치환이 그냥 안 걸릴 뿐 **문장은 원문 그대로** 남는다 — 조용히 틀린 말을 만들지 않는다.
 *
 * 그래서 판별 기준을 좁게 잡았다: 공백·한글이 없고 `_ . -` 중 하나를 포함하는 ASCII 토큰만.
 * `(LTV)` `(DSR)` `(F4)` `(84A)` 같은 **사용자에게 의미 있는 약어는 건드리지 않는다.**
 */

/** 괄호 안 내용이 내부 식별자인가. */
export function isInternalIdentifier(token: string): boolean {
  // ASCII 식별자 모양이어야 하고(공백·한글 불가)
  if (!/^[A-Za-z][A-Za-z0-9_.\-]*$/.test(token)) return false;
  // 코드에서만 쓰는 구분자(_ . -)를 포함해야 한다 → LTV·DSR·API 같은 약어는 남는다
  return /[_.\-]/.test(token);
}

/**
 * 서버 문장 → 사용자에게 보여줄 문장.
 * 값이 없으면 그대로 돌려준다(빈 문자열을 만들어 내지 않는다).
 */
export function plainText(text: string): string {
  if (!text) return text;
  return (
    text
      // "(liquidity.turnover_12m_pct)" 처럼 식별자 하나만 든 괄호를 제거
      .replace(/\s*\(([^()]+)\)/g, (whole, inner: string) =>
        isInternalIdentifier(inner.trim()) ? "" : whole,
      )
      // 괄호가 빠지며 생긴 이중 공백 정리(문장 부호 앞 공백 포함)
      .replace(/[ \t]{2,}/g, " ")
      .replace(/\s+([.,·])/g, "$1")
      .trim()
  );
}

/** 문자열 배열용 편의 함수. */
export function plainTexts(texts: readonly string[]): string[] {
  return texts.map(plainText);
}
