/**
 * 추천 1건 리포트 (F6) — "왜 이 매물인가"에 답하는 자리.
 *
 * 정직 규칙(이 컴포넌트의 존재 이유)
 * -----------------------------------
 *  · `price_basis="trade"` → **호가가 아니다.** 호가·호가갭을 렌더링하지 않고
 *    서버가 준 `price_note` 를 반드시 보여준다. 시각 강도도 호가보다 약하게(농도 규칙).
 *  · `total_score === null` → "점수 없음". **0 으로 그리지 않는다**(0은 나쁨, null은 모름).
 *  · `missing` 이 있는 finding(예: 입지 데이터 미수집)은 숨기지 않고 **판단 보류로 노출**한다.
 *  · `risks` 가 0건이어도 섹션을 감추지 않는다 — 감추면 리스크를 숨긴 것처럼 읽힌다.
 *
 * 렌더 순서는 components.md §5.6 을 따른다(순서를 바꾸지 않는다).
 */
import type { RecommendationItem } from "../api/client";
import { agentLabel, severityLabel } from "../lib/agentLabels";
import { formatArea, formatKrw, formatPct } from "../lib/format";
import { dongView, findingView, priceView, scoreView } from "../lib/recommendation";
import { ConfidenceDots, Price } from "./Price";
import { Section } from "./Section";
import "./ReportCard.css";

interface Props {
  item: RecommendationItem;
  onShowOnMap?: (complexId: number) => void;
}

