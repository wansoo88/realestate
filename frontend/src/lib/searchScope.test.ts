/**
 * 검색 범위 — **요청에 실리는 것**과 **화면에 적히는 것**이 같은 상태에서 나오는지 못박는다.
 * 갈라지면 화면은 "이 주변에서 찾는 중"이라고 말하고 서버는 전체를 뒤진다.
 */
import { describe, expect, it } from "vitest";
import {
  appliedScope,
  intersectionNote,
  regionNames,
  scopeFields,
  scopeText,
} from "./searchScope";

const BBOX = "126.9,37.4,127.0,37.6";

describe("scopeFields — 실제로 나가는 필드", () => {
  it("bbox 만 있으면 bbox 를 싣는다", () => {
    expect(scopeFields({ regionCodes: [], bbox: BBOX })).toEqual({
      region_codes: [],
      bbox: BBOX,
    });
  });

  it("시군구와 함께 있으면 **둘 다** 싣는다(서버가 교집합으로 좁힌다)", () => {
    expect(scopeFields({ regionCodes: ["11680"], bbox: BBOX })).toEqual({
      region_codes: ["11680"],
      bbox: BBOX,
    });
  });

  it("이 주변을 안 쓰면 bbox 키 자체가 없다(빈 문자열·null 을 보내지 않는다)", () => {
    const fields = scopeFields({ regionCodes: ["11680"], bbox: null });
    expect(fields).toEqual({ region_codes: ["11680"] });
    expect("bbox" in fields).toBe(false);
  });

  it("형식이 깨진 bbox 는 보내지 않는다 — 422 를 자초하지 않는다", () => {
    expect("bbox" in scopeFields({ regionCodes: [], bbox: "bad" })).toBe(false);
    expect("bbox" in scopeFields({ regionCodes: [], bbox: "127.0,37.4,126.9,37.6" })).toBe(false);
  });
});

describe("appliedScope — 화면 표기는 보낸 것과 같아야 한다", () => {
  it("보내지 못한 bbox 는 표기에서도 빠진다", () => {
    expect(appliedScope({ regionCodes: ["11680"], bbox: "bad" })).toEqual({
      regionCodes: ["11680"],
      bbox: null,
    });
  });

  it("보낸 값은 그대로 남는다", () => {
    expect(appliedScope({ regionCodes: [], bbox: BBOX })).toEqual({
      regionCodes: [],
      bbox: BBOX,
    });
  });
});

describe("regionNames", () => {
  it("코드가 아니라 이름으로 보여준다", () => {
    expect(regionNames(["11680"])).toBe("서울 강남구");
    expect(regionNames(["11680", "41135"])).toBe("서울 강남구 · 경기 성남시 분당구");
  });

  it("셋 이상은 '외 N곳'으로 줄인다", () => {
    expect(regionNames(["11680", "41135", "11650"])).toBe("서울 강남구 외 2곳");
  });

  it("모르는 코드는 이름을 지어내지 않고 코드를 보여준다", () => {
    expect(regionNames(["99999"])).toBe("99999");
  });

  it("비어 있으면 빈 문자열", () => {
    expect(regionNames([])).toBe("");
  });
});

describe("scopeText — 지금 어디에서 찾는가", () => {
  it("아무 조건도 없으면 전체라고 말한다", () => {
    expect(scopeText({ regionCodes: [], bbox: null })).toBe("수도권 전체");
  });

  it("이 주변만이면 크기를 함께 적는다(좌표는 사람이 못 읽는다)", () => {
    expect(scopeText({ regionCodes: [], bbox: BBOX })).toBe("이 주변(약 8.8 × 22km)");
  });

  it("시군구만이면 지역 이름만 적는다", () => {
    expect(scopeText({ regionCodes: ["11680"], bbox: null })).toBe("서울 강남구");
  });

  it("둘 다면 교집합 기호로 잇는다(나열하면 합집합으로 읽힌다)", () => {
    expect(scopeText({ regionCodes: ["11680"], bbox: BBOX })).toBe(
      "이 주변(약 8.8 × 22km) ∩ 서울 강남구",
    );
  });

  it("보낼 수 없는 bbox 는 범위 문구에도 나타나지 않는다", () => {
    expect(scopeText({ regionCodes: ["11680"], bbox: "bad" })).toBe("서울 강남구");
  });
});

describe("intersectionNote", () => {
  it("둘 다 걸렸을 때만 교집합을 설명한다", () => {
    expect(intersectionNote({ regionCodes: ["11680"], bbox: BBOX })).toMatch(/교집합/);
  });

  it("한쪽만이면 설명하지 않는다(없는 조건을 설명하면 오해가 된다)", () => {
    expect(intersectionNote({ regionCodes: [], bbox: BBOX })).toBeNull();
    expect(intersectionNote({ regionCodes: ["11680"], bbox: null })).toBeNull();
  });
});
