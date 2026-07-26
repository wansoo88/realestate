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
  patchLabelEl,
  type KakaoLike,
} from "./mapMarkers";

function mockKakao() {
  const overlays: Array<{
    opts: any;
    setMapCalls: unknown[];
    zIndexCalls: number[];
    positionCalls: any[];
  }> = [];
  class LatLng {
    constructor(public lat: number, public lng: number) {}
  }
  // 실제 카카오 CustomOverlay 가 가진 API 를 그대로 흉내낸다(재사용 경로가 이걸 쓴다).
  class CustomOverlay {
    opts: any;
    setMapCalls: unknown[] = [];
    zIndexCalls: number[] = [];
    positionCalls: any[] = [];
    constructor(opts: any) {
      this.opts = opts;
      overlays.push(this);
    }
    setMap(m: unknown) {
      this.setMapCalls.push(m);
    }
    setZIndex(z: number) {
      this.zIndexCalls.push(z);
    }
    setPosition(p: unknown) {
      this.positionCalls.push(p);
    }
  }
  const kakao = { maps: { LatLng, CustomOverlay } } as unknown as KakaoLike;
  return { kakao, overlays };
}

/**
 * 계측용 Document — DOM 요소 생성 수와 addEventListener 호출 수를 센다(CR18-7).
 * "빨라졌다"가 아니라 **숫자로** 증명하려고 만든 것이다.
 */
function countingDoc() {
  let created = 0;
  let listeners = 0;
  const doc = {
    createElement(tag: string) {
      created += 1;
      const el = document.createElement(tag);
      const orig = el.addEventListener.bind(el);
      // 프로토타입이 아니라 인스턴스에만 씌워 다른 테스트에 영향을 주지 않는다.
      el.addEventListener = ((...args: unknown[]) => {
        listeners += 1;
        return (orig as (...a: unknown[]) => void)(...args);
      }) as typeof el.addEventListener;
      return el;
    },
  } as unknown as Document;
  return { doc, stats: () => ({ created, listeners }) };
}

