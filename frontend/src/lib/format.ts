/**
 * 금액·면적 표기.
 *
 * 한국 부동산은 "14억 8,000" 처럼 읽는다. 원 단위 숫자를 그대로 보여주면
 * 자릿수를 세게 되고, 자릿수를 세면 비교를 못 한다.
 */

/** 원 → "14억 8,000만" 형태. 억 단위가 없으면 "8,500만". */
export function formatKrw(won: number | null | undefined): string {
  if (won === null || won === undefined || Number.isNaN(won)) return "—";
  if (won === 0) return "0원";

  const sign = won < 0 ? "-" : "";
  const abs = Math.abs(Math.round(won));

  const eok = Math.floor(abs / 100_000_000);
  const man = Math.floor((abs % 100_000_000) / 10_000);

  if (eok > 0) {
    return man > 0
      ? `${sign}${eok}억 ${man.toLocaleString("ko-KR")}만`
      : `${sign}${eok}억`;
  }
  if (man > 0) return `${sign}${man.toLocaleString("ko-KR")}만`;
  return `${sign}${abs.toLocaleString("ko-KR")}원`;
}

/** 짧은 표기 — 지도 마커처럼 자리가 없을 때. "14.8억" */
export function formatKrwShort(won: number | null | undefined): string {
  if (won === null || won === undefined || Number.isNaN(won)) return "—";
  const abs = Math.abs(won);
  if (abs >= 100_000_000) {
    const eok = won / 100_000_000;
    // 10억 이상은 소수 첫째자리, 미만은 둘째자리까지
    return `${eok.toFixed(abs >= 1_000_000_000 ? 1 : 2)}억`;
  }
  if (abs >= 10_000) return `${Math.round(won / 10_000).toLocaleString("ko-KR")}만`;
  return `${Math.round(won).toLocaleString("ko-KR")}원`;
}

/**
 * 지도 마커 전용 **초압축** — 항상 억 단위 소수 1자리. "8.4억"
 *
 * 왜 formatKrwShort 로 부족한가: 그쪽은 10억 미만에서 소수 2자리("8.50억")를 쓴다.
 * 칩·리스트에서는 그 정밀도가 비교에 도움이 되지만, 마커에서는 **글자 한 개가 지도를 덮는다**.
 * 한 화면에 수십 개가 동시에 뜨는 자리이므로 자릿수를 고정해 폭을 예측 가능하게 만든다.
 * 100억 이상은 소수점을 버린다("120억") — 그 구간에서 1,000만원 자리는 판단에 영향이 없다.
 */
export function formatKrwCompact(won: number | null | undefined): string {
  if (won === null || won === undefined || Number.isNaN(won)) return "—";
  const abs = Math.abs(won);
  if (abs >= 100_000_000) {
    const eok = won / 100_000_000;
    return `${eok.toFixed(abs >= 10_000_000_000 ? 0 : 1)}억`;
  }
  if (abs >= 10_000) return `${Math.round(won / 10_000).toLocaleString("ko-KR")}만`;
  return `${Math.round(won).toLocaleString("ko-KR")}원`;
}

/**
 * 월 상환액처럼 **만원 자리 소수까지 봐야 하는** 금액. "300.7만원"
 *
 * 왜 `formatKrw` 로 부족한가: 그쪽은 만원 미만을 버려 3,007,000 원이 "300만"이 된다.
 * 매달 나가는 돈에서 7,000원 차이는 30년이면 250만원이다 — 버리면 안 되는 자리다.
 * 1억 이상은 억 표기가 읽기 쉬우므로 `formatKrw` 에 넘긴다(현실적인 월 상환액이 아니다).
 */
export function formatKrwManwon(won: number | null | undefined): string {
  if (won === null || won === undefined || Number.isNaN(won)) return "—";
  if (Math.abs(won) >= 100_000_000) return formatKrw(won);
  if (won === 0) return "0원";
  const man = Math.round(won / 1_000) / 10; // 천원 자리에서 반올림 → 만원 소수 1자리
  if (man === 0) return `${Math.round(won).toLocaleString("ko-KR")}원`;
  return `${man.toLocaleString("ko-KR")}만원`;
}

/** ㎡ → "84.97㎡ (25.7평)" */
export function formatArea(m2: number | null | undefined): string {
  if (m2 === null || m2 === undefined || Number.isNaN(m2)) return "—";
  const pyeong = m2 / 3.305785;
  return `${m2.toFixed(2)}㎡ (${pyeong.toFixed(1)}평)`;
}

/** 퍼센트. 부호를 항상 붙여 상승/하락을 색 없이도 알 수 있게 한다(접근성). */
export function formatPct(pct: number | null | undefined, digits = 1): string {
  if (pct === null || pct === undefined || Number.isNaN(pct)) return "—";
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(digits)}%`;
}

/** "2026-06-30" → "2026년 6월 30일 기준" */
export function formatAsOf(iso: string | null | undefined): string {
  if (!iso) return "기준일 미상";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return `${iso} 기준`;
  return `${m[1]}년 ${Number(m[2])}월 ${Number(m[3])}일 기준`;
}

export type Confidence = "confirmed" | "estimated" | "unknown";

/** 신뢰도 라벨. 추정치를 확정치처럼 보이게 하지 않는다. */
export function confidenceLabel(c: Confidence): string {
  switch (c) {
    case "confirmed":
      return "실거래 기준";
    case "estimated":
      return "추정";
    default:
      return "데이터 없음";
  }
}
