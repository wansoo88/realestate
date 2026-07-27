/**
 * 태그 판정 — 이 파일이 지키는 단 하나의 계약: **모름은 아님이 아니다.**
 *
 * 세대수 미확보가 수도권 아파트의 16.2% 다. 그걸 "대단지 아님"으로 접으면
 * 2,666개 단지가 조용히 사라지고, 화면은 "여긴 대단지가 없다"고 거짓 단언을 한다.
 */
import { describe, expect, it } from "vitest";
import type { ComplexItem, RecommendationItem } from "../api/client";
import {
  LARGE_COMPLEX_MIN_HOUSEHOLDS,
  NEAR_STATION_MAX_M,
  TAG_DEFS,
  complexTagFacts,
  recommendationTagFacts,
  tagDef,
  tagVerdict,
  tagsOf,
  unknownTagsOf,
} from "./tags";

describe("대단지 — 1,000세대 이상", () => {
  it("경계값 1,000세대는 대단지다(이상)", () => {
    expect(tagVerdict("large_complex", { households: 1000 })).toBe("yes");
    expect(tagVerdict("large_complex", { households: 999 })).toBe("no");
    expect(tagVerdict("large_complex", { households: 1001 })).toBe("yes");
  });

  it("기준 상수를 바꾸면 판정도 함께 바뀐다(숫자를 두 곳에 적지 않았다)", () => {
    expect(tagVerdict("large_complex", { households: LARGE_COMPLEX_MIN_HOUSEHOLDS })).toBe("yes");
    expect(tagVerdict("large_complex", { households: LARGE_COMPLEX_MIN_HOUSEHOLDS - 1 })).toBe("no");
  });

  it("세대수를 모르면 **모름**이다 — '대단지 아님'으로 접지 않는다", () => {
    expect(tagVerdict("large_complex", { households: null })).toBe("unknown");
    expect(tagVerdict("large_complex", {})).toBe("unknown");
    expect(tagVerdict("large_complex", { households: undefined })).toBe("unknown");
  });

  it("0세대·음수·NaN 은 데이터 오류지 '작은 단지'가 아니다 → 모름", () => {
    expect(tagVerdict("large_complex", { households: 0 })).toBe("unknown");
    expect(tagVerdict("large_complex", { households: -5 })).toBe("unknown");
    expect(tagVerdict("large_complex", { households: Number.NaN })).toBe("unknown");
  });
});

describe("역세권 — 직선 500m 이내", () => {
  it("경계값 500m 는 역세권이다(이내)", () => {
    expect(tagVerdict("near_station", { stationDistanceM: 500 })).toBe("yes");
    expect(tagVerdict("near_station", { stationDistanceM: 501 })).toBe("no");
  });

  it("기준 상수를 따른다", () => {
    expect(tagVerdict("near_station", { stationDistanceM: NEAR_STATION_MAX_M })).toBe("yes");
    expect(tagVerdict("near_station", { stationDistanceM: NEAR_STATION_MAX_M + 0.1 })).toBe("no");
  });

  it("0m 는 유효한 값이다(역 바로 위) — 모름이 아니다", () => {
    expect(tagVerdict("near_station", { stationDistanceM: 0 })).toBe("yes");
  });

  it("거리를 모르면 모름", () => {
    expect(tagVerdict("near_station", {})).toBe("unknown");
    expect(tagVerdict("near_station", { stationDistanceM: null })).toBe("unknown");
    expect(tagVerdict("near_station", { stationDistanceM: -1 })).toBe("unknown");
  });
});

describe("재건축 — 정비사업 진행 중", () => {
  it("true/false/모름을 구분한다", () => {
    expect(tagVerdict("redevelopment", { redevelopment: true })).toBe("yes");
    expect(tagVerdict("redevelopment", { redevelopment: false })).toBe("no");
    expect(tagVerdict("redevelopment", { redevelopment: null })).toBe("unknown");
    expect(tagVerdict("redevelopment", {})).toBe("unknown");
  });
});

describe("tagsOf / unknownTagsOf", () => {
  it("확실한 것만 태그가 된다 — 모름은 배지가 되지 않는다", () => {
    const facts = { households: 1200, stationDistanceM: null };
    expect(tagsOf(facts)).toEqual(["large_complex"]);
    // 모르는 것은 태그가 아니라 '모름' 목록으로 간다
    expect(unknownTagsOf(facts)).toEqual(["near_station", "redevelopment"]);
  });

  it("한 단지가 여러 태그를 동시에 가질 수 있다(섹션 분할이 아니라 태그인 이유)", () => {
    expect(tagsOf({ households: 2000, stationDistanceM: 300, redevelopment: true })).toEqual([
      "large_complex",
      "near_station",
      "redevelopment",
    ]);
  });

  it("사실이 하나도 없으면 태그도 하나도 없다(지어내지 않는다)", () => {
    expect(tagsOf({})).toEqual([]);
  });
});

