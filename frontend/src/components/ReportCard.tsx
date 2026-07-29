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
import {
  bandTimeView,
  dongView,
  findingView,
  priceView,
  scoreView,
  summaryBasisView,
} from "../lib/recommendation";
import { coverageView } from "../lib/scoreAxes";
import type { TagId } from "../lib/tags";
import { ConfidenceDots, Price } from "./Price";
import { ScoreCoverage } from "./ScoreCoverage";
import { Section } from "./Section";
import { TagBadges } from "./TagBadges";
import "./ReportCard.css";

interface Props {
  item: RecommendationItem;
  /** 확실히 만족하는 특성(대단지·역세권…). 서버가 사실을 안 주면 비어 있다. */
  tags?: TagId[];
  /** 판정할 수 없어 함께 보인 특성. */
  unknownTags?: TagId[];
  /**
   * 이번 결과에서 AI 요약이 **한 건이라도** 쓰였는가(RecommendPanel 이 계산해 내려준다).
   * 이 값이 false 면 모든 카드가 규칙 기반이므로 카드에는 아무 표기도 하지 않는다 —
   * 그 사실은 결과 전체 고지가 이미 한 번 말한다(CR31-2).
   */
  llmActive?: boolean;
  onShowOnMap?: (complexId: number) => void;
  /**
   * "내 매물"(호가 직접 입력) 화면으로 가는 길 (CR35-2).
   *
   * 이 카드의 점수 설명은 호가가 없으면 *"'내 매물'에서 직접 입력하시면 가격 축이
   * 반영됩니다"* 라고 말한다. 그 문장이 가리키는 화면이 **여기서 열려야** 한다 —
   * 안내만 있고 갈 곳이 없으면 그 문장은 거짓말이다.
   */
  onAddListing?: (complex: { id: number; name: string }) => void;
}

export function ReportCard({
  item,
  tags,
  unknownTags,
  llmActive = false,
  onShowOnMap,
  onAddListing,
}: Props) {
  const price = priceView(item);
  const score = scoreView(item);
  const dong = dongView(item.dong_valuation);
  const band = item.price_band;
  // 이 밴드가 **언제의 가격인지**. 판단은 전부 bandTimeView 안에 있다(CR33-3).
  const bandTime = bandTimeView(band);
  const summary = summaryBasisView(item, { llmActive });

  const coverage = coverageView(item);
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
        {/* 점수: 모르면 "점수 없음". 0 을 쓰지 않는다.
            부분 반영(coverage<100)이면 **점수 옆에** 그 사실을 붙인다 —
            25% 커버리지 점수와 100% 점수를 같은 강도로 그리면 "확신의 농도"가 깨진다(§5.3). */}
        <span
          className={`report__score${score.known ? "" : " report__score--unknown"}${
            coverage.partial ? " report__score--partial" : ""
          }`}
        >
          <span className="num">{score.text}</span>
          {score.known && coverage.badge && (
            <span className="report__score-cov">{coverage.badge}</span>
          )}
        </span>
      </header>

      {!score.known && score.reason && <p className="report__score-why">{score.reason}</p>}

      {/* 특성 배지 — 사실(세대수·역 거리). 서버가 사실을 안 주면 아무것도 그리지 않는다. */}
      <TagBadges tags={tags ?? []} unknownTags={unknownTags ?? []} />

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

      {/* 호가가 없으면 **가격 축이 통째로 빠진다**(가중치 31%). 서버 설명이 가리키는
          "내 매물" 화면으로 가는 길을 그 사실 옆에 둔다 — 안내만 있고 갈 곳이 없으면
          그건 안내가 아니다(CR35-2). */}
      {price.askKrw === null && onAddListing && (
        <p className="report__addask">
          <button
            type="button"
            className="report__addask-btn"
            onClick={() => onAddListing({ id: item.complex.id, name: item.complex.name })}
          >
            이 단지 호가 입력
          </button>
          <span className="report__addask-why">
            네이버 부동산 등에서 본 호가를 적으면 <strong>가격 축</strong>이 이 후보의 점수에
            반영됩니다. 공공 데이터에는 호가가 없습니다.
          </span>
        </p>
      )}

      {/* 적정가 밴드 — 출처 앞에 **시점**을 먼저 밝힌다.
          환산된 중위를 그냥 "국토교통부 실거래가"라고 부르면 원본 체결가로 읽힌다(CR33-3).
          서버가 시점을 말하지 않는 응답(구버전)에서는 꼬리표 자체가 없다 — 없는 걸 주장하지 않는다.
          농도 규칙: 시점 꼬리표는 캡션 색까지만. 금액(중위)보다 튀면 안 된다. */}
      {band && (
        <p className="report__band">
          적정가 밴드 <span className="num">{formatKrw(band.p25_krw)}</span>~
          <span className="num">{formatKrw(band.p75_krw)}</span> · 중위{" "}
          <span className="num">{formatKrw(band.median_krw)}</span>
          <span className="report__band-meta">
            {" ("}
            {bandTime.label && (
              <span className="report__band-asof">{`${bandTime.label} · `}</span>
            )}
            {`${band.source} · 최근 ${band.period_months}개월 ${band.sample_size}건${
              band.expanded ? " · 표본 부족으로 기간 확장" : ""
            })`}
          </span>
          {bandTime.detail && <span className="report__band-why">{bandTime.detail}</span>}
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

      {/* 이 카드의 문장을 누가 썼는가 — **다른 카드는 AI 인데 이것만 규칙 기반일 때만** 뜬다.
          경고가 아니라 출처 표기다(농도 규칙: 약하게). 사유는 서버가 카드 단위로 주지
          않으므로 지어내지 않고 하단 고지를 가리킨다. */}
      {summary.degraded && (
        <p className="report__basis">
          <span className="badge badge--estimated">{summary.label}</span>
          <span className="report__basis-why">{summary.note}</span>
        </p>
      )}

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

      {/* 내 조건이 점수에 어떻게 들어갔는가 — **카드 맨 끝**(사용자 요청: 평가 상세 버튼은 마지막).
          반영률 한 줄만 접히지 않고, 나머지 설명은 '평가 상세' 안으로 들어간다. */}
      <ScoreCoverage item={item} />

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
