/**
 * 에이전트 id → 사람이 읽는 한국어 라벨.
 *
 * `valuation-trader` 를 그대로 보여주면 사용자는 그게 누구 의견인지 모른다.
 * 원문 id 는 `title` 속성으로 남겨 추적 가능성을 잃지 않는다(components.md §5.7).
 */

const LABELS: Record<string, string> = {
  "listing-researcher": "매물 리서처",
  "location-analyst": "지역 전문가",
  "finance-tax-advisor": "세금·대출 전문가",
  "valuation-trader": "매매 전문가",
  "policy-researcher": "정책 연구가",
  "market-timing-analyst": "타이밍 분석가",
  "risk-auditor": "리스크 검증가",
  "portfolio-advisor": "종합 자문가",
};

/** 모르는 id 는 **지어내지 않고** 원문을 그대로 돌려준다. */
export function agentLabel(agentId: string): string {
  return LABELS[agentId] ?? agentId;
}

/** 심각도 → 텍스트 병기(색만으로 전달 금지, A3). */
export function severityLabel(severity: string): string {
  switch (severity) {
    case "high":
      return "심각도 높음";
    case "medium":
      return "심각도 중";
    case "low":
      return "심각도 낮음";
    default:
      return "심각도 미상";
  }
}
