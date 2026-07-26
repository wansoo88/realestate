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
import type { RecommendationJob } from "../api/client";
import { formatKrwShort } from "../lib/format";
import { NOTICE_NOT_ADVICE, NOTICE_TRADE_DELAY } from "../lib/notices";
import { progressText, type JobPhase } from "../lib/recommendation";
import { ReportCard } from "./ReportCard";
import { Section } from "./Section";
import "./RecommendPanel.css";

interface Props {
  phase: JobPhase;
  job: RecommendationJob | null;
  error: string | null;
  budgetKrw: number | null;
  onStart: () => void;
  onCancel: () => void;
  onShowOnMap?: (complexId: number) => void;
  onEditConditions?: () => void;
}

export function RecommendPanel({
  phase,
  job,
  error,
  budgetKrw,
  onStart,
  onCancel,
  onShowOnMap,
  onEditConditions,
}: Props) {
  const running = phase === "queued" || phase === "running";
  const items = job?.items ?? [];
  const excluded = job?.excluded ?? null;

  return (
    <div className="rec">
      <p className="rec__budget">
        {budgetKrw
          ? `내 예산 ${formatKrwShort(budgetKrw)} 기준으로 분석합니다.`
          : "예산이 아직 계산되지 않았습니다 — 자산을 입력하면 예산 안에서만 후보를 세웁니다."}
      </p>

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

      {items.map((item) => (
        <ReportCard
          key={`${item.complex.id}-${item.unit_type?.area_m2 ?? "na"}`}
          item={item}
          onShowOnMap={onShowOnMap}
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
