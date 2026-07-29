/**
 * 목록 위의 필터 줄 — **예산 내 토글 + 특성 칩**.
 *
 * 왜 섹션을 나누지 않고 칩으로 묶었나
 * -----------------------------------
 * "대단지 3건 / 역세권 5건" 처럼 섹션을 쪼개면 ① 한 단지가 두 곳에 중복으로 나오고
 * ② 각 섹션이 1,2,3 으로 다시 번호를 매기게 되어 **원래 순위가 사라진다.**
 * 칩은 목록 하나를 유지한 채 좁히기만 하므로 순위도 중복 없음도 지켜진다.
 *
 * 이 줄이 반드시 지키는 것
 *  · **숨긴 건 숫자로 말한다.** 예산 토글도, 판정 불가 제외도 몇 건인지 적는다.
 *  · **0건과 모름을 구분한다.** 세대수를 아무도 모르면 그건 "대단지가 없다"가 아니다.
 *  · **다중 선택은 교집합**이고, 그 사실을 문장으로 적는다(칩만 둘이면 합집합으로 읽힌다).
 *
 * 모바일: 칩이 늘어나면 가로 스크롤(한 손 도달 범위를 넘기지 않게 한 줄 유지).
 */
import { useId } from "react";
import {
  budgetNotice,
  tagUnknownNotice,
  unmeasurableNotice,
  type FilterOutcome,
} from "../lib/listFilter";
import type { TagId } from "../lib/tags";
import "./ListFilterBar.css";

interface Props<T> {
  /** 무엇을 거르는 목록인가 — 보조기기용 이름("주변 단지"·"AI 추천"). */
  listLabel: string;
  outcome: FilterOutcome<T>;
  budgetOnly: boolean;
  onBudgetOnlyChange: (on: boolean) => void;
  onToggleTag: (id: TagId) => void;
  onClearTags: () => void;
  includeUnknownTag: boolean;
  onIncludeUnknownChange: (on: boolean) => void;
  /**
   * 사용자가 '내 조건'의 예산 칩을 꺼서 **초과 표시 자체가 꺼져 있는가** (CR37-7).
   *
   * `outcome.budgetKnown === false` 와 같은 모양이지만 **다른 사실**이다:
   * 하나는 "예산을 아직 모른다", 하나는 "알지만 표시를 껐다". 같은 문장으로 말하면
   * 사용자는 자기가 방금 끈 스위치를 고장으로 읽는다.
   */
  budgetDisplayOff?: boolean;
}

