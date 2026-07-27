/**
 * 단지 특성 태그 — **정의를 여기 한 곳에만 둔다.**
 *
 * 왜 한 곳인가
 * ------------
 * 태그는 "1,000세대 이상"처럼 **숫자 기준이 곧 의미**다. 기준이 화면마다 흩어지면
 * 목록의 배지와 칩의 개수가 조용히 어긋나고, 그 순간 화면이 거짓말을 한다.
 * 나중에 태그를 추가할 때(학군 등)도 이 파일 한 곳만 고치면 되도록 만든다.
 *
 * 세 가지 판정만 쓴다 — **yes / no / unknown**.
 * ⚠️ `unknown` 을 `no` 로 접지 않는다. 세대수 미확보가 전체의 16.2%(16,462건 중 2,666건)다.
 *    "모름"을 "대단지 아님"으로 취급하면 그 2,666건은 사용자가 영영 못 보게 되고,
 *    화면은 "이 지역엔 대단지가 없다"고 **거짓 단언**을 하게 된다.
 *
 * 학군 태그는 이번 라운드에 없다
 * ------------------------------
 * 학업성취도·학원가 데이터가 아직 없다. 배정 초등학교까지의 거리만으로 "학군지"라
 * 부르는 건 과장이다(거리가 가깝다 ≠ 좋은 학군). 학교알리미 학업성취도를 확보하면
 * 아래 `TAG_DEFS` 에 한 줄 추가하고 `tagVerdict` 에 분기 하나를 더하면 된다.
 * 그때까지 배정 초등학교 정보는 **리포트 근거에만** 남는다(태그로 승격하지 않는다).
 */
import type { ComplexItem, RecommendationItem } from "../api/client";

export type TagId = "large_complex" | "near_station" | "redevelopment";

/** 판정 결과. `unknown` 은 "아님"이 아니라 "모름"이다 — 둘을 섞는 순간 데이터가 유실된다. */
export type TagVerdict = "yes" | "no" | "unknown";

/* ── 기준값 (이 숫자가 태그의 정의다) ─────────────────────────────────────── */

/** 대단지: 1,000세대 이상. 수도권 아파트 16,462개 중 1,062개(6.5%)만 해당하는 엄격한 선. */
export const LARGE_COMPLEX_MIN_HOUSEHOLDS = 1000;

/**
 * 역세권: 최근접 역까지 **직선거리** 500m 이내.
 * 도보로는 6~7분. 직선거리라 실제 도보거리는 이보다 길다 — 화면에 그렇게 적는다.
 */
export const NEAR_STATION_MAX_M = 500;

export interface TagDef {
  id: TagId;
  /** 색만으로 구분되지 않게(A3) 아이콘·라벨을 항상 함께 쓴다. */
  icon: string;
  label: string;
  /** 판정 기준. 화면에 그대로 적어 "왜 이게 대단지인가"에 답한다. */
  criterion: string;
  /** 판정에 필요한 사실의 이름. 없을 때 **무엇이 없어서** 판정 못 했는지 말하는 데 쓴다. */
  factLabel: string;
}

export const TAG_DEFS: readonly TagDef[] = [
  {
    id: "large_complex",
    icon: "🏢",
    label: "대단지",
    criterion: `${LARGE_COMPLEX_MIN_HOUSEHOLDS.toLocaleString("ko-KR")}세대 이상`,
    factLabel: "세대수",
  },
  {
    id: "near_station",
    icon: "🚇",
    label: "역세권",
    criterion: `역까지 직선 ${NEAR_STATION_MAX_M}m 이내`,
    factLabel: "역 거리",
  },
  {
    id: "redevelopment",
    icon: "🔨",
    label: "재건축",
    // "진행 중"이라고 쓰지 않는다 — 서버가 확인해 주는 것은 **구역 매칭**까지다.
    // 단계는 분류되지 않을 수도 있어(raw_stage 만 있는 경우) 리포트가 따로 말한다.
    criterion: "정비사업 구역으로 확인됨",
    factLabel: "정비사업 확인",
  },
] as const;

