/**
 * 특성 배지 — 🏢대단지 · 🚇역세권 · 🔨재건축.
 *
 * 컨셉("확신의 농도")과의 관계
 * ----------------------------
 * 태그는 **사실**이다(세대수 1,500 · 역까지 320m). 그래서 추정치(시세)처럼 흐리게 둘
 * 이유가 없다. 다만 이 화면의 주인공은 여전히 금액이므로, 배지는 캡션 크기·굵기 400 을
 * 넘지 않는다. 색이 금액보다 튀는 순간 "무엇이 사실이고 무엇이 추정인가"의 위계가
 * 색으로 무너진다.
 *
 * 접근성
 *  · 색은 **보조 채널**이다. 아이콘과 글자가 항상 함께 있고, 색을 전부 지워도 읽힌다.
 *  · 이모지는 `aria-hidden` — 스크린리더가 "사무실 건물"이라고 읽으면 방해만 된다.
 *  · 판정 불가(`unknown`)는 색을 주지 않는다. 모르는 걸 강조하면 아는 것처럼 보인다.
 */
import { tagDef, type TagId } from "../lib/tags";
import "./TagBadges.css";

interface Props {
  /** 확실히 만족하는 태그. */
  tags: TagId[];
  /**
   * 판정할 수 없는 태그. 필터를 걸었는데 이 항목이 "모름"이라 함께 보인 경우에만 온다.
   * 태그처럼 보이되 **"?" 와 회색**으로 확실한 것과 구분한다.
   */
  unknownTags?: TagId[];
}

export function TagBadges({ tags, unknownTags = [] }: Props) {
  if (tags.length === 0 && unknownTags.length === 0) return null;

  return (
    <p className="tags">
      {tags.map((id) => {
        const def = tagDef(id);
        return (
          <span key={id} className={`tag tag--${id}`}>
            <span className="tag__icon" aria-hidden="true">
              {def.icon}
            </span>
            {def.label}
            {/* 기준을 숨기지 않는다 — "왜 이게 대단지인가"에 마우스/스크린리더로 답한다 */}
            <span className="sr-only"> ({def.criterion})</span>
          </span>
        );
      })}

      {unknownTags.map((id) => {
        const def = tagDef(id);
        return (
          <span key={id} className="tag tag--unknown">
            <span className="tag__icon" aria-hidden="true">
              {def.icon}
            </span>
            {def.label} 판정 불가
            <span className="sr-only"> — {def.factLabel} 정보가 없습니다</span>
          </span>
        );
      })}
    </p>
  );
}
