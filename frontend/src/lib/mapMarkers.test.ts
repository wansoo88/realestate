// @vitest-environment jsdom
/**
 * 지도 마커 로직 테스트 (FE-2) — 카카오 SDK 를 목으로 주입한다(브라우저 전용이라 실제 로드 불가).
 * 검증: 마커/군집 오버레이 생성·정리, 탭·키보드 → 선택 콜백, 그리고 **XSS 안전성**.
 */
import { describe, expect, it, vi } from "vitest";
import type { ClusterItem, ComplexItem } from "../api/client";
import {
  MarkerLayer,
  buildLabelEl,
  clusterMarkerLines,
  complexMarkerText,
  type KakaoLike,
} from "./mapMarkers";

function mockKakao() {
  const overlays: Array<{ opts: any; setMapCalls: unknown[] }> = [];
  class LatLng {
    constructor(public lat: number, public lng: number) {}
  }
  class CustomOverlay {
    opts: any;
    setMapCalls: unknown[] = [];
    constructor(opts: any) {
      this.opts = opts;
      overlays.push(this);
    }
    setMap(m: unknown) {
      this.setMapCalls.push(m);
    }
  }
  const kakao = { maps: { LatLng, CustomOverlay } } as unknown as KakaoLike;
  return { kakao, overlays };
}

function complex(id: number): ComplexItem {
  return {
    id,
    name: `단지${id}`,
    point: [127.0 + id * 0.01, 37.5],
    households: 100,
    built_year: 2010,
    recent_price_krw: 1_480_000_000,
    price_as_of: "2026-06-30",
    price_confidence: "estimated",
    active_listings: 1,
    over_budget: false,
  };
}

function cluster(code: string, count: number): ClusterItem {
  return { region_code: code, count, center: [127.0, 37.5], median_price_krw: 1_500_000_000 };
}

describe("complexMarkerText", () => {
  it("추정치는 '추정' 접두로 확정치와 구분한다", () => {
    expect(complexMarkerText(complex(1))).toBe("추정 14.8억");
  });

  it("가격이 없으면 0원이 아니라 '데이터 없음'", () => {
    expect(
      complexMarkerText({ ...complex(1), recent_price_krw: null, price_confidence: "unknown" }),
    ).toBe("데이터 없음");
  });
});

describe("clusterMarkerLines", () => {
  it("개수를 첫 줄(주인공)로, 중위가를 둘째 줄로 둔다", () => {
    expect(clusterMarkerLines(cluster("1168000000", 342))).toEqual(["342", "중위 15.0억"]);
  });
});

describe("buildLabelEl — XSS 안전", () => {
  it("서버 문자열을 HTML 로 해석하지 않는다(textContent 만 사용)", () => {
    const el = buildLabelEl(document, "x", ["청담<img src=x onerror=alert(1)>(103)"]);
    // 태그가 실제 요소로 만들어지면 안 된다
    expect(el.querySelector("img")).toBeNull();
    // 원문은 텍스트로 그대로 남는다
    expect(el.textContent).toContain("<img");
  });
});

