/**
 * 시군구 목록·검색.
 *
 * 이 목록은 `config/regions_capital.yaml`(행정안전부 법정동코드)에서 옮긴 것이고,
 * 5자리 코드는 서버가 `complex.region_code`(10자리)와 **접두 매칭**하는 값이다.
 * 코드가 한 자리라도 틀리면 후보가 조용히 0건이 된다 — 형식을 여기서 못박는다.
 */
import { describe, expect, it } from "vitest";
import { REGIONS, SIDO_ORDER, regionByCode, regionLabel, searchRegions } from "./regions";

describe("목록 형식", () => {
  it("수도권 91개 시군구를 모두 담는다", () => {
    expect(REGIONS.length).toBe(91);
  });

  it("코드는 5자리 숫자다(서버가 접두 매칭에 쓰는 형식)", () => {
    for (const r of REGIONS) expect(r.code).toMatch(/^\d{5}$/);
  });

  it("코드가 중복되지 않는다(체크박스 키·선택 상태가 엉킨다)", () => {
    expect(new Set(REGIONS.map((r) => r.code)).size).toBe(REGIONS.length);
  });

  it("시도 접두가 서울 11 · 경기 41 · 인천 28 규약을 따른다", () => {
    const prefix = { 서울: "11", 경기: "41", 인천: "28" } as const;
    for (const r of REGIONS) expect(r.code.startsWith(prefix[r.sido])).toBe(true);
    expect(SIDO_ORDER).toEqual(["서울", "경기", "인천"]);
  });
});

describe("regionLabel", () => {
  it("시도를 붙인다 — '중구'만으로는 서울인지 인천인지 알 수 없다", () => {
    const seoulJung = REGIONS.find((r) => r.sido === "서울" && r.name === "중구");
    expect(seoulJung).toBeTruthy();
    expect(regionLabel(seoulJung!)).toBe("서울 중구");
  });
});

describe("regionByCode", () => {
  it("코드로 되찾는다(선택 칩이 이름을 그릴 때)", () => {
    expect(regionByCode("11680")?.name).toBe("강남구");
    expect(regionByCode("00000")).toBeUndefined();
  });
});

describe("searchRegions", () => {
  it("부분 문자열로 찾는다", () => {
    expect(searchRegions("분당").map((r) => r.code)).toEqual(["41135"]);
  });

  it("띄어 쓴 검색이 걸린다 — '성남 분당' → 성남시 분당구", () => {
    // 이름 중간에 '시'가 끼어 있어 단순 부분일치로는 0건이었다(첫 구현의 실제 버그).
    expect(searchRegions("성남 분당").map((r) => r.code)).toEqual(["41135"]);
    expect(searchRegions("  분당  ").map((r) => r.code)).toEqual(["41135"]);
  });

  it("붙여 쓴 검색도 걸린다('서울강남' → 서울 강남구)", () => {
    expect(searchRegions("서울강남").map((r) => r.name)).toEqual(["강남구"]);
  });

  it("토큰이 여러 개면 **모두** 들어 있어야 한다(아무거나 걸리면 검색이 무의미해진다)", () => {
    expect(searchRegions("성남 없는말")).toEqual([]);
  });

  it("빈 검색어는 전체를 그대로 준다", () => {
    expect(searchRegions("")).toHaveLength(REGIONS.length);
    expect(searchRegions("   ")).toHaveLength(REGIONS.length);
  });

  it("주어진 후보 안에서만 찾는다(시도 탭과 검색을 겹쳐 쓴다)", () => {
    const incheon = REGIONS.filter((r) => r.sido === "인천");
    expect(searchRegions("구", incheon).every((r) => r.sido === "인천")).toBe(true);
  });

  it("없는 이름은 빈 결과", () => {
    expect(searchRegions("없는동네")).toEqual([]);
  });
});
