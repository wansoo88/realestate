/**
 * 단지 카드 — 결론 먼저, 근거는 접기 (ux/README.md §6)
 *
 * 핵심: **추정치를 확정치처럼 보이게 하지 않는다.**
 * 이 서비스는 확신을 파는 게 아니라 판단 근거를 판다.
 */
import type { ComplexItem } from "../api/client";
import { confidenceLabel, formatAsOf, formatKrw } from "../lib/format";
import "./ComplexCard.css";

interface Props {
  item: ComplexItem;
  selected?: boolean;
  onSelect?: (id: number) => void;
}

export function ComplexCard({ item, selected, onSelect }: Props) {
  const estimated = item.price_confidence === "estimated";

  return (
    <article
      className={`card${selected ? " card--selected" : ""}${item.over_budget ? " card--over" : ""}`}
    >
      <button
        className="card__main"
        onClick={() => onSelect?.(item.id)}
        aria-pressed={selected}
      >
        <header className="card__head">
          <h3 className="card__name">{item.name}</h3>
          {item.over_budget && <span className="badge card__over-badge">예산 초과</span>}
        </header>

        <p className={`card__price num${estimated ? " estimated" : ""}`}>
          {item.recent_price_krw === null ? (
            <span className="estimated">데이터 없음</span>
          ) : (
            <>
              {estimated && <span aria-hidden="true">~</span>}
              {formatKrw(item.recent_price_krw)}
              <span className="badge badge--estimated card__conf">
                {confidenceLabel(item.price_confidence)}
              </span>
            </>
          )}
        </p>

        <p className="card__meta">
          {item.built_year ? `${item.built_year}년 준공` : "준공년도 미상"}
          {item.households ? ` · ${item.households.toLocaleString("ko-KR")}세대` : ""}
          {item.active_listings > 0 ? ` · 매물 ${item.active_listings}건` : " · 매물 없음"}
        </p>

        <p className="card__asof">{formatAsOf(item.price_as_of)}</p>
      </button>
    </article>
  );
}
