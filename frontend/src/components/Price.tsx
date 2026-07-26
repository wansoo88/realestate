/**
 * 금액 표기의 **단일 창구** (components.md §3.1).
 *
 * 화면마다 금액을 따로 그리면 표기가 갈라지고, 이 제품에서 표기가 갈라지는 건
 * "추정치를 확정치로 보여주는 것"과 같다. 그래서 금액은 전부 이 컴포넌트를 지난다.
 *
 * 농도 규칙(규칙 1): 확정 = 선명 / 추정 = 흐림 + `~` + 배지. **색만으로 구분하지 않는다** —
 * 색각 이상·야외 화면에서 색은 가장 먼저 사라지는 정보다.
 */
import { confidenceLabel, formatAsOf, formatKrw, formatKrwShort, type Confidence } from "../lib/format";
import "./Price.css";

interface ConfidenceBadgeProps {
  confidence: Confidence;
  sampleCount?: number | null;
}

export function ConfidenceBadge({ confidence, sampleCount }: ConfidenceBadgeProps) {
  const text =
    confidence === "confirmed"
      ? sampleCount && sampleCount > 0
        ? `실거래 ${sampleCount}건`
        : confidenceLabel("confirmed")
      : confidence === "estimated"
        ? "추정"
        : "신뢰도 미상";

  return (
    <span className={`badge price__badge price__badge--${confidence}`}>{text}</span>
  );
}

/**
 * 신뢰도 5단계 점 (components.md §3.3).
 *
 * 점 문자는 장식이라 `aria-hidden`, 진실은 `aria-label` 문장이 말한다.
 * 0.5 미만이면 점만 보고는 낮은 줄 모르므로 **"낮음" 텍스트를 함께** 붙인다.
 */
export function ConfidenceDots({ value }: { value: number }) {
  const safe = Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;
  const filled = Math.round(safe * 5);
  return (
    <span className="dots" aria-label={`신뢰도 5단계 중 ${filled}단계`}>
      <span className="dots__marks" aria-hidden="true">
        {"●".repeat(filled)}
        {"○".repeat(5 - filled)}
      </span>
      {safe < 0.5 && <span className="badge price__badge--estimated dots__low">신뢰도 낮음</span>}
    </span>
  );
}

interface PriceProps {
  krw: number | null;
  confidence: Confidence;
  /** 이 금액이 **무엇인지**. 라벨이 없으면 모든 숫자가 호가로 읽힌다. */
  label?: string | null;
  asOf?: string | null;
  size?: "lg" | "md" | "sm";
  short?: boolean;
  sampleCount?: number | null;
  /** 배지를 숨긴다(이미 상위에서 근거를 말하고 있는 자리). */
  hideBadge?: boolean;
}

export function Price({
  krw,
  confidence,
  label,
  asOf,
  size = "md",
  short = false,
  sampleCount,
  hideBadge = false,
}: PriceProps) {
  // 값이 없을 때만 "데이터 없음". 값이 있는데 이 문구를 쓰면 모순이다(F-05).
  if (krw === null || krw === undefined) {
    return (
      <span className={`price price--${size} price--none estimated`}>데이터 없음</span>
    );
  }

  const estimated = confidence === "estimated";
  const text = short ? formatKrwShort(krw) : formatKrw(krw);

  return (
    <span className={`price price--${size}${estimated ? " price--est" : ""}`}>
      {label && <span className="price__label">{label}</span>}
      <span className="price__value num">
        {/* `~` 는 시각 기호다. 스크린리더에는 배지 텍스트("추정")가 진실을 말한다. */}
        {estimated && (
          <span className="price__tilde" aria-hidden="true">
            ~
          </span>
        )}
        {text}
      </span>
      {!hideBadge && <ConfidenceBadge confidence={confidence} sampleCount={sampleCount} />}
      {asOf !== undefined && <span className="price__asof">{formatAsOf(asOf)}</span>}
    </span>
  );
}
