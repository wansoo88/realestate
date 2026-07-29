/**
 * 최대 실구매 가능 금액 + 자금계획 (F2) — 이 앱에서 가장 큰 숫자가 나오는 자리.
 *
 * 규칙 두 가지를 반드시 지킨다.
 *  ① **무엇이 한도를 묶었는지**(binding_constraint)를 문장으로 말한다.
 *     "8.5억"만 보여주면 사용자는 왜 그 숫자인지 모르고, 모르면 못 믿는다.
 *  ② **가정과 출처**(assumptions·evidence)를 함께 노출한다. 출처 없는 세율·한도는
 *     이 제품에서 금지다(G2). 출처가 없는 evidence 항목은 아예 렌더링하지 않는다.
 *
 * 자금계획(plan)에서 추가로 지키는 것
 *  ③ **한도를 넘어도 숫자를 보여준다.** "불가능합니다"만 띄우면 얼마를 더 모아야 하는지
 *     알 수 없다 — 그게 사용자가 물어본 것이다. 초과분·무엇이 막는지를 함께 적는다.
 *  ④ **가정을 숫자 옆에 붙인다.** 금리 4%/30년이 5%/20년이 되면 월 상환액이 40% 넘게
 *     달라진다. 가정 없는 월 상환액은 근거 없는 숫자다(G2).
 */
import type { AffordabilityResponse } from "../api/client";
import {
  planAreaNote,
  planOverLimit,
  planOverLimitKrw,
  targetPriceView,
  usablePlan,
  type PlanArea,
} from "../lib/affordability";
import { formatAsOf, formatKrw, formatKrwManwon } from "../lib/format";
import { usableEvidence } from "../lib/recommendation";
import { Price } from "./Price";
import { Section } from "./Section";
import "./AffordabilityPanel.css";

/**
 * 이 자금계획이 **어느 가격을 근거로** 세워졌는가.
 * 단지 기준일 때 그 값은 `recent_price_krw`(최근 실거래 기반 **추정**)이지 호가가 아니다 —
 * 그 사실이 화면에서 사라지면 추정치가 "이 값에 살 수 있다"로 둔갑한다.
 */
export type PlanBasis =
  | { kind: "manual" }
  | { kind: "complex"; name: string; estimated: boolean; asOf: string | null };