export function ListFilterBar<T>({
  listLabel,
  outcome,
  budgetOnly,
  onBudgetOnlyChange,
  onToggleTag,
  onClearTags,
  includeUnknownTag,
  onIncludeUnknownChange,
  budgetDisplayOff = false,
}: Props<T>) {
  /** 같은 화면에 이 줄이 둘(주변 단지·AI 추천) 있어도 id 가 겹치지 않게. */
  const noteId = useId();
  /**
   * 표시를 껐으면 그 사실을 말한다 — 예산을 모르는 것과 섞지 않는다.
   * 그리고 **되돌아가는 길**(어느 스위치를 켜면 되는지)을 문장 안에 적는다.
   */
  const budgetText = budgetDisplayOff
    ? "예산 초과 표시를 꺼 두었습니다 — '내 조건'의 예산 칩을 켜면 초과 단지에 배지가 붙고, 이 스위치로 숨길 수 있습니다."
    : budgetNotice(outcome, budgetOnly);
  const tagText = tagUnknownNotice(outcome);
  const unmeasurableText = unmeasurableNotice(outcome);
  const anyTagSelected = outcome.mode !== "all";
  const hasUnknownToOffer = outcome.hiddenTagUnknown > 0 || outcome.shownTagUnknown > 0;

  return (
    <div className="lfb">
      <div className="lfb__top">
        {/*
          role="switch" 를 쓰는 이유: 이건 "누르면 실행"이 아니라 **켜짐/꺼짐 상태**다.
          aria-checked 로 지금 상태가 보조기기에 그대로 전달된다.
          예산을 모르면 켤 수 없다 — 켜 봐야 전부 사라진 빈 화면이 되기 때문이다.
        */}
        <button
          type="button"
          role="switch"
          aria-checked={budgetOnly && outcome.budgetKnown}
          disabled={!outcome.budgetKnown}
          /* 못 켜는 이유를 스위치 **자신에게** 붙인다. 비활성 버튼은 초점을 못 받아
             아래 문장까지 못 읽고 지나칠 수 있다 — 그러면 "왜 안 눌리지"가 된다. */
          aria-describedby={budgetText ? noteId : undefined}
          className={`lfb__switch${budgetOnly && outcome.budgetKnown ? " lfb__switch--on" : ""}`}
          onClick={() => onBudgetOnlyChange(!budgetOnly)}
        >
          <span className="lfb__track" aria-hidden="true">
            <span className="lfb__thumb" />
          </span>
          예산 내
        </button>

        <span className="lfb__shown">
          <span className="num">{outcome.entries.length}</span>
          <span className="lfb__shown-unit">건 표시</span>
          {outcome.entries.length !== outcome.total && (
            <span className="lfb__shown-total"> / 전체 {outcome.total}건</span>
          )}
        </span>
      </div>

      {/* 무엇을 몇 건 숨겼는지. 조용히 사라지면 사용자는 "왜 안 보이지?"가 된다. */}
      {budgetText && (
        <p className="lfb__note" id={noteId} role="status">
          {budgetText}
        </p>
      )}

      <div className="lfb__chips" role="group" aria-label={`${listLabel} 특성 필터`}>
        {/*
          접근성 이름을 `aria-label` 로 직접 준다. 아이콘·숫자·기준이 각각 다른 요소라
          기본 계산에 맡기면 "대단지 2 건 · 기준…" 처럼 끊겨 읽힌다.
          보이는 글자(라벨+숫자)는 이름의 부분집합이라 음성 조작과도 어긋나지 않는다.
        */}
        <button
          type="button"
          className={`lfb__chip${!anyTagSelected ? " lfb__chip--on" : ""}`}
          aria-pressed={!anyTagSelected}
          aria-label={`전체 ${outcome.entries.length}건`}
          onClick={onClearTags}
        >
          전체
          <span className="lfb__chip-count num">{outcome.entries.length}</span>
        </button>

        {outcome.chips.map((chip) => (
          <button
            key={chip.id}
            type="button"
            className={`lfb__chip lfb__chip--${chip.id}${chip.selected ? " lfb__chip--on" : ""}`}
            aria-pressed={chip.selected}
            // 0건일 때 "없다"인지 "모른다"인지를 보조기기에도 정확히 전달한다
            aria-label={
              `${chip.label} ${chip.count}건` +
              (chip.disabled && chip.unknown > 0
                ? ` — 해당 없음이 아니라 ${chip.unknown}건을 판정할 수 없습니다`
                : "") +
              ` · 기준 ${chip.criterion}`
            }
            // 해당 0건은 눌러도 결과가 비어 있다. 숨기지는 않는다 — "없다"도 정보다.
            disabled={chip.disabled}
            onClick={() => onToggleTag(chip.id)}
          >
            <span className="lfb__chip-icon" aria-hidden="true">
              {chip.icon}
            </span>
            {chip.label}
            <span className="lfb__chip-count num">{chip.count}</span>
          </button>
        ))}
      </div>

      {/* 교집합인지 합집합인지를 화면이 분명히 말한다 */}
      {outcome.mode === "intersection" && (
        <p className="lfb__mode">고른 특성을 모두 만족하는 항목만 보입니다.</p>
      )}

      {/* 판정 불가를 '아님'으로 접지 않는다 — 몇 건인지 말하고, 볼 수 있게 해 준다 */}
      {tagText && (
        <p className="lfb__note lfb__note--unknown" role="status">
          {tagText}
        </p>
      )}
      {hasUnknownToOffer && (
        <button
          type="button"
          className="lfb__reveal"
          aria-pressed={includeUnknownTag}
          onClick={() => onIncludeUnknownChange(!includeUnknownTag)}
        >
          {includeUnknownTag ? "판정 불가 항목 숨기기" : "판정 불가 항목도 보기"}
        </button>
      )}

      {/* "0건"이 사실은 "모름"일 때 그 사실을 말한다 */}
      {unmeasurableText && (
        <p className="lfb__note lfb__note--unknown">{unmeasurableText}</p>
      )}
    </div>
  );
}
