/**
 * 실구매 가능 금액 (F2) — 이 앱에서 가장 큰 숫자가 나오는 자리.
 *
 * 규칙 두 가지를 반드시 지킨다.
 *  ① **무엇이 한도를 묶었는지**(binding_constraint)를 문장으로 말한다.
 *     "8.5억"만 보여주면 사용자는 왜 그 숫자인지 모르고, 모르면 못 믿는다.
 *  ② **가정과 출처**(assumptions·evidence)를 함께 노출한다. 출처 없는 세율·한도는
 *     이 제품에서 금지다(G2). 출처가 없는 evidence 항목은 아예 렌더링하지 않는다.
 */
import type { AffordabilityResponse } from "../api/client";
import { formatAsOf, formatKrw } from "../lib/format";
import { usableEvidence } from "../lib/recommendation";
import { Price } from "./Price";
import { Section } from "./Section";
import "./AffordabilityPanel.css";

interface Props {
  data: AffordabilityResponse | null;
  loading: boolean;
  error: string | null;
  /** 자산 미입력(422) — 계산할 수 없으니 조건 화면으로 보낸다. */
  needsProfile?: boolean;
  onEditConditions?: () => void;
}

/** 한도를 결정한 제약을 사람 말로. 모르는 코드는 원문을 그대로 둔다(지어내지 않는다). */
function constraintSentence(code: string): string {
  switch (code) {
    case "LTV":
      return "한도를 결정한 건 담보인정비율(LTV)입니다.";
    case "DSR":
      return "한도를 결정한 건 총부채원리금상환비율(DSR)입니다.";
    case "DTI":
      return "한도를 결정한 건 총부채상환비율(DTI)입니다.";
    case "CAP":
      return "한도를 결정한 건 주택담보대출 절대한도입니다.";
    case "CASH":
      return "한도를 결정한 건 보유 현금입니다.";
    default:
      return `한도를 결정한 건 ${code} 입니다.`;
  }
}

export function AffordabilityPanel({
  data,
  loading,
  error,
  needsProfile,
  onEditConditions,
}: Props) {
  if (needsProfile) {
    return (
      <div className="afford afford--empty">
        <p className="afford__empty-text">
          자산 정보를 입력하면 실구매 가능 금액을 계산합니다.
        </p>
        {onEditConditions && (
          <button type="button" className="afford__cta" onClick={onEditConditions}>
            내 조건 입력하기
          </button>
        )}
      </div>
    );
  }

  if (loading && !data) return <p className="afford__status">한도를 계산하는 중…</p>;

  if (error) {
    return (
      <p className="afford__error" role="alert">
        {error}
      </p>
    );
  }

  if (!data) return null;

  const evidence = usableEvidence(data.evidence);
  const cost = data.acquisition_cost_krw;

  return (
    <div className="afford">
      <h3 className="afford__caption">실구매 가능 금액</h3>
      {/* 법정 계산 결과라 추정이 아니다 → confirmed 농도(선명하게). */}
      <Price krw={data.max_purchase_krw} confidence="confirmed" size="lg" hideBadge />

      <p className="afford__binding">{constraintSentence(data.breakdown.binding_constraint)}</p>

      <dl className="afford__breakdown">
        <div className="afford__item">
          <dt>내 현금</dt>
          <dd className="num">{formatKrw(data.breakdown.own_cash_krw)}</dd>
        </div>
        <div className="afford__item">
          <dt>대출 가능</dt>
          <dd className="num">{formatKrw(data.breakdown.max_loan_krw)}</dd>
        </div>
        <div className="afford__item">
          <dt>취득 부대비용</dt>
          <dd className="num">{formatKrw(cost.total)}</dd>
        </div>
      </dl>

      <Section title="한도 계산 내역" count={undefined}>
        <ul className="afford__list">
          {data.breakdown.ltv_limit_krw != null && (
            <li>
              LTV 한도 <span className="num">{formatKrw(data.breakdown.ltv_limit_krw)}</span>
            </li>
          )}
          {data.breakdown.dsr_limit_krw != null && (
            <li>
              DSR 한도 <span className="num">{formatKrw(data.breakdown.dsr_limit_krw)}</span>
            </li>
          )}
          {data.breakdown.dti_limit_krw != null && (
            <li>
              DTI 한도 <span className="num">{formatKrw(data.breakdown.dti_limit_krw)}</span>
            </li>
          )}
          {data.breakdown.absolute_cap_krw != null && (
            <li>
              절대한도 <span className="num">{formatKrw(data.breakdown.absolute_cap_krw)}</span>
            </li>
          )}
          <li>
            취득세 <span className="num">{formatKrw(cost.tax)}</span> · 중개보수{" "}
            <span className="num">{formatKrw(cost.brokerage)}</span> · 등기{" "}
            <span className="num">{formatKrw(cost.registration)}</span>
          </li>
        </ul>
      </Section>

      {/* 근거: 출처가 있는 항목만. 출처 없는 세율은 보여주지 않는다(G2). */}
      <Section title="이 계산의 근거" count={evidence.length} defaultOpen>
        <ul className="afford__evidence">
          {evidence.map((e, i) => (
            <li key={`${e.claim}-${i}`} className="afford__evidence-item">
              <span className="afford__claim">{e.claim}</span>
              <span className="afford__source">
                {e.source}
                {e.as_of ? ` · ${formatAsOf(e.as_of)}` : ""}
              </span>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="계산에 쓴 가정" count={data.assumptions.length}>
        <ul className="afford__list">
          {data.assumptions.map((a, i) => (
            <li key={`${a}-${i}`}>{a}</li>
          ))}
        </ul>
      </Section>

      {data.warnings.length > 0 && (
        <Section title="주의" count={data.warnings.length} tone="warn" defaultOpen>
          <ul className="afford__list">
            {data.warnings.map((w, i) => (
              <li key={`${w}-${i}`}>{w}</li>
            ))}
          </ul>
        </Section>
      )}

      <p className="afford__disclaimer">{data.disclaimer}</p>
    </div>
  );
}
