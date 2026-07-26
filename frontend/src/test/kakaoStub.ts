/**
 * 카카오맵 SDK 스텁 — **테스트에서 지도 경로를 실제로 태우기 위한 것**.
 *
 * 왜 필요한가: 이 앱에서 목록은 지도가 만들어 낸다. `idle` 이벤트 → bbox → 조회 → 목록.
 * jsdom 은 외부 스크립트를 로드하지 않으므로 SDK 가 없으면 지도가 만들어지지 않고,
 * **목록도 영원히 비어 있다.** 그래서 정렬·hover·마커 단계 같은 화면 동작을 테스트하려면
 * SDK 자리를 채워 줘야 한다. (여기서 지어내는 것은 SDK 뿐이고, 서버 응답은 여전히 목이다.)
 *
 * MapView 가 실제로 쓰는 API 만 흉내낸다 — 더 만들면 그건 SDK 재구현이지 테스트가 아니다.
 */

export interface KakaoStubHandle {
  /** 생성된 CustomOverlay 들(마커 검증용) */
  overlays: Array<{ opts: Record<string, any>; mapArg: unknown }>;
  /** 지금 지도 level (작을수록 확대) */
  level(): number;
  /** 지도 중심 [경도, 위도] — 좌표 순서 회귀(CR18-5)를 여기서도 잡는다 */
  center(): [number, number];
  /** idle 을 강제로 한 번 더 발생시킨다(팬·줌 시뮬레이션) */
  fireIdle(): void;
  /**
   * 지도를 끌어 옮긴 것처럼 중심을 바꾸고 idle 을 발생시킨다.
   * 인자는 지도 규약과 같은 **[경도, 위도]** — 여기서 뒤집으면 테스트가 좌표순서를 못 잡는다.
   * (React 상태가 따라 움직이므로 호출부에서 `act()` 로 감싼다)
   */
  moveTo(center: [number, number]): void;
  restore(): void;
}

/** 장소검색(services) 스텁 주입 옵션. 없으면 services 자체가 없는 상태를 흉내낸다. */
export interface PlacesStub {
  status?: "OK" | "ZERO_RESULT" | "ERROR";
  rows?: Array<Record<string, unknown>>;
}

export function installKakaoStub(
  init: { level?: number; center?: [number, number]; places?: PlacesStub } = {},
): KakaoStubHandle {
  let level = init.level ?? 6;
  const center: [number, number] = [...(init.center ?? [126.978, 37.5665])] as [number, number];
  const overlays: KakaoStubHandle["overlays"] = [];
  const listeners = new Map<string, Set<() => void>>();

  const latLng = (lat: number, lng: number) => ({
    getLat: () => lat,
    getLng: () => lng,
    lat,
    lng,
  });

  const map = {
    getLevel: () => level,
    setLevel: (n: number) => {
      level = n;
      fire("idle");
    },
    getCenter: () => latLng(center[1], center[0]),
    // 실제 SDK 와 같은 인자 형태(LatLng) — 좌표 순서가 뒤집히면 여기서 드러난다.
    setCenter: (p: { lat: number; lng: number }) => {
      center[0] = p.lng;
      center[1] = p.lat;
      fire("idle");
    },
    relayout: () => fire("idle"),
    // 화면 범위는 중심에서 ±0.05도로 고정한다(값 자체는 테스트에 중요하지 않다).
    getBounds: () => ({
      getSouthWest: () => latLng(center[1] - 0.05, center[0] - 0.05),
      getNorthEast: () => latLng(center[1] + 0.05, center[0] + 0.05),
    }),
    panTo: () => {},
  };

  function fire(type: string) {
    for (const fn of listeners.get(type) ?? []) fn();
  }

  class CustomOverlay {
    opts: Record<string, any>;
    mapArg: unknown = null;
    constructor(opts: Record<string, any>) {
      this.opts = opts;
      overlays.push(this);
    }
    setMap(m: unknown) {
      this.mapArg = m;
    }
    setZIndex() {}
    setPosition() {}
  }

  /** 장소검색 — 실제 SDK 와 같은 콜백 형태(status 문자열 + 배열). */
  const services = init.places
    ? {
        Places: class {
          keywordSearch(
            _kw: string,
            cb: (data: unknown[], status: string) => void,
          ) {
            cb(init.places?.rows ?? [], init.places?.status ?? "OK");
          }
        },
        Status: { OK: "OK", ZERO_RESULT: "ZERO_RESULT", ERROR: "ERROR" },
      }
    : undefined;

  const prev = window.kakao;
  window.kakao = {
    maps: {
      ...(services ? { services } : {}),
      // MapView 는 window.kakao.maps 가 이미 있으면 스크립트를 붙이지 않는다.
      load: (cb: () => void) => cb(),
      Map: function KakaoMap() {
        return map;
      } as unknown as new () => typeof map,
      LatLng: function LatLng(lat: number, lng: number) {
        return latLng(lat, lng);
      } as unknown as new (lat: number, lng: number) => unknown,
      CustomOverlay,
      event: {
        addListener: (_t: unknown, type: string, fn: () => void) => {
          if (!listeners.has(type)) listeners.set(type, new Set());
          listeners.get(type)!.add(fn);
        },
        removeListener: (_t: unknown, type: string, fn: () => void) => {
          listeners.get(type)?.delete(fn);
        },
      },
    },
  };

  return {
    overlays,
    level: () => level,
    center: () => [center[0], center[1]],
    fireIdle: () => fire("idle"),
    // 실제 SDK 와 같은 인자 형태(LatLng)로 넘긴다 — 지도 쪽 경로를 그대로 태운다.
    moveTo: (c) => map.setCenter(latLng(c[1], c[0])),
    restore: () => {
      window.kakao = prev;
      listeners.clear();
    },
  };
}