/** id 가 from..to 인 단지 목록(팬 시뮬레이션용). 매번 **새 객체**로 만든다. */
function complexRange(from: number, to: number): ComplexItem[] {
  const out: ComplexItem[] = [];
  for (let id = from; id <= to; id += 1) out.push(complex(id));
  return out;
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

describe("CR18-7 — id 기준 diff (마커 재사용)", () => {
  // 예전 구현은 갱신마다 전량 파괴·재생성했다. 500개 상한 기준 팬 1회에
  // 요소 1,000개 생성 + addEventListener 1,000회. 밀집 지역(강남·송파)에서 프레임이 끊긴다.
  // 아래 단언들은 "얼마나 안 만드는가"를 숫자로 못박는다.

  it("같은 목록을 다시 그리면 오버레이·DOM 요소·리스너를 하나도 새로 만들지 않는다(재사용률 100%)", () => {
    const { kakao, overlays } = mockKakao();
    const { doc, stats } = countingDoc();
    const layer = new MarkerLayer({ kakao, map: { panTo: vi.fn() }, doc });

    layer.setComplexes(complexRange(1, 500), {});
    const first = stats();
    expect(overlays.length).toBe(500);
    expect(first.created).toBe(1000); // 마커당 div+span
    expect(first.listeners).toBe(1000); // 마커당 click+keydown

    // App 은 조회할 때마다 **새 배열·새 객체**를 넣는다 — 그 상황을 그대로 재현한다.
    layer.setComplexes(complexRange(1, 500), {});
    const second = stats();

    expect(overlays.length).toBe(500); // 신규 오버레이 0
    expect(second.created - first.created).toBe(0); // 신규 요소 0
    expect(second.listeners - first.listeners).toBe(0); // 신규 리스너 0
    // 살아남은 마커는 지도에서 떼어냈다 다시 붙이지도 않는다(깜빡임·재배치 방지).
    expect(overlays.every((o) => !o.setMapCalls.includes(null))).toBe(true);
  });

  it("팬(80% 겹침) — 사라진 것만 떼고 새로 생긴 것만 만든다", () => {
    const { kakao, overlays } = mockKakao();
    const { doc, stats } = countingDoc();
    const layer = new MarkerLayer({ kakao, map: { panTo: vi.fn() }, doc });

    layer.setComplexes(complexRange(1, 500), {});
    const before = stats();

    layer.setComplexes(complexRange(101, 600), {}); // 400 재사용 · 100 신규 · 100 소멸
    const after = stats();

    expect(overlays.length).toBe(600); // 신규 오버레이 100개뿐
    expect(after.created - before.created).toBe(200); // 100 × (div+span)
    expect(after.listeners - before.listeners).toBe(200); // 100 × 2
    expect(overlays.filter((o) => o.setMapCalls.includes(null)).length).toBe(100); // 소멸분만 정리
  });

  it("재사용해도 상태 변화는 반영한다 — 선택 클래스·zIndex·라벨", () => {
    const { kakao, overlays } = mockKakao();
    const layer = new MarkerLayer({ kakao, map: { panTo: vi.fn() }, doc: document });

    layer.setComplexes([complex(1), complex(2)], { selectedId: 1 });
    const el1 = overlays[0].opts.content as HTMLElement;
    const el2 = overlays[1].opts.content as HTMLElement;

    layer.setComplexes([complex(1), complex(2)], { selectedId: 2 });

    expect(overlays.length).toBe(2); // 재생성 없음
    expect(el1.className).not.toContain("map-pill--selected");
    expect(el2.className).toContain("map-pill--selected");
    expect(overlays[1].zIndexCalls).toContain(100); // 선택은 위로
    expect(overlays[0].zIndexCalls).toContain(10); // 해제는 원래 층으로
  });

  it("재사용 마커의 라벨 텍스트가 새 값으로 갱신된다(옛 가격이 남지 않는다)", () => {
    const { kakao, overlays } = mockKakao();
    const layer = new MarkerLayer({ kakao, map: { panTo: vi.fn() }, doc: document });

    layer.setComplexes([complex(1)], {});
    const el = overlays[0].opts.content as HTMLElement;
    expect(el.textContent).toContain("14.8억");

    layer.setComplexes([{ ...complex(1), recent_price_krw: 2_000_000_000 }], {});

    expect(overlays.length).toBe(1);
    expect(el.textContent).toContain("20.0억");
    expect(el.textContent).not.toContain("14.8억");
  });

  it("줄 수가 달라져도(순위 배지 등장) 라벨을 다시 채운다", () => {
    const { kakao, overlays } = mockKakao();
    const layer = new MarkerLayer({ kakao, map: { panTo: vi.fn() }, doc: document });

    layer.setComplexes([complex(1)], {});
    const el = overlays[0].opts.content as HTMLElement;

    layer.setComplexes([complex(1)], { rankById: { 1: 2 } });

    expect(overlays.length).toBe(1);
    expect(el.textContent).toContain("2위");
    expect(el.querySelectorAll("span").length).toBe(2);
    expect(el.getAttribute("aria-label")).toContain("2위");
  });

  it("재사용 마커는 **최신** onSelect 를 호출한다(옛 클로저가 남으면 안 된다)", () => {
    // 재사용하면서 콜백 교체를 빼먹으면, 마커 탭이 옛 상태를 잡은 콜백을 부른다.
    // 화면에는 아무 이상이 없어 눈으로는 절대 못 잡는 종류의 버그다.
    const { kakao, overlays } = mockKakao();
    const layer = new MarkerLayer({ kakao, map: { panTo: vi.fn() }, doc: document });
    const stale = vi.fn();
    const fresh = vi.fn();

    layer.setComplexes([complex(1)], { onSelect: stale });
    layer.setComplexes([complex(1)], { onSelect: fresh });
    const el = overlays[0].opts.content as HTMLElement;
    el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));

    expect(stale).not.toHaveBeenCalled();
    expect(fresh).toHaveBeenCalledTimes(2);
    expect(fresh).toHaveBeenCalledWith(1);
  });

  it("사라진 마커는 리스너까지 떼어낸다(재사용이 누수로 바뀌지 않게)", () => {
    const { kakao, overlays } = mockKakao();
    const layer = new MarkerLayer({ kakao, map: { panTo: vi.fn() }, doc: document });
    const onSelect = vi.fn();

    layer.setComplexes([complex(1)], { onSelect });
    const el = overlays[0].opts.content as HTMLElement;
    layer.setComplexes([], { onSelect });
    el.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    expect(onSelect).not.toHaveBeenCalled();
  });

  it("같은 응답에 id 가 중복돼도 오버레이가 새어나가지 않는다", () => {
    const { kakao, overlays } = mockKakao();
    const layer = new MarkerLayer({ kakao, map: { panTo: vi.fn() }, doc: document });

    layer.setComplexes([complex(1), complex(1)], {});
    layer.setComplexes([], {});

    expect(overlays.length).toBe(1);
    expect(overlays[0].setMapCalls).toContain(null); // 추적되지 않은 채 남는 것이 없다
  });

  it("destroy 는 재사용 캐시까지 비운다(다시 그리면 새로 만든다)", () => {
    const { kakao, overlays } = mockKakao();
    const layer = new MarkerLayer({ kakao, map: { panTo: vi.fn() }, doc: document });

    layer.setComplexes([complex(1)], {});
    layer.destroy();
    layer.setComplexes([complex(1)], {});

    expect(overlays.length).toBe(2);
    expect(overlays[0].setMapCalls).toContain(null);
  });

  it("군집도 region_code 로 재사용한다 — 개수만 바뀌면 요소를 만들지 않는다", () => {
    const { kakao, overlays } = mockKakao();
    const { doc, stats } = countingDoc();
    const layer = new MarkerLayer({ kakao, map: { panTo: vi.fn() }, doc });

    layer.setClusters([cluster("1168000000", 342), cluster("1150000000", 100)]);
    const before = stats();
    const el = overlays[0].opts.content as HTMLElement;

    layer.setClusters([cluster("1168000000", 350), cluster("1174000000", 7)]);
    const after = stats();

    expect(overlays.length).toBe(3); // 신규 1개(1174…)만
    expect(after.created - before.created).toBe(3); // div+span 2줄
    expect(el.textContent).toContain("350"); // 재사용된 군집의 숫자는 갱신
    expect(overlays[1].setMapCalls).toContain(null); // 사라진 1150… 만 제거
  });

  it("군집 중심이 움직이면 setPosition 으로 옮긴다 — 좌표 순서는 CR18-5 그대로", () => {
    const { kakao, overlays } = mockKakao();
    const layer = new MarkerLayer({ kakao, map: { panTo: vi.fn() }, doc: document });

    layer.setClusters([{ ...cluster("1168000000", 10), center: [127.0276, 37.4979] }]);
    layer.setClusters([{ ...cluster("1168000000", 11), center: [127.1, 37.6] }]);

    expect(overlays.length).toBe(1);
    const moved = overlays[0].positionCalls[0] as { lat: number; lng: number };
    expect(moved.lat).toBe(37.6);
    expect(moved.lng).toBe(127.1);
  });
});

describe("patchLabelEl — 재사용 경로도 XSS 안전", () => {
  // 갱신 경로가 innerHTML 로 바뀌면 보안리뷰 PASS 가 무너진다. 두 갈래(같은 줄 수/다른 줄 수) 모두 막는다.
  const PAYLOAD = "<img src=x onerror=alert(1)>";

  it("줄 수가 같은 갱신(textContent 교체)에서 HTML 로 해석하지 않는다", () => {
    const el = buildLabelEl(document, "x", ["14.8억"]);
    patchLabelEl(document, el, [PAYLOAD]);

    expect(el.querySelector("img")).toBeNull();
    expect(el.textContent).toContain("<img");
  });

  it("줄 수가 달라지는 갱신(다시 채우기)에서도 마찬가지다", () => {
    const el = buildLabelEl(document, "x", ["14.8억"]);
    patchLabelEl(document, el, ["1위", PAYLOAD]);

    expect(el.querySelector("img")).toBeNull();
    expect(el.querySelectorAll("span").length).toBe(2);
    expect(el.textContent).toContain("<img");
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
