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

/* ─────────────────────────────────────────────────────────────────────────
 * 서버 "사유" → 사람 말 (CR33-3)
 *
 * 시점 보정을 **왜 못 했는지**(`price_band.time_adjustment.reason`) 같은 값은
 * 지금은 완결된 한국어 문장으로 오지만, 서버가 코드(`no_index`)로 바꿔 보낼 수 있다.
 * 그때 화면이 그대로 뱉으면 사용자는 `no_index` 를 읽게 된다.
 *
 * 그래서 사유 해석은 **이 한 곳에만** 둔다(화면마다 매핑을 흩뿌리면 반드시 갈라진다).
 * 원칙은 plainText 와 같다 — **모르면 지어내지 않고 침묵한다.**
 * ───────────────────────────────────────────────────────────────────────── */

const HANGUL_RE = /[가-힣]/;

/**
 * 알려진 사유 코드 → 사용자 문장.
 * 키는 서버 상수(`timeadjust.py::REASON_*`)에 대응하는 snake_case 코드다.
 * 여기 없는 코드는 **번역하지 않고 감춘다**(틀린 번역보다 침묵이 낫다).
 */
const REASON_TEXT: Record<string, string> = {
  no_index: "이 지역의 시장지수가 없어 시점 보정을 하지 못했습니다",
  no_reference: "기준으로 삼을 만큼 자료가 찬 달이 없어 시점 보정을 하지 못했습니다",
  no_reference_month: "기준으로 삼을 만큼 자료가 찬 달이 없어 시점 보정을 하지 못했습니다",
  low_coverage: "거래 시점을 덮는 지수가 모자라 시점 보정을 하지 못했습니다",
  too_few: "보정할 수 있는 거래가 최소 표본에 미달해 시점 보정을 하지 못했습니다",
  too_few_samples: "보정할 수 있는 거래가 최소 표본에 미달해 시점 보정을 하지 못했습니다",
  out_of_range: "지수 보정 배율이 비정상 범위라 시점 보정을 하지 않았습니다",
  ratio_out_of_range: "지수 보정 배율이 비정상 범위라 시점 보정을 하지 않았습니다",
};

/**
 * 사유 값을 화면에 낼 문장으로 바꾼다. 낼 수 없으면 **null**(빈 문자열이 아니다).
 *
 * 판정 순서
 *  1. 아는 코드 → 사람 문장으로 번역
 *  2. 사람이 읽는 문장(한글이 있거나 공백으로 띄운 말) → 내부 식별자만 걷어내고 그대로
 *  3. 그 외(공백 없는 ASCII 토큰 = 코드 모양) → **null**. 모르는 코드는 노출하지 않는다.
 */
export function plainReason(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const key = raw.trim();
  if (key === "") return null;

  const mapped = REASON_TEXT[key] ?? REASON_TEXT[key.toLowerCase()];
  if (mapped) return mapped;

  // 한글도 없고 띄어쓰기도 없으면 사람에게 보여줄 문장이 아니다(예: "IDX_ERR_42").
  if (!HANGUL_RE.test(key) && !/\s/.test(key)) return null;

  const text = plainText(key);
  return text === "" ? null : text;
}
