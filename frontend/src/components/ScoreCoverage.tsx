/**
 * 평가 반영률 + 평가 상세 (api-spec §5.3).
 *
 * 두 층으로 나눈다.
 *  ① **항상 보임** — "설정하신 가중치의 52%만 반영됐습니다" + 한 줄 사유.
 *     이건 상세가 아니라 헤드라인이다. 접으면 사용자는 지금 순위를 "내가 설정한 대로
 *     나온 순위"로 오해한다. 그 오해가 곧 잘못된 매수 판단이 된다.
 *  ② **접힘** — 축별 반영/미반영, 왜 못 봤는지, 어떻게 계산했는지, 아직 못 보는 것.
 *     `<details>` 를 쓰는 이유는 Section 과 같다: 키보드·스크린리더·Ctrl+F 가 공짜.
 *
 * 100% 반영이면 ①을 띄우지 않는다. 항상 뜨는 경고는 아무도 읽지 않는다.
 * (그래도 ②는 남는다 — 궁금한 사람은 언제든 열어 볼 수 있어야 한다.)
 */
import type { RecommendationItem } from "../api/client";
import { coverageDetail } from "../lib/scoreCoverage";
import "./ScoreCoverage.css";

interface Props {
  item: RecommendationItem;
}

export function ScoreCoverage({ item }: Props) {
  const d = coverageDetail(item);
  if (!d.hasDetail) return null;

  return (
    <section className={`cov cov--${d.tone}`} aria-label="평가 반영률">
      {/* ── 접히지 않는 부분 ─────────────────────────────────────────── */}
      {d.warn && (
        <p className="cov__head">
          <span className="cov__icon" aria-hidden="true">
            ⚠
          </span>
          <span>{d.headline}</span>
        </p>
      )}
      {d.reason && <p className="cov__why">{d.reason}</p>}

      {/* ── 접히는 부분 ─────────────────────────────────────────────── */}
      <details className="cov__details">
        <summary className="cov__summary">평가 상세</summary>

        <div className="cov__body">
          {d.applied.length + d.dropped.length > 0 && (
            <dl className="cov__split">
              <div className="cov__split-row">
                <dt>반영됨</dt>
                <dd>
                  {d.applied.length > 0 ? (
                    <>
                      {d.applied.map((a) => (
                        <span key={a.axis} className="cov__axis">
                          {a.label} <span className="num">{a.weightPct}%</span>
                        </span>
                      ))}
                      <span className="cov__sum">
                        합계 <span className="num">{d.appliedSumPct}%</span>
                      </span>
                    </>
                  ) : (
                    <span className="cov__none">없음</span>
                  )}
                </dd>
              </div>

              {d.dropped.length > 0 && (
                <div className="cov__split-row cov__split-row--off">
                  <dt>미반영</dt>
                  <dd>
                    {d.dropped.map((a) => (
                      <span key={a.axis} className="cov__axis">
                        {a.label} <span className="num">{a.weightPct}%</span>
                      </span>
                    ))}
                    <span className="cov__sum">
                      합계 <span className="num">{d.droppedSumPct}%</span>
                    </span>
                  </dd>
                </div>
              )}
            </dl>
          )}

          {d.reasons.length > 0 && (
            <section className="cov__block">
              <h4 className="cov__h">왜 못 봤나요</h4>
              <ul className="cov__list">
                {d.reasons.map((r) => (
                  <li key={r.axis}>
                    <span className="cov__label">{r.label}</span>
                    <span>{r.text}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {d.method.length > 0 && (
            <section className="cov__block">
              <h4 className="cov__h">점수는 어떻게 냈나요</h4>
              <ul className="cov__list cov__list--plain">
                {d.method.map((m, i) => (
                  <li key={`${m}-${i}`}>{m}</li>
                ))}
              </ul>
            </section>
          )}

          {/* 반영됐어도 남는 한계 — "호가만 들어오면 다 본다"는 오해를 막는다 */}
          {d.limits.length > 0 && (
            <section className="cov__block">
              <h4 className="cov__h">아직 못 보는 것</h4>
              <ul className="cov__list">
                {d.limits.map((l) => (
                  <li key={l.axis}>
                    <span className="cov__label">{l.label}</span>
                    <span>{l.text}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* 내가 0% 로 둔 항목 — "빠졌다"가 아니라 "안 봤다"이다. 다르게 말한다. */}
          {d.zeroWeight.length > 0 && (
            <section className="cov__block">
              <h4 className="cov__h">내가 0% 로 둔 항목</h4>
              <p className="cov__plain">
                {d.zeroWeight.map((z) => z.label).join(" · ")} — 처음부터 점수에 넣지 않았습니다.
              </p>
            </section>
          )}

          {/* 구버전 서버(축 정보 없음) 폴백 — 고지가 사라지지 않게 원문을 그대로 */}
          {d.rawNotes.length > 0 && (
            <ul className="cov__list cov__list--plain" aria-label="점수에 반영되지 않은 항목">
              {d.rawNotes.map((n, i) => (
                <li key={`${n}-${i}`}>{n}</li>
              ))}
            </ul>
          )}
        </div>
      </details>
    </section>
  );
}