describe("MarkerLayer.setComplexes", () => {
  it("단지 수만큼 오버레이를 만들어 지도에 올린다", () => {
    const { kakao, overlays } = mockKakao();
    const map = { panTo: vi.fn() };
    const layer = new MarkerLayer({ kakao, map, doc: document });

    layer.setComplexes([complex(1), complex(2), complex(3)], {});

    expect(overlays.length).toBe(3);
    expect(overlays[0].setMapCalls).toContain(map);
  });

  it("마커 탭 → onSelect(id) 호출 (바텀시트 연동)", () => {
    const { kakao, overlays } = mockKakao();
    const layer = new MarkerLayer({ kakao, map: { panTo: vi.fn() }, doc: document });
    const onSelect = vi.fn();

    layer.setComplexes([complex(1), complex(2)], { onSelect });
    (overlays[1].opts.content as HTMLElement).dispatchEvent(
      new MouseEvent("click", { bubbles: true }),
    );

    expect(onSelect).toHaveBeenCalledWith(2);
  });

  it("키보드(Enter)로도 선택된다", () => {
    const { kakao, overlays } = mockKakao();
    const layer = new MarkerLayer({ kakao, map: { panTo: vi.fn() }, doc: document });
    const onSelect = vi.fn();

    layer.setComplexes([complex(5)], { onSelect });
    (overlays[0].opts.content as HTMLElement).dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
    );

    expect(onSelect).toHaveBeenCalledWith(5);
  });

  it("선택된 단지는 파란 채움 클래스 + 지도 이동(panTo)", () => {
    const { kakao, overlays } = mockKakao();
    const map = { panTo: vi.fn() };
    const layer = new MarkerLayer({ kakao, map, doc: document });

    layer.setComplexes([complex(1), complex(2)], { selectedId: 2 });

    expect(map.panTo).toHaveBeenCalledTimes(1);
    const selected = overlays.find((o) =>
      (o.opts.content as HTMLElement).className.includes("map-pill--selected"),
    );
    expect(selected).toBeTruthy();
  });

  it("CR18-1 회귀 — 같은 selectedId 로 다시 그려도 panTo 는 1회뿐이다(지도 되감김 방지)", () => {
    // 실제 증상: 마커를 탭한 뒤 지도를 끌면 idle→조회→setItems→다시 그리기 가 반복되는데,
    // 그릴 때마다 panTo 하면 지도가 선택 단지로 되감긴다(그리고 idle 이 또 발생해 조회 2배).
    const { kakao } = mockKakao();
    const map = { panTo: vi.fn() };
    const layer = new MarkerLayer({ kakao, map, doc: document });

    // 조회 결과가 매번 새 배열로 오는 상황(App 의 setItems)을 그대로 재현한다.
    layer.setComplexes([complex(7), complex(8)], { selectedId: 7 });
    layer.setComplexes([complex(7), complex(8)], { selectedId: 7 });
    layer.setComplexes([complex(7), complex(9)], { selectedId: 7 });

    expect(map.panTo).toHaveBeenCalledTimes(1);
  });

  it("선택이 바뀌면 그때는 다시 panTo 한다(리스트→지도 동기화는 유지)", () => {
    const { kakao } = mockKakao();
    const map = { panTo: vi.fn() };
    const layer = new MarkerLayer({ kakao, map, doc: document });

    layer.setComplexes([complex(1), complex(2)], { selectedId: 1 });
    layer.setComplexes([complex(1), complex(2)], { selectedId: 2 });

    expect(map.panTo).toHaveBeenCalledTimes(2);
  });

  it("선택을 해제했다가 같은 단지를 다시 고르면 이동한다", () => {
    const { kakao } = mockKakao();
    const map = { panTo: vi.fn() };
    const layer = new MarkerLayer({ kakao, map, doc: document });

    layer.setComplexes([complex(3)], { selectedId: 3 });
    layer.setComplexes([complex(3)], { selectedId: null });
    layer.setComplexes([complex(3)], { selectedId: 3 });

    expect(map.panTo).toHaveBeenCalledTimes(2);
  });

  it("선택 없이 그리면 지도를 움직이지 않는다", () => {
    const { kakao } = mockKakao();
    const map = { panTo: vi.fn() };
    const layer = new MarkerLayer({ kakao, map, doc: document });

    layer.setComplexes([complex(1), complex(2)], {});

    expect(map.panTo).not.toHaveBeenCalled();
  });

  it("빈 배열로 다시 그리면 이전 마커를 지도에서 제거한다", () => {
    const { kakao, overlays } = mockKakao();
    const layer = new MarkerLayer({ kakao, map: { panTo: vi.fn() }, doc: document });

    layer.setComplexes([complex(1)], {});
    const first = overlays[0];
    layer.setComplexes([], {});

    expect(first.setMapCalls).toContain(null); // setMap(null) 로 떼어냄
  });
});

describe("CR18-5 회귀 — 좌표 순서 (경도·위도 뒤집힘 방지)", () => {
  // 우리 API 계약(api-spec)의 point/center 는 GeoJSON 과 같은 **[경도, 위도]** 순서다.
  // 카카오 LatLng 생성자는 반대로 **(위도, 경도)**. 한 번만 뒤집히면 마커가 태평양 어딘가에
  // 찍히는데 지도는 멀쩡히 렌더되므로 눈에 잘 안 띈다 → 테스트로 못박는다.
  const LNG = 127.0276; // 서울(강남) 경도 — 위도(37.x)보다 크다
  const LAT = 37.4979;

  it("단지 마커: [경도,위도] → LatLng(위도, 경도)", () => {
    const { kakao, overlays } = mockKakao();
    const layer = new MarkerLayer({ kakao, map: { panTo: vi.fn() }, doc: document });

    layer.setComplexes([{ ...complex(1), point: [LNG, LAT] }], {});

    const pos = overlays[0].opts.position as { lat: number; lng: number };
    expect(pos.lat).toBe(LAT);
    expect(pos.lng).toBe(LNG);
  });

  it("panTo 대상도 같은 규약을 따른다", () => {
    const { kakao } = mockKakao();
    const map = { panTo: vi.fn() };
    const layer = new MarkerLayer({ kakao, map, doc: document });

    layer.setComplexes([{ ...complex(4), point: [LNG, LAT] }], { selectedId: 4 });

    const target = map.panTo.mock.calls[0][0] as { lat: number; lng: number };
    expect(target.lat).toBe(LAT);
    expect(target.lng).toBe(LNG);
  });

  it("군집 중심: [경도,위도] → LatLng(위도, 경도)", () => {
    const { kakao, overlays } = mockKakao();
    const layer = new MarkerLayer({ kakao, map: { panTo: vi.fn() }, doc: document });

    layer.setClusters([{ ...cluster("1168000000", 10), center: [LNG, LAT] }]);

    const pos = overlays[0].opts.position as { lat: number; lng: number };
    expect(pos.lat).toBe(LAT);
    expect(pos.lng).toBe(LNG);
  });
});

describe("MarkerLayer.setClusters", () => {
  it("군집 수만큼 오버레이를 만들고, 탭하면 콜백을 호출한다", () => {
    const { kakao, overlays } = mockKakao();
    const layer = new MarkerLayer({ kakao, map: { panTo: vi.fn() }, doc: document });
    const onCluster = vi.fn();

    layer.setClusters([cluster("1168000000", 342), cluster("1150000000", 100)], onCluster);
    expect(overlays.length).toBe(2);

    (overlays[0].opts.content as HTMLElement).dispatchEvent(
      new MouseEvent("click", { bubbles: true }),
    );
    expect(onCluster).toHaveBeenCalledTimes(1);
  });
});