describe("학군 태그는 이번 라운드에 없다", () => {
  it("학업성취도 데이터가 없으므로 학군 태그를 정의하지 않았다", () => {
    // 거리만으로 '학군지'라 부르면 과장이다. 데이터가 들어오면 TAG_DEFS 에 추가한다.
    expect(TAG_DEFS.map((t) => t.id)).toEqual([
      "large_complex",
      "near_station",
      "redevelopment",
    ]);
  });

  it("모든 태그는 아이콘·라벨·기준 문구를 갖는다(색만으로 구분하지 않기 위해)", () => {
    for (const def of TAG_DEFS) {
      expect(def.icon.length).toBeGreaterThan(0);
      expect(def.label.length).toBeGreaterThan(0);
      expect(def.criterion.length).toBeGreaterThan(0);
      expect(tagDef(def.id)).toBe(def);
    }
  });

  it("기준 문구에 실제 임계값이 들어 있다(문구와 코드가 어긋나지 않게)", () => {
    expect(tagDef("large_complex").criterion).toContain("1,000");
    expect(tagDef("near_station").criterion).toContain(String(NEAR_STATION_MAX_M));
  });
});

describe("API 응답 → 사실값", () => {
  const complex: ComplexItem = {
    id: 1,
    name: "가나아파트",
    point: [127, 37.5],
    households: 1500,
    built_year: 2005,
    recent_price_krw: 1_000_000_000,
    price_as_of: "2026-06-30",
    price_confidence: "estimated",
    active_listings: 1,
    over_budget: false,
  };

  it("지도 응답의 세대수를 그대로 읽는다", () => {
    expect(complexTagFacts(complex)).toEqual({
      households: 1500,
      stationDistanceM: undefined,
      redevelopment: undefined,
    });
  });

  it("서버가 역 거리를 안 실으면 역세권 판정은 모름이다(추측하지 않는다)", () => {
    expect(tagVerdict("near_station", complexTagFacts(complex))).toBe("unknown");
    expect(tagsOf(complexTagFacts(complex))).toEqual(["large_complex"]);
  });

  it("서버가 실어 주면 그때부터 판정된다", () => {
    const facts = complexTagFacts({
      ...complex,
      nearest_station: { distance_m: 420, basis: "straight_line" },
      redevelopment: { available: true, stage: "사업시행인가" },
    });
    expect(tagsOf(facts)).toEqual(["large_complex", "near_station", "redevelopment"]);
    expect(unknownTagsOf(facts)).toEqual([]);
  });

  it("추천 응답은 항목 최상위의 사실값을 본다(complex 안이 아니다)", () => {
    const item = {
      complex: { id: 7, name: "다라" },
      total_households: 900,
      nearest_station: { name: "다라역", distance_m: 200, basis: "straight_line" },
    } as RecommendationItem;
    expect(recommendationTagFacts(item)).toEqual({
      households: 900,
      stationDistanceM: 200,
      redevelopment: undefined,
    });
    expect(tagsOf(recommendationTagFacts(item))).toEqual(["near_station"]);
  });

  it("추천 응답에 필드가 없으면 태그가 하나도 안 붙는다", () => {
    const item = { complex: { id: 7, name: "다라" } } as RecommendationItem;
    expect(tagsOf(recommendationTagFacts(item))).toEqual([]);
    expect(unknownTagsOf(recommendationTagFacts(item))).toHaveLength(TAG_DEFS.length);
  });

  /**
   * 서버 계약에서 `available === false` 는 **"정비사업이 없다"가 아니라 "확인되지 않았다"** 다
   * (구역 매칭 실패 · 경기도 미수집). 이걸 "아님"으로 옮기면 없는 사실을 단정하게 된다.
   */
  it("정비사업 미확인(available=false)을 '재건축 아님'으로 바꾸지 않는다", () => {
    const facts = complexTagFacts({
      ...complex,
      redevelopment: { available: false, missing: ["매칭된 구역 없음"] },
    });
    expect(facts.redevelopment).toBeUndefined();
    expect(tagVerdict("redevelopment", facts)).toBe("unknown");
    expect(unknownTagsOf(facts)).toContain("redevelopment");
  });

  it("구역이 확인되면 단계를 분류하지 못했어도 재건축 태그를 단다", () => {
    // available=true 는 '구역이 확인됨'이다 — 단계 미분류는 태그와 별개다
    const facts = complexTagFacts({
      ...complex,
      redevelopment: { available: true, stage: "unknown", raw_stage: "조합설립추진" },
    });
    expect(tagVerdict("redevelopment", facts)).toBe("yes");
  });
});
