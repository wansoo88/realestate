/**
 * AI 추천 실행 + 결과 (F1·F3·F6) — 이 제품의 **출력 쪽 절반**.
 *
 * 화면이 반드시 답해야 하는 두 질문
 *  ① "왜 이게 1순위인가" → `ReportCard`(why / why_not / 근거)
 *  ② "왜 저건 안 나왔나" → `excluded[]`(제외 후보와 사유). 이게 없으면 사용자는
 *     결과를 신뢰하지 못하고, 신뢰하지 못하면 이 도구를 쓸 이유가 없다.
 *
 * ⚠️ 재분석은 **명시적 버튼으로만** 실행한다. 조건을 만질 때마다 돌면 Claude API 비용이
 *    사고가 된다(architecture.md §6).
 */
import { useMemo } from "react";
import type { RecommendationJob } from "../api/client";
import { useTagFilter } from "../hooks/useTagFilter";
import { sameBbox } from "../lib/bbox";
import { formatKrwShort } from "../lib/format";
import { budgetVerdict, filterList } from "../lib/listFilter";
import { NOTICE_NOT_ADVICE, NOTICE_TRADE_DELAY } from "../lib/notices";
import { llmSummaryActive, progressText, type JobPhase } from "../lib/recommendation";
import { conditionText, type ConditionPlan } from "../lib/recommendConditions";
import { scopeText, type SearchScope } from "../lib/searchScope";
import { recommendationTagFacts } from "../lib/tags";
import { AreaScope } from "./AreaScope";
import { ListFilterBar } from "./ListFilterBar";
import { RegionPicker } from "./RegionPicker";
import { ReportCard } from "./ReportCard";
import { Section } from "./Section";
import "./RecommendPanel.css";

interface Props {
  phase: JobPhase;
  job: RecommendationJob | null;
  error: string | null;
  budgetKrw: number | null;
  /**
   * 목록 필터가 쓰는 실효 예산(희망가 우선, 없으면 한도).
   *
   * ⚠️ **키를 넘겼으면 `null` 도 그 값 그대로 쓴다** — `?? budgetKrw` 로 접지 않는다.
   *    `null` 은 "예산이 없다"가 아니라 "지금은 초과 표시를 하지 않는다"(예산 칩 꺼짐)일
   *    수 있고, 접으면 지도는 배지가 사라졌는데 추천만 배지가 남는다(CR37-7).
   *    아예 안 넘긴 호출부(`undefined`)만 `budgetKrw` 로 폴백한다.
   */
  listBudgetKrw?: number | null;
  /** 초과 표시가 꺼져 있는가 — 목록 위 문장이 "예산 미상"과 구분해 말한다. */
  budgetDisplayOff?: boolean;
  /** 예산 내만 보기. 주변 단지 목록과 **같은 스위치**를 공유한다. */
  budgetOnly?: boolean;
  onBudgetOnlyChange?: (on: boolean) => void;
  /** 분석 지역(5자리 시군구). 빈 배열 = 지역 제한 없음. */
  regionCodes: string[];
  onRegionsChange: (codes: string[]) => void;
  /** 지도가 지금 보고 있는 범위. null = 지도 미준비. */
  currentBbox: string | null;
  /** "이 주변"으로 잡아 둔 범위. */
  areaBbox: string | null;
  onCaptureArea: (bbox: string) => void;
  onClearArea: () => void;
  /**
   * 이번 결과가 **실제로 돌아간** 범위. 결과가 나온 뒤 지도를 옮기거나 칩을 해제해도
   * 이 값은 그대로 남는다 — 그러지 않으면 "그때 그 범위"가 뭐였는지 알 길이 사라진다.
   */
  appliedScope: SearchScope | null;
  /**
   * 지금 누르면 걸릴 "내 조건"(실행 전 표시). 없으면 조건 줄 자체를 그리지 않는다.
   * 조건 칩을 껐는데 추천만 계속 걸러지던 사고(FE-4) 이후, 화면은 **무엇이 걸리고
   * 무엇이 꺼졌는지**를 실행 전에도 후에도 말해야 한다.
   */
  conditions?: ConditionPlan | null;
  /** 이번 결과가 **실제로 쓴** 조건. 결과가 나온 뒤 칩을 만져도 이 값은 남는다. */
  appliedConditions?: ConditionPlan | null;
  onStart: () => void;
  onCancel: () => void;
  onShowOnMap?: (complexId: number) => void;
  onEditConditions?: () => void;
  /**
   * "내 매물"(호가 직접 입력)로 가는 길 (CR35-2).
   * 결과 카드의 설명이 그 화면을 가리키므로, 그 자리에서 열 수 있어야 한다.
   */
  onAddListing?: (complex: { id: number; name: string }) => void;
}

