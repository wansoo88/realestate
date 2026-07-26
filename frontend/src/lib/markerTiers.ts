/**
 * 마커 표현 단계 — **한 화면에 가격 pill 이 200개 뜨는 상태는 설계 실패다.**
 *
 * 왜 이 파일이 따로 있나
 * ----------------------
 * 예전 구현은 모든 단지를 똑같은 무게의 "추정 8.4억" pill 로 찍었다. 강남·송파처럼 밀집한
 * 구역에서는 화면이 가격 텍스트로 덮여 **지도가 사라지고**, 어디를 봐야 할지 위계도 없었다.
 * (사용자 지적: "완성도 측면에서 좋지 않습니다")
 *
 * 널리 쓰이는 지도 서비스(네이버 부동산·호갱노노)의 공통 패턴을 그대로 따른다.
 *   광역   → 지역 군집 원 + 건수      (이건 서버가 level="cluster" 로 내려준다)
 *   중간   → **가격만** 압축해서      ("8.4억")
 *   근접   → **단지명 + 가격**
 *   밀집   → pill 을 **점으로 강등**  (텍스트를 지운다)
 *
 * ⚠️ 강등은 "정보를 줄이는" 선택이라 그냥 하면 안 된다. 이 제품의 규칙(모르는 걸 숨기지 않는다)을
 *    지키려면 **숨긴 것을 되찾을 경로**가 반드시 함께 있어야 한다. 그래서:
 *      ① 목록(바텀시트/우측 패널)에는 **언제나 전부** 가격과 함께 남는다
 *      ② 강등되면 `densityNotice()` 로 "무엇을 왜 줄였는지" 화면에 밝힌다
 *      ③ 점을 탭하면 그 마커만 즉시 상세로 승격된다(선택은 강등 대상이 아니다)
 *
 * 순수 함수만 둔다 — SDK·DOM 없이 테스트할 수 있어야 줌·밀집 전이를 못박을 수 있다.
 */

/** dot: 텍스트 없는 점 · price: 가격만 · detail: 단지명 + 가격 */
export type MarkerTier = "dot" | "price" | "detail";

/**
 * 이 개수를 **넘으면** 가격 pill 을 점으로 강등한다.
 *
 * 60 인 근거: 360px 폰 화면에 가로 3~4개, 세로 8~10줄이 겹치지 않게 들어가는 상한이
 * 대략 30~40개다. 60을 넘어가면 pill 끼리 서로를 가려 **읽을 수 있는 가격이 오히려 줄어든다**
 * (읽히지 않는 정보는 표시한 것이 아니다).
 */
export const DENSITY_LIMIT = 60;

/** 이 줌부터 단지명을 함께 보여준다. 우리 zoom 규약은 **클수록 확대**(카카오 level 의 반대). */
export const DETAIL_ZOOM = 16;

/**
 * 이번 화면 전체의 기본 표현 단계.
 * 밀집이 줌보다 우선한다 — 확대해도 그 안에 단지가 빽빽하면 pill 은 여전히 서로를 가린다.
 */
export function baseTier(zoom: number, count: number): MarkerTier {
  if (count > DENSITY_LIMIT) return "dot";
  if (zoom >= DETAIL_ZOOM) return "detail";
  return "price";
}

export interface MarkerEmphasis {
  /** 사용자가 지금 고른 단지 */
  selected?: boolean;
  /** 목록에서 마우스를 올린 단지(양방향 동기화) */
  hovered?: boolean;
  /** AI 추천 순위. 있으면 근거가 붙은 마커다. */
  rank?: number;
  /** 시세 데이터가 있는가. 없으면 pill 에 쓸 숫자 자체가 없다. */
  hasPrice?: boolean;
}

/**
 * 마커 **하나**의 표현 단계.
 *
 * 규칙 "확신의 농도" = 근거의 강도가 시각적 강도다. 그래서 강등에 예외를 둔다.
 *  - **선택**: 항상 상세. 사용자가 방금 지목한 대상까지 점으로 만들면 조작이 끊긴다.
 *  - **추천 순위**: 근거(리포트)가 붙은 소수의 후보다. 최소한 가격은 보여준다.
 *  - **hover**: 목록에서 가리키는 중 — 지도에서 그 값을 확인하려는 동작이므로 가격을 되살린다.
 *  - **시세 없음**: 보여줄 숫자가 없다. "데이터 없음" pill 로 자리만 차지하느니 점으로 둔다
 *    (사라지는 게 아니다 — 점은 그대로 있고, 탭하면 목록·상세에서 '데이터 없음'을 명시한다).
 */
export function tierFor(base: MarkerTier, e: MarkerEmphasis = {}): MarkerTier {
  if (e.selected) return "detail";
  if (e.rank || e.hovered) return base === "dot" ? "price" : base;
  if (e.hasPrice === false) return "dot";
  return base;
}

/**
 * 강등됐을 때 **무엇을 줄였는지** 밝히는 한 줄. 조용히 줄이면 그건 숨긴 것이다.
 * 강등이 아니면 null — 할 말이 없을 때 말하지 않는 것도 규칙이다(소란 떨지 않는다).
 */
export function densityNotice(tier: MarkerTier, count: number): string | null {
  if (tier !== "dot" || count <= 0) return null;
  return `단지 ${count.toLocaleString("ko-KR")}곳 — 가격은 확대하거나 목록에서 볼 수 있습니다`;
}
