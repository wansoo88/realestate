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
  delete (window as unknown as { kakao?: unknown }).kakao;
});

/**
 * `keywordSearch` 가 콜백을 **어떻게 부르는지**만 우리가 정하는 최소 services.
 * 카카오 SDK 는 성공/실패에서 인자 모양이 달라서, 그 모양 자체가 검증 대상이다.
 */
function installServices(invoke: (cb: (...args: unknown[]) => void) => void): void {
  (window as unknown as { kakao: unknown }).kakao = {
    maps: {
      services: {
        Places: class {
          keywordSearch(_kw: string, cb: (...args: unknown[]) => void) {
            invoke(cb);
          }
        },
        Status: { OK: "OK", ZERO_RESULT: "ZERO_RESULT", ERROR: "ERROR" },
      },
    },
  };
}

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

  /**
   * 실패 경로의 **인자 모양**을 못박는다.
   *
   * 카카오 services.js 1.1.1 은 실패하면 `cb("ERROR", null, null)` 로 부른다 —
   * 성공(`cb(documents, "OK", pagination)`)과 달리 인자가 한 칸씩 밀린다.
   * 도메인 미등록이면 검색 XHR 이 401 로 돌아오고 SDK 가 정확히 이 형태로 콜백한다.
   */
  it("실패는 인자가 밀려서 온다 — cb('ERROR', null, null) 을 그대로 받아낸다", async () => {
    const seen: unknown[][] = [];
    installServices((cb) => {
      const args = ["ERROR", null, null];
      seen.push(args);
      cb(...args);
    });

    const res = await searchPlaces("강남역");

    expect(seen[0]).toEqual(["ERROR", null, null]); // 실제 SDK 모양을 태웠다
    expect(res.error).toBe("failed");
    expect(res.places).toEqual([]);
  });

  /**
   * **멈추지 않는다** — 이게 이 파일에서 제일 중요한 성질이다.
   *
   * 실제 SDK 는 XHR 콜백에서 **비동기로** 부른다. 그래서 `searchPlaces` 안의 try/catch 는
   * 콜백에서 난 예외를 잡지 못한다. 배열이 아닌 값에 `.map` 을 걸어 TypeError 가 나면
   * Promise 는 이행도 거부도 되지 않고, 화면의 "찾는 중…" 버튼이 **영영 돌아오지 않는다**
   * (재검색도 못 한다). 그래서 어떤 모양이 와도 반드시 값으로 끝나야 한다.
   */
  it.each([
    ["실패 모양 그대로", ["ERROR", null, null]],
    ["status 만 OK 인 뒤틀린 모양", ["ERROR", "OK", null]],
    ["data 가 비어 있는 모양", [null, "OK", null]],
    ["아무것도 안 준 모양", [undefined, undefined, undefined]],
  ])("비동기로 %s 이 와도 멈추지 않고 실패로 끝난다", async (_label, args) => {
    installServices((cb) => {
      // 실제 SDK 와 같이 **비동기** — try/catch 밖에서 터지게 한다.
      setTimeout(() => cb(...(args as unknown[])), 0);
    });

    const res = await searchPlaces("강남역");

    expect(res.error).toBe("failed");
    expect(res.places).toEqual([]);
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

  /**
   * 이 실패의 실제 원인은 **카카오 콘솔 웹 도메인 미등록**이다(파일 머리말에 근거).
   * 그 상태에서는 몇 번을 다시 눌러도 되지 않는다 — "잠시 후 다시 시도"는 거짓말이고,
   * 사용자를 무한 재시도에 묶어 둔다. 고칠 수 있는 곳을 가리켜야 한다.
   */
  it("고칠 수 없는 실패를 '다시 시도하라'고 하지 않는다 — 할 일을 가리킨다", () => {
    const text = placeErrorText("failed");
    expect(text).not.toContain("다시 시도");
    expect(text).toContain("도메인");
  });
});