export function RecommendPanel({
  phase,
  job,
  error,
  budgetKrw,
  listBudgetKrw,
  budgetDisplayOff = false,
  budgetOnly = false,
  onBudgetOnlyChange,
  regionCodes,
  onRegionsChange,
  currentBbox,
  areaBbox,
  onCaptureArea,
  onClearArea,
  appliedScope,
  conditions = null,
  appliedConditions = null,
  onStart,
  onCancel,
  onShowOnMap,
  onEditConditions,
  onAddListing,
}: Props) {
  const running = phase === "queued" || phase === "running";
  const items = useMemo(() => job?.items ?? [], [job]);
  const excluded = job?.excluded ?? null;

  /**
   * 이번 결과에 AI 요약이 **한 건이라도** 쓰였는가.
   *
   * 이 값이 카드별 강등 표기의 스위치다(CR31-2). LLM 미연결이면 모든 카드가 규칙 기반이라
   * 카드마다 배지를 달면 소음이 되고, 그건 이미 job notes 가 한 번 말한다.
   * **AI 가 돌았는데 이 카드만 규칙 기반인 경우**가 진짜 알려야 할 상황이다.
   */
  const llmActive = useMemo(() => llmSummaryActive(items), [items]);

  const tagFilter = useTagFilter();

  /**
   * 예산·특성 필터. **순위(rank)는 건드리지 않는다** — 걸러낸 뒤에도 카드에 찍히는 번호는
   * 서버가 준 원래 순위다. 필터 결과에 1,2,3 을 새로 붙이면 그건 새 순위처럼 읽히는
   * 거짓 정보가 된다("3위였던 게 1위로 올랐다"고 읽힌다).
   *
   * ⚠️ **화면이 예산을 판정하는 유일한 목록이다** (CR38-1).
   *    지도·목록은 서버가 항목마다 그 면적의 한도로 판정해 준 값(`over_budget`)을 쓰지만,
   *    추천 응답에는 항목별 판정이 없다. 그래서 여기서만 금액 하나로 판정한다.
   *
   *    두 목록이 다른 말을 하지 않는가 — 그 위험은 두 가지로 막혀 있다.
   *      · 추천 카드에는 **예산 배지가 없다**(`ReportCard`). 이 판정은 `예산 내` 토글이
   *        몇 건을 숨겼는지 세는 데만 쓰이고, 지도 배지와 한 화면에서 만나지 않는다.
   *      · 두 목록은 애초에 다른 금액을 말한다 — 지도는 최근 체결 1건, 추천은 창 중위를
   *        기준월로 환산한 추정가(CR35-4). 각자 **자기가 보여주는 금액**으로 판정하는
   *        것이 원칙이고, 여기서 쓰는 값이 카드에 찍히는 `est_price_krw` 다.
   */
  const outcome = useMemo(
    () =>
      filterList(
        items.map((item) => ({
          item,
          // `undefined`(안 넘김)일 때만 폴백한다. `null` 은 넘긴 사람의 뜻이다(위 주석).
          budget: budgetVerdict(
            item.est_price_krw,
            listBudgetKrw === undefined ? budgetKrw : listBudgetKrw,
          ),
          facts: recommendationTagFacts(item),
        })),
        {
          budgetOnly,
          tags: tagFilter.tags,
          includeUnknownTag: tagFilter.includeUnknown,
        },
      ),
    [items, budgetOnly, listBudgetKrw, budgetKrw, tagFilter.tags, tagFilter.includeUnknown],
  );

  /** 결과를 낸 범위가 지금 지도와 다른가 — 다르면 "지금 화면 = 결과"로 읽히지 않게 말한다. */
  const resultAreaMoved =
    appliedScope?.bbox != null && !sameBbox(appliedScope.bbox, currentBbox);

  /* 조건도 범위와 같은 규칙: 결과가 있으면 **그때 조건**, 없으면 **지금 조건**. */
  const resultPhase = running || phase === "done";
  const plan = (resultPhase ? (appliedConditions ?? conditions) : conditions) ?? null;
  const onText = plan ? conditionText(plan.on) : null;
  const offText = plan ? conditionText(plan.off) : null;
  const mapOnlyMissing = plan?.on.filter((c) => c.side === "rec_only") ?? [];

  return (
    <div className="rec">
      <p className="rec__budget">
        {budgetKrw
          ? `내 예산 ${formatKrwShort(budgetKrw)} 기준으로 분석합니다.`
          : "예산이 아직 계산되지 않았습니다 — 자산을 입력하면 예산 안에서만 후보를 세웁니다."}
      </p>

      {/* 어디에서 찾을지 — 분석을 **시작하기 전에** 정한다. 실행 버튼 바로 위가 제자리다.
          빠른 길(이 주변)을 먼저, 정밀한 길(시군구)을 다음에 둔다. */}
      <AreaScope
        currentBbox={currentBbox}
        bbox={areaBbox}
        onCapture={onCaptureArea}
        onClear={onClearArea}
        regionCodes={regionCodes}
        disabled={running}
      />
      <RegionPicker
        value={regionCodes}
        onChange={onRegionsChange}
        areaScoped={areaBbox !== null}
        disabled={running}
      />

      <div className="rec__actions">
        <button type="button" className="rec__run" onClick={onStart} disabled={running}>
          {running ? "분석 중…" : phase === "done" ? "다시 분석" : "AI 추천 실행"}
        </button>
        {running && (
          <button type="button" className="rec__cancel" onClick={onCancel}>
            중단
          </button>
        )}
      </div>

      {/* 진행 상태 — 빈 스피너 금지. 진행률은 서버가 줄 때만 말한다(지어내지 않는다). */}
      {running && (
        <p className="rec__status" role="status" aria-live="polite">
          {progressText({ status: job?.status ?? "queued", progress: job?.progress })}
        </p>
      )}

      {error && (
        <p className="rec__error" role="alert">
          {error}
        </p>
      )}

      {/* 이 결과가 **어느 범위에서** 나왔는지. 실행 후 지도를 옮기면 화면과 결과가
          어긋나므로, 결과 옆에 범위를 붙여 두지 않으면 사용자가 알 수 없다. */}
      {appliedScope && (running || phase === "done") && (
        <p className="rec__scope">
          {running ? "분석 범위" : "이 결과를 찾은 범위"}: {scopeText(appliedScope)}
          {resultAreaMoved && (
            <span className="rec__scope-moved"> · 지금 보고 있는 지도와 다른 범위입니다</span>
          )}
        </p>
      )}

      {/* 이 결과가 **어떤 조건으로** 나왔는지. 범위(위)와 짝을 이룬다.
          FE-4 이전에는 이 줄이 없어서, 칩을 껐는데 추천만 계속 걸러져도
          화면 어디에도 그 사실이 없었다. */}
      {plan && (onText || offText) && (
        <div className="rec__conds">
          {onText && (
            <p className="rec__conds-line">
              <span className="rec__conds-key">
                {resultPhase ? "이 결과에 적용된 조건" : "적용할 조건"}
              </span>
              <span>{onText}</span>
            </p>
          )}
          {/* 껐다는 사실은 **결과 옆에** 남아야 한다 — 조건이 없어서 안 걸린 것과
              사용자가 꺼서 안 걸린 것은 다른 이야기다. */}
          {offText && (
            <p className="rec__conds-line rec__conds-line--off">
              <span className="rec__conds-key">꺼 둔 조건</span>
              <span>{offText} — 지도와 추천 모두 적용하지 않았습니다.</span>
            </p>
          )}
          {/* 지도와 추천이 다른 조건으로 돌면 반드시 말한다.
              말하지 않으면 "지도엔 보이는데 추천엔 없는 단지"의 이유가 사라진다. */}
          {mapOnlyMissing.length > 0 && (
            <p className="rec__conds-diff">
              {mapOnlyMissing.map((c) => c.label).join(" · ")} 은(는) 추천에만 걸립니다 —
              지도 목록과 결과가 다를 수 있습니다.
            </p>
          )}
        </div>
      )}

      {phase === "done" && items.length === 0 && (
        <div className="rec__empty">
          <p className="rec__empty-title">조건에 맞는 후보가 없습니다.</p>
          <p className="rec__empty-body">
            예산·기피 조건에 걸렸거나, 아직 수집된 실거래·매물 데이터가 없을 수 있습니다.
            지어낸 후보를 채우지 않습니다.
          </p>
          {!excluded && (
            <p className="rec__empty-body rec__empty-body--weak">
              제외 사유 목록은 이번 응답에 포함되지 않았습니다.
            </p>
          )}
          {onEditConditions && (
            <button type="button" className="rec__edit" onClick={onEditConditions}>
              조건 넓히기
            </button>
          )}
        </div>
      )}

      {/* 결과가 있을 때만 필터 줄을 낸다 — 거를 게 없으면 조작도 없다 */}
      {phase === "done" && items.length > 0 && (
        <ListFilterBar
          listLabel="AI 추천"
          outcome={outcome}
          budgetOnly={budgetOnly}
          onBudgetOnlyChange={onBudgetOnlyChange ?? (() => {})}
          onToggleTag={tagFilter.toggle}
          onClearTags={tagFilter.clear}
          includeUnknownTag={tagFilter.includeUnknown}
          onIncludeUnknownChange={tagFilter.setIncludeUnknown}
          budgetDisplayOff={budgetDisplayOff}
        />
      )}

      {/* 필터로 0건이 되면 "추천이 없다"가 아니라 "가려졌다"고 말한다 */}
      {phase === "done" && items.length > 0 && outcome.entries.length === 0 && (
        <p className="rec__filtered" role="status">
          필터에 걸려 추천 {items.length}건이 모두 가려졌습니다. 예산 토글이나 특성 칩을
          꺼 보세요.
        </p>
      )}

      {outcome.entries.map((entry) => (
        <ReportCard
          key={`${entry.item.complex.id}-${entry.item.unit_type?.area_m2 ?? "na"}`}
          item={entry.item}
          tags={entry.tags}
          unknownTags={entry.unknownTags}
          llmActive={llmActive}
          onShowOnMap={onShowOnMap}
          onAddListing={onAddListing}
        />
      ))}

      {/* "왜 이건 안 나왔지"에 답하는 자리 */}
      {excluded && (
        <Section title="제외된 후보" count={excluded.length}>
          <ul className="rec__excluded">
            {excluded.map((e, i) => (
              <li key={`${e.complex_id}-${i}`}>
                <span className="rec__excluded-name">
                  {e.complex_name ?? `단지 #${e.complex_id}`}
                </span>
                <span className="rec__excluded-reason">{e.reason}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {job?.notes && job.notes.length > 0 && (
        <ul className="rec__notes">
          {job.notes.map((n, i) => (
            <li key={`${n}-${i}`}>{n}</li>
          ))}
        </ul>
      )}

      {phase === "done" && (
        <footer className="rec__foot">
          <p>{NOTICE_TRADE_DELAY}</p>
          <p>{job?.disclaimer ?? NOTICE_NOT_ADVICE}</p>
        </footer>
      )}
    </div>
  );
}
