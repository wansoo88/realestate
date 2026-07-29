/**
 * 단지 카드/행 — 컨셉 "확신의 농도".
 *
 * 규칙 2(숫자가 주인공): 가장 굵고 큰 요소는 항상 금액이다.
 * 규칙 3(밀도는 계층으로): ① 금액 ② 단지명 ③ 한 줄 캡션. 나머지는 상세로 미룬다.
 * 규칙 1(농도): 추정치는 확정치처럼 보이게 하지 않는다 — 옅은 배지로 절제해 표기.
 *
 * 폰에서는 **카드**(세로로 읽는다), 데스크톱 우측 패널에서는 **밀도 높은 행**이 된다.
 * 썸네일이 없는 도메인이라 한 줄에 금액·단지명·연식·세대수·매물수가 다 들어간다 —
 * 그래야 스크롤 없이 비교가 된다. DOM 은 하나이고 배치만 CSS 가 바꾼다(ComplexCard.css).
 */
import { useEffect, useRef } from "react";
import type { ComplexItem } from "../api/client";
import { formatAsOf, formatKrw } from "../lib/format";
import type { BudgetVerdict } from "../lib/listFilter";
import type { TagId } from "../lib/tags";
import { TagBadges } from "./TagBadges";
import "./ComplexCard.css";

interface Props {
  item: ComplexItem;
  selected?: boolean;
  /** AI 추천 순위. 없으면 배지 자체가 없다(0 이나 "-" 를 그리지 않는다). */
  rank?: number;
  /** 확실히 만족하는 특성(대단지·역세권…). 모르는 것은 여기 들어오지 않는다. */
  tags?: TagId[];
  /** 필터를 걸었는데 판정할 수 없어 함께 보인 특성. "판정 불가"로 표시한다. */
  unknownTags?: TagId[];
  /**
   * 예산 판정. 주면 이 값이 배지의 근거가 된다(목록은 **항상** 넘긴다).
   *
   * ⚠️ 그 값은 **서버가 항목별로 내린 판정**을 옮긴 것이다(CR38-1 · `lib/budgetStatus`
   *    머리말). 화면이 아는 한도는 하나뿐인데 실제 상한은 면적별로 다르기 때문이다 —
   *    카드가 자기 가격으로 다시 판정하면 120㎡ 단지가 84㎡ 한도로 판정된다.
   *
   * 안 주면 서버의 `over_budget` 을 직접 읽되 **`=== true` 일 때만** 배지를 단다.
   * 그 값은 3값이고(true·false·`null`=판정 못 함), `null` 을 falsy 로 흘려보내면
   * "모른다"가 "예산 내"와 같은 취급이 된다(api-spec §4).
   */
  budget?: BudgetVerdict;
  onSelect?: (id: number) => void;
  /** 목록 ↔ 지도 동기화. 가리키는 동안 해당 마커를 지도에서 들어올린다. */
  onHover?: (id: number | null) => void;
}

export function ComplexCard({
  item,
  selected,
  rank,
  tags,
  unknownTags,
  budget,
  onSelect,
  onHover,
}: Props) {
  const estimated = item.price_confidence === "estimated";
  const overBudget = budget !== undefined ? budget === "over" : item.over_budget === true;
  const ref = useRef<HTMLButtonElement>(null);

  // 지도 마커로 선택되면 목록에서 해당 카드가 보이도록 스크롤한다(양방향 동기화, ux §3).
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  return (
    <article
      className={`card${selected ? " card--selected" : ""}${overBudget ? " card--over" : ""}`}
      // 마우스는 hover, 키보드는 focus — 둘 다 "지금 이걸 보고 있다"는 같은 신호다.
      onMouseEnter={() => onHover?.(item.id)}
      onMouseLeave={() => onHover?.(null)}
      onFocus={() => onHover?.(item.id)}
      onBlur={() => onHover?.(null)}
    >
      <button
        ref={ref}
        className="card__main"
        onClick={() => onSelect?.(item.id)}
        aria-pressed={selected}
      >
        {rank !== undefined && (
          <span className="card__rank num">
            <span className="sr-only">AI 추천 </span>
            {rank}
            <span className="sr-only">위</span>
          </span>
        )}

        {/* 금액 = 주인공. 확정이 아니면 옅은 '추정' 배지로 근거의 농도를 알린다. */}
        <p className={`card__price num${estimated ? " card__price--est" : ""}`}>
          {item.recent_price_krw === null ? (
            <span className="card__nodata">데이터 없음</span>
          ) : (
            <>
              {formatKrw(item.recent_price_krw)}
              {estimated && <span className="badge badge--estimated card__conf">추정</span>}
              {/* **어느 면적의 체결가인가** (CR35-4).
                  한 단지가 34~120㎡ 인데 면적을 말하지 않으면 사용자는 이 금액을 자기가
                  보는 평형의 값으로 읽는다(실측: 서울 단지 절반이 조건 밖 면적, 평균 22.2%
                  어긋남). 금액 **바로 옆**에 두는 이유는 이게 금액의 단위이기 때문이다.
                  서버가 안 주면(구버전) 아무 말도 하지 않는다 — 모르는 걸 지어내지 않는다. */}
              {item.price_area_m2 != null && (
                <span className="card__pricearea">전용 {item.price_area_m2}㎡</span>
              )}
            </>
          )}
        </p>

        <header className="card__head">
          <h3 className="card__name">{item.name}</h3>
          {overBudget && <span className="badge card__over-badge">예산 초과</span>}
        </header>

        {/* 캡션 + 특성 배지는 한 덩어리다(데스크톱 행 배치에서 같은 칸을 쓴다) */}
        <div className="card__metarow">
          {/* 그 외 정보는 한 줄 캡션으로 눌러둔다(규칙 2: 아이콘 나열 금지).
              세대수는 **모르면 모른다고** 적는다 — 빈칸으로 두면 "작은 단지"로 읽힌다. */}
          <p className="card__meta">
            {item.built_year ? `${item.built_year}년 준공` : "준공년도 미상"}
            {item.households
              ? ` · ${item.households.toLocaleString("ko-KR")}세대`
              : " · 세대수 미상"}
            {item.active_listings > 0 ? ` · 매물 ${item.active_listings}건` : " · 매물 없음"}
          </p>

          {/* 특성 배지 — 사실(세대수·거리)이라 색을 줄 자격이 있지만 금액보다 튀지 않는다 */}
          <TagBadges tags={tags ?? []} unknownTags={unknownTags ?? []} />
        </div>

        <p className="card__asof">{formatAsOf(item.price_as_of)}</p>
      </button>
    </article>
  );
}
