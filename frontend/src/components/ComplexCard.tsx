/**
 * 단지 카드 — 컨셉 "확신의 농도".
 *
 * 규칙 2(숫자가 주인공): 카드에서 가장 큰 요소는 항상 금액이다.
 * 규칙 3(밀도는 계층으로): 카드엔 ① 금액 ② 단지명 ③ 한 줄 캡션만. 나머지는 상세로 미룬다.
 * 규칙 1(농도): 추정치는 확정치처럼 보이게 하지 않는다 — 옅은 배지·흐린 캡션으로 절제해 표기.
 * 박스로 두르지 않고 헤어라인 + 여백으로 나눈다.
 */
import { useEffect, useRef } from "react";
import type { ComplexItem } from "../api/client";
import { formatAsOf, formatKrw } from "../lib/format";
import "./ComplexCard.css";

interface Props {
  item: ComplexItem;
  selected?: boolean;
  onSelect?: (id: number) => void;
}

export function ComplexCard({ item, selected, onSelect }: Props) {
  const estimated = item.price_confidence === "estimated";
  const ref = useRef<HTMLButtonElement>(null);

  // 지도 마커로 선택되면 목록에서 해당 카드가 보이도록 스크롤한다(양방향 동기화, ux §3).
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  return (
    <article
      className={`card${selected ? " card--selected" : ""}${item.over_budget ? " card--over" : ""}`}
    >
      <button
        ref={ref}
        className="card__main"
        onClick={() => onSelect?.(item.id)}
        aria-pressed={selected}
      >
        {/* 금액 = 주인공. 확정이 아니면 옅은 '추정' 배지로 근거의 농도를 알린다. */}
        <p className={`card__price num${estimated ? " card__price--est" : ""}`}>
          {item.recent_price_krw === null ? (
            <span className="card__nodata">데이터 없음</span>
          ) : (
            <>
              {formatKrw(item.recent_price_krw)}
              {estimated && <span className="badge badge--estimated card__conf">추정</span>}
            </>
          )}
        </p>

        <header className="card__head">
          <h3 className="card__name">{item.name}</h3>
          {item.over_budget && <span className="badge card__over-badge">예산 초과</span>}
        </header>

        {/* 그 외 정보는 한 줄 캡션으로 눌러둔다(규칙 2: 아이콘 나열 금지) */}
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