export function tagDef(id: TagId): TagDef {
  const def = TAG_DEFS.find((t) => t.id === id);
  // 타입상 도달할 수 없다. 도달했다면 TAG_DEFS 와 TagId 가 어긋난 것이므로 조용히 넘기지 않는다.
  if (!def) throw new Error(`알 수 없는 태그: ${id}`);
  return def;
}

/**
 * 판정에 쓰는 **사실값만** 모은 구조.
 *
 * 전부 optional 인 이유: 서버가 아직 안 내려주는 필드가 있다. 없으면 `unknown` 이고,
 * `unknown` 이면 태그를 달지 않는다 — 값을 추측해 채우지 않는다.
 */
export interface TagFacts {
  /** 총 세대수. */
  households?: number | null;
  /** 최근접 역까지 직선거리(m). */
  stationDistanceM?: number | null;
  /**
   * 정비사업 구역이 **확인**되었는가.
   * `undefined` = 확인되지 않음(= 모름). 서버는 "없음"을 표현하지 않는다 —
   * 매칭 실패는 곧 미확인이기 때문이다(수집 범위: 서울·인천).
   */
  redevelopment?: boolean | null;
}

/** 세대수로 쓸 수 있는 값인가. 0·음수·NaN 은 데이터 오류지 "0세대"가 아니다 → 모름. */
function usableCount(v: number | null | undefined): v is number {
  return typeof v === "number" && Number.isFinite(v) && v > 0;
}

/** 거리로 쓸 수 있는 값인가. 음수·NaN 은 모름(0m 는 있을 수 있다 — 역 바로 위). */
function usableDistance(v: number | null | undefined): v is number {
  return typeof v === "number" && Number.isFinite(v) && v >= 0;
}

export function tagVerdict(id: TagId, facts: TagFacts): TagVerdict {
  switch (id) {
    case "large_complex":
      if (!usableCount(facts.households)) return "unknown";
      return facts.households >= LARGE_COMPLEX_MIN_HOUSEHOLDS ? "yes" : "no";
    case "near_station":
      if (!usableDistance(facts.stationDistanceM)) return "unknown";
      return facts.stationDistanceM <= NEAR_STATION_MAX_M ? "yes" : "no";
    case "redevelopment":
      if (facts.redevelopment === null || facts.redevelopment === undefined) return "unknown";
      return facts.redevelopment ? "yes" : "no";
  }
}

/** 이 단지가 **확실히 만족하는** 태그들. 모름은 들어가지 않는다(배지의 유일한 근거). */
export function tagsOf(facts: TagFacts): TagId[] {
  return TAG_DEFS.filter((t) => tagVerdict(t.id, facts) === "yes").map((t) => t.id);
}

/** 판정 자체가 불가능한 태그들. "무엇을 모르는지"를 화면이 말할 때 쓴다. */
export function unknownTagsOf(facts: TagFacts): TagId[] {
  return TAG_DEFS.filter((t) => tagVerdict(t.id, facts) === "unknown").map((t) => t.id);
}

/* ── API 응답 → 사실값 ────────────────────────────────────────────────────
 * 서버가 아직 안 싣는 필드는 `undefined` 로 남는다 = 모름. 좌표나 이름으로
 * 거리를 추측하지 않는다 — 지어낸 사실로 단 태그는 태그가 아니라 오류다. */

/**
 * `available === false` 를 "재건축 아님"으로 바꾸지 않는다.
 * 서버에서 false 는 **"확인되지 않았다"**(구역 매칭 실패 · 경기도 미수집)라서,
 * false 를 "아님"으로 옮기면 없는 사실을 단정하게 된다 → `undefined`(모름)로 남긴다.
 */
function redevelopmentFact(
  block: { available: boolean } | null | undefined,
): boolean | undefined {
  if (!block) return undefined;
  return block.available ? true : undefined;
}

export function complexTagFacts(c: ComplexItem): TagFacts {
  return {
    households: c.households,
    stationDistanceM: c.nearest_station?.distance_m,
    redevelopment: redevelopmentFact(c.redevelopment),
  };
}

export function recommendationTagFacts(item: RecommendationItem): TagFacts {
  return {
    households: item.total_households,
    stationDistanceM: item.nearest_station?.distance_m,
    redevelopment: redevelopmentFact(item.redevelopment),
  };
}
