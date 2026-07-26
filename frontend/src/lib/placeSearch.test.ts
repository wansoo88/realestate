// @vitest-environment jsdom
/**
 * 장소·역 검색.
 *
 * 못박는 것 두 가지:
 *  ① **좌표 순서** — 카카오는 x=경도 / y=위도. 한 번만 뒤집혀도 지도가 태평양으로 간다(CR18-5).
 *  ② **실패를 삼키지 않는다** — SDK 가 없거나(CSP 차단 포함) 결과가 0건이면 그 사실을 돌려준다.
 */
import { afterEach, describe, expect, it } from "vitest";
import { installKakaoStub, type KakaoStubHandle } from "../test/kakaoStub";
import { getServices, placeErrorText, searchPlaces, toPlace } from "./placeSearch";

let kakao: KakaoStubHandle | null = null;

afterEach(() => {
  kakao?.restore();
  kakao = null;
});

const GANGNAM = {
  id: "21160988",
  place_name: "강남역 2호선",
  address_name: "서울 강남구 역삼동 858",
  road_address_name: "서울 강남구 강남대로 396",
  x: "127.027926",
  y: "37.497175",
};

describe("toPlace — 좌표 순서(CR18-5)", () => {
  it("x=경도 · y=위도를 우리 규약 [경도, 위도] 로 옮긴다", () => {
    const p = toPlace(GANGNAM);
    expect(p?.point[0]).toBeCloseTo(127.027926, 6); // 경도가 먼저
    expect(p?.point[1]).toBeCloseTo(37.497175, 6);
  });

  it("도로명이 있으면 도로명을, 없으면 지번을 보조 설명으로 쓴다", () => {
    expect(toPlace(GANGNAM)?.detail).toBe("서울 강남구 강남대로 396");
    expect(toPlace({ ...GANGNAM, road_address_name: "" })?.detail).toContain("역삼동");
  });

  it("좌표나 이름이 깨진 행은 버린다(지도를 0,0 으로 보내지 않는다)", () => {
    expect(toPlace({ ...GANGNAM, x: "" })).toBeNull();
    expect(toPlace({ ...GANGNAM, place_name: "" })).toBeNull();
  });
});

describe("searchPlaces", () => {
  it("SDK 가 없으면 'unavailable' — 조용히 빈 결과로 넘기지 않는다", async () => {
    // CSP 차단·스크립트 로드 실패에서 실제로 생기는 상태다.
    expect(getServices()).toBeNull();
    const res = await searchPlaces("강남역");
    expect(res.error).toBe("unavailable");
    expect(res.places).toEqual([]);
  });

  it("결과를 우리 타입으로 정규화해 돌려준다", async () => {
    kakao = installKakaoStub({ places: { status: "OK", rows: [GANGNAM] } });

    const res = await searchPlaces("강남역");

    expect(res.error).toBeNull();
    expect(res.places[0].name).toBe("강남역 2호선");
    expect(res.places[0].point[0]).toBeCloseTo(127.0279, 3);
  });

  it("0건이면 'empty' 로 알린다", async () => {
    kakao = installKakaoStub({ places: { status: "ZERO_RESULT", rows: [] } });
    expect((await searchPlaces("없는역")).error).toBe("empty");
  });

  it("SDK 오류는 'failed' 로 알린다", async () => {
    kakao = installKakaoStub({ places: { status: "ERROR", rows: [] } });
    expect((await searchPlaces("강남역")).error).toBe("failed");
  });

  it("빈 검색어로는 아예 부르지 않는다", async () => {
    kakao = installKakaoStub({ places: { status: "OK", rows: [GANGNAM] } });
    const res = await searchPlaces("   ");
    expect(res.places).toEqual([]);
    expect(res.error).toBeNull();
  });

  it("결과 수를 제한한다(목록이 지도를 덮지 않게)", async () => {
    kakao = installKakaoStub({
      places: { status: "OK", rows: Array.from({ length: 15 }, () => GANGNAM) },
    });
    expect((await searchPlaces("강남역", 5)).places).toHaveLength(5);
  });
});

describe("placeErrorText", () => {
  it("실패마다 다른 말을 한다(무슨 일이 났는지 알 수 있게)", () => {
    expect(placeErrorText("unavailable")).toContain("사용할 수 없습니다");
    expect(placeErrorText("empty")).toContain("검색 결과가 없습니다");
    expect(placeErrorText("failed")).toContain("실패");
  });
});