interface Props {
  data: AffordabilityResponse | null;
  loading: boolean;
  error: string | null;
  /** 자산 미입력(422) — 계산할 수 없으니 조건 화면으로 보낸다. */
  needsProfile?: boolean;
  onEditConditions?: () => void;
  /** 자금계획의 근거. null = 희망가도 없고 고른 단지도 없다. */
  planBasis?: PlanBasis | null;
  /**
   * 고른 단지에 시세 근거가 없을 때 그 단지 이름.
   * 값을 지어내 계획을 세우지 않되, **왜 이 단지 기준이 아닌지**는 반드시 말한다 —
   * 조용히 내 희망가 계획을 보여주면 사용자는 그걸 그 단지의 계획으로 읽는다.
   */
  noPriceComplexName?: string | null;
  /** 단지 기준 계획을 접고 내 희망가로 돌아간다. */
  onClearComplex?: () => void;
  /** 조건에 저장된 희망가(있으면 되돌아갈 곳을 문장으로 말할 수 있다). */
  targetPriceKrw?: number | null;
  /**
   * 단지 기준일 때 **어느 면적으로** 요청했는가 (CR35-4).
   * 기준가는 면적별 값이라, 이 말이 없으면 34평 계획이 25평 매물의 계획으로 읽힌다.
   */
  planArea?: PlanArea | null;
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

/** 짧은 제약 이름(괄호 안에 들어갈 말). */
function constraintShort(code: string | null | undefined): string | null {
  if (!code) return null;
  switch (code) {
    case "LTV":
      return "담보인정비율(LTV)";
    case "DSR":
      return "총부채원리금상환비율(DSR)";
    case "DTI":
      return "총부채상환비율(DTI)";
    case "CAP":
      return "주택담보대출 절대한도";
    case "CASH":
      return "보유 현금";
    default:
      return code;
  }
}

export function AffordabilityPanel({
  data,
  loading,
  error,
  needsProfile,
  onEditConditions,
  planBasis = null,
  noPriceComplexName = null,
  onClearComplex,
  targetPriceKrw = null,
  planArea = null,
}: Props) {
  if (needsProfile) {
    return (
      <div className="afford afford--empty">
        <p className="afford__empty-text">
          자산 정보를 입력하면 최대 실구매 가능 금액을 계산합니다.
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
  const plan = usablePlan(data.plan);
  const isComplex = planBasis?.kind === "complex";
  /** 서버가 말하는 기준가 근거. 구버전 응답이면 null 이고, 그때는 아무 말도 하지 않는다. */
  // 기준가 근거는 **무엇에 대한 값인지** 이름으로 말해야 한다 (CR36-5) —
  // "추천 카드와 같은 값"만으로는 어느 카드인지, 카드가 있기는 한지 알 수 없다.
  const target = targetPriceView(data.target_price, {
    complexName: isComplex ? planBasis?.name : null,
    areaM2: planArea?.m2 ?? null,
  });

  return (
    <div className="afford">
      <h3 className="afford__caption">최대 실구매 가능 금액</h3>
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

      {/* ── 자금계획 ─────────────────────────────────────────────────────── */}
      <section className="plan" aria-labelledby="plan-title">
        <h3 className="plan__title" id="plan-title">
          자금계획
        </h3>

        {noPriceComplexName && (
          <p className="plan__nodata" role="status">
            <strong>{noPriceComplexName}</strong>은(는) 최근 실거래 근거가 없어 이 단지 기준으로는
            계산할 수 없습니다. 아래는 <strong>내가 정한 희망가</strong> 기준입니다.
          </p>
        )}

        {/* ── 기준가를 못 세운 경우 ─────────────────────────────────────────
            서버가 표본 부족으로 금액을 만들지 못하면 **계획 자체가 없다**.
            0 으로 채우거나 다른 값으로 슬쩍 갈아끼우지 않고, 사유를 그대로 보인다. */}
        {target && !target.known && (
          <p className="plan__noref" role="status">
            <strong>{target.label}</strong>
            {target.reason ? ` — ${target.reason}` : ""}
            {planBasis?.kind === "complex" ? " 다른 면적이나 다른 단지를 골라 보세요." : ""}
          </p>
        )}

        {plan === null ? (
          // 사유를 이미 위에서 말했으면(기준가 없음) 여기서 또 말하지 않는다 —
          // "포함되지 않았습니다"는 사유를 모를 때 쓰는 문장이다.
          target && !target.known ? null : (
            <p className="plan__empty">
              {planBasis === null
                ? "희망 매매가를 정하거나 지도에서 단지를 고르면 필요한 대출과 월 원리금을 계산합니다."
                : "이 응답에는 자금계획이 포함되지 않았습니다 — 계산 결과를 지어내지 않습니다."}
              {planBasis === null && onEditConditions && (
                <>
                  {" "}
                  <button type="button" className="plan__link" onClick={onEditConditions}>
                    희망 매매가 정하기
                  </button>
                </>
              )}
            </p>
          )
        ) : (
          <>
            {/* 무엇을 기준으로 세운 계획인가 — 단지 기준이면 **추정치임을 함께** 말한다. */}
            <p className={`plan__basis${isComplex ? " plan__basis--est" : ""}`}>
              {isComplex ? (
                <>
                  <span className="plan__basis-name">{planBasis.name}</span>
                  <span className="plan__basis-what">
                    {planBasis.estimated ? " 최근 실거래 기준 추정가" : " 최근 실거래가"}
                  </span>
                  {planBasis.estimated && (
                    <span className="badge badge--estimated plan__badge">추정</span>
                  )}
                </>
              ) : (
                <span className="plan__basis-what">내가 정한 희망 매매가</span>
              )}
            </p>

            {isComplex && (
              <p className="plan__estnote">
                이 금액은 <strong>지금 살 수 있는 호가가 아니라</strong> 최근 실거래를 근거로 한
                추정치입니다. {formatAsOf(planBasis.asOf)}이며 신고 지연으로 최근 거래가 빠졌을 수
                있습니다.
              </p>
            )}

            <p className="plan__target num">{formatKrw(plan.target_price_krw)}</p>

            {/* ── 이 금액이 **어디서 온 값인가** (CR35-4) ─────────────────────
                서버가 `basis` 로 말해 준다. 화면이 이걸 안 적으면 추천 카드와 자금계획이
                다른 금액을 말할 때 사용자는 어느 쪽이 맞는지 판단할 근거가 없다. */}
            {target?.known && (
              <p className={`plan__ref${target.estimated ? " plan__ref--est" : ""}`}>
                <span className="plan__ref-label">{target.label}</span>
                {target.detail && <span className="plan__ref-detail">{target.detail}</span>}
                {target.reason && <span className="plan__ref-why">사유: {target.reason}</span>}
                {/* 면적을 말하지 않으면 34평 계획이 25평 매물의 계획으로 읽힌다 */}
                {planArea && <span className="plan__ref-area">{planAreaNote(planArea)}</span>}
              </p>
            )}

            <dl className="plan__rows">
              <div className="plan__row">
                <dt>총 필요자금</dt>
                <dd className="num">{formatKrw(plan.total_needed_krw)}</dd>
              </div>
            </dl>
            <p className="plan__formula">
              매매가 {formatKrw(plan.target_price_krw)} + 취득세{" "}
              {formatKrw(plan.cost_breakdown?.tax)} + 중개보수{" "}
              {formatKrw(plan.cost_breakdown?.brokerage)} + 기타{" "}
              {formatKrw(plan.cost_breakdown?.etc)}
            </p>

            <dl className="plan__rows">
              <div className="plan__row">
                <dt>내 현금</dt>
                <dd className="num">{formatKrw(plan.own_cash_krw)}</dd>
              </div>
              <div className="plan__row plan__row--strong">
                <dt>더 필요한 돈</dt>
                <dd className="num">{formatKrw(plan.shortfall_krw)}</dd>
              </div>
              <div className="plan__row">
                <dt>필요 대출</dt>
                <dd className="num">{formatKrw(plan.required_loan_krw)}</dd>
              </div>
            </dl>

            {/* 한도 초과여도 **숫자를 지우지 않는다**. 얼마가 모자란지가 곧 답이다. */}
            {planOverLimit(plan) ? (
              <p className="plan__over" role="status">
                <span className="badge plan__over-badge">한도 초과</span>
                내 대출 한도 <span className="num">{formatKrw(plan.loan_limit_krw)}</span>
                {constraintShort(plan.binding_constraint)
                  ? ` · ${constraintShort(plan.binding_constraint)}이(가) 막습니다`
                  : ""}{" "}
                — <span className="num">{formatKrw(planOverLimitKrw(plan))}</span> 부족합니다. 그만큼
                현금을 더 모으거나 더 싼 집을 봐야 합니다.
              </p>
            ) : (
              <p className="plan__ok">
                내 대출 한도 <span className="num">{formatKrw(plan.loan_limit_krw)}</span> 안입니다.
              </p>
            )}

            <div className="plan__monthly">
              <span className="plan__monthly-label">월 원리금</span>
              <strong className="plan__monthly-value num">
                {formatKrwManwon(plan.monthly_payment_krw)}
              </strong>
              {/* 가정은 **숫자 옆에** 붙인다 — 접어 두면 아무도 안 본다(G2) */}
              <span className="plan__terms">
                금리 {plan.terms?.annual_rate_pct ?? "?"}% · {plan.terms?.years ?? "?"}년 원리금
                균등 가정
              </span>
            </div>

            {typeof plan.total_interest_krw === "number" && (
              <p className="plan__interest">
                총 이자 <span className="num">{formatKrw(plan.total_interest_krw)}</span> (같은 가정
                기준)
              </p>
            )}

            <p className="plan__caveat">
              실제 금리·기간은 금융기관 심사에서 정해집니다. 위 월 상환액은 위 가정으로만 계산한
              값입니다.
            </p>

            {isComplex && onClearComplex && (
              <button type="button" className="plan__reset" onClick={onClearComplex}>
                {targetPriceKrw !== null
                  ? `내 희망가(${formatKrw(targetPriceKrw)}) 기준으로 계산`
                  : "단지 기준 해제"}
              </button>
            )}
          </>
        )}
      </section>

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
