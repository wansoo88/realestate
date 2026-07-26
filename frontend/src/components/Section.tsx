/**
 * 접기 섹션 (components.md §3.7).
 *
 * 네이티브 `<details>/<summary>` 로 구현한다 — 키보드·스크린리더·브라우저 검색(Ctrl+F)이
 * 전부 공짜로 따라온다. 직접 만든 아코디언은 이 셋을 전부 다시 만들어야 하고, 대개 못 만든다.
 *
 * ⚠️ `count === 0` 이어도 **섹션을 감추지 않는다.** "확인할 점 없음"을 보여주는 것과
 *    아예 안 보여주는 것은 다르다 — 후자는 리스크를 숨긴 것처럼 읽힌다.
 */
import "./Section.css";

interface Props {
  title: string;
  count?: number;
  tone?: "neutral" | "warn";
  defaultOpen?: boolean;
  emptyText?: string;
  children?: React.ReactNode;
}

export function Section({
  title,
  count,
  tone = "neutral",
  defaultOpen = false,
  emptyText = "해당 없음",
  children,
}: Props) {
  const empty = count === 0;
  return (
    <details className={`section section--${tone}`} open={defaultOpen && !empty}>
      <summary className="section__summary">
        <span className="section__title">{title}</span>
        {count !== undefined && (
          <span className="badge section__count">{count === 0 ? "없음" : `${count}건`}</span>
        )}
      </summary>
      <div className="section__body">{empty ? <p className="section__empty">{emptyText}</p> : children}</div>
    </details>
  );
}