export function ReportCard({ item, onShowOnMap }: Props) {
  const price = priceView(item);
  const score = scoreView(item);
  const dong = dongView(item.dong_valuation);
  const band = item.price_band;

  const views = item.findings.map((f) => ({ finding: f, view: findingView(f) }));
  const pending = views.filter((v) => v.view.pending);
  const risks = item.findings.flatMap((f) =>
    f.risks.map((r) => ({ ...r, agent_id: f.agent_id })),
  );

  return (
    <article className={`report${price.estimated ? " report--est" : ""}`}>
      <header className="report__head">
        {item.rank !== undefined && (
          <span className="report__rank" aria-label={`${item.rank}순위`}>
            {item.rank}
          </span>
        )}
        <div className="report__title">
          <h3 className="report__name">{item.complex.name}</h3>
          <p className="report__unit">
            {item.unit_type ? formatArea(item.unit_type.area_m2) : "면적 미상"}
            {item.unit_type?.type_name ? ` · ${item.unit_type.type_name}` : ""}
            {item.building?.name ? ` · ${item.building.name}` : ""}
          </p>
        </div>
        {/* 점수: 모르면 "점수 없음". 0 을 쓰지 않는다. */}
        <span className={`report__score${score.known ? "" : " report__score--unknown"}`}>
          <span className="num">{score.text}</span>
        </span>
      </header>

      {!score.known && score.reason && <p className="report__score-why">{score.reason}</p>}

      {/* 가격 — 호가/실거래 추정을 라벨과 농도로 구분한다 */}
      <Price
        krw={price.krw}
        confidence={price.confidence}
        label={price.label}
        size="lg"
        sampleCount={band?.sample_size ?? null}
      />

      {/* trade 기준일 때만 서버 문구가 온다. 오면 반드시 보여준다. */}
      {price.note && (
        <p className="report__price-note" role="note">
          {price.note}
        </p>
      )}

      {/* 호가 갭은 호가가 있을 때만 존재한다(비교 대상이 없으면 계산 자체를 안 한다) */}
      {price.askKrw !== null && (
        <p className="report__ask">
          호가 <span className="num">{formatKrw(price.askKrw)}</span>
          {price.gapPct !== null && (
            <>
              {" · 적정가 대비 "}
              <span className="num">{formatPct(price.gapPct)}</span>
            </>
          )}
        </p>
      )}

      {band && (
        <p className="report__band">
          적정가 밴드 <span className="num">{formatKrw(band.p25_krw)}</span>~
          <span className="num">{formatKrw(band.p75_krw)}</span> · 중위{" "}
          <span className="num">{formatKrw(band.median_krw)}</span>
          <span className="report__band-meta">
            {` (${band.source} · 최근 ${band.period_months}개월 ${band.sample_size}건${
              band.expanded ? " · 표본 부족으로 기간 확장" : ""
            })`}
          </span>
        </p>
      )}

      {/* 동별 편차(F4) — 실측인지 보류인지 명시 */}
      <p className={`report__dong${dong.measured ? "" : " report__dong--weak"}`}>
        <span className="report__dong-label">{dong.label}</span>
        {dong.available ? (
          <>
            <ConfidenceDots value={dong.confidence} />
            {dong.detail && <span className="report__dong-detail">{dong.detail}</span>}
          </>
        ) : (
          <span className="report__dong-detail">{dong.detail ?? "근거 없음"}</span>
        )}
      </p>
      {dong.available && dong.dongs.length > 0 && (
        <ul className="report__dongs">
          {dong.dongs.slice(0, 4).map((d) => (
            <li key={d.dong}>
              {d.dong}동 <span className="num">{formatPct(d.vs_complex_pct)}</span>
              <span className="report__dong-detail"> · 실거래 {d.sample}건</span>
            </li>
          ))}
        </ul>
      )}

      <p className="report__headline">{item.headline}</p>

      {/* 판단 보류 — 숨기면 "분석했다"는 인상만 남는다. 무엇을 못 봤는지 앞에 둔다. */}
      {pending.length > 0 && (
        <ul className="report__pending" aria-label="판단 보류 항목">
          {pending.map(({ finding, view }) => (
            <li key={finding.agent_id} className="report__pending-item">
              <span className="badge report__pending-badge">판단 보류</span>
              <span title={finding.agent_id}>{agentLabel(finding.agent_id)}</span>
              <span className="report__pending-why">{view.missing.join(", ")}</span>
            </li>
          ))}
        </ul>
      )}

      <Section title="좋은 점" count={item.why.length} defaultOpen>
        <ul className="report__list">
          {item.why.map((w, i) => (
            <li key={`${w}-${i}`}>{w}</li>
          ))}
        </ul>
      </Section>

      {/* 단점·리스크는 0건이어도 섹션을 남긴다 */}
      <Section
        title="확인할 점"
        count={item.why_not.length + risks.length}
        tone="warn"
        emptyText="확인된 하방 리스크 없음 — 데이터 부족일 수 있습니다."
      >
        <ul className="report__list">
          {item.why_not.map((w, i) => (
            <li key={`${w}-${i}`}>{w}</li>
          ))}
        </ul>
        <ul className="report__risks">
          {risks.map((r, i) => (
            <li key={`${r.agent_id}-${i}`} className={`report__risk report__risk--${r.severity}`}>
              <span className="badge">{severityLabel(r.severity)}</span>
              <span>{r.detail}</span>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="전문가별 근거" count={views.length}>
        <ul className="report__findings">
          {views.map(({ finding, view }) => (
            <li key={finding.agent_id} className="report__finding">
              <p className="report__finding-head">
                <span title={finding.agent_id}>{agentLabel(finding.agent_id)}</span>
                <span className="report__verdict">{finding.verdict}</span>
                <span className="report__finding-score num">{view.scoreText}</span>
              </p>
              <p className="report__rationale">{finding.rationale}</p>
              {/* 출처 없는 근거는 렌더링하지 않는다(G2) */}
              {view.evidence.map((e, i) => (
                <p key={`${finding.agent_id}-ev-${i}`} className="report__evidence">
                  {e.claim}
                  <span className="report__evidence-src">
                    {` — ${e.source ?? "출처 미상"}`}
                    {e.as_of ? ` · ${e.as_of}` : ""}
                    {e.data_rows ? ` · ${e.data_rows}건` : ""}
                  </span>
                </p>
              ))}
            </li>
          ))}
        </ul>
      </Section>

      {item.next_actions.length > 0 && (
        <Section title="다음에 할 일" count={item.next_actions.length}>
          <ul className="report__list">
            {item.next_actions.map((a, i) => (
              <li key={`${a}-${i}`}>{a}</li>
            ))}
          </ul>
        </Section>
      )}

      {onShowOnMap && (
        <button
          type="button"
          className="report__map-btn"
          onClick={() => onShowOnMap(item.complex.id)}
        >
          지도에서 보기
        </button>
      )}
    </article>
  );
}
