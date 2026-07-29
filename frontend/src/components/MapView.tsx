/**
 * 지도 — 카카오맵 SDK. 컨셉 "확신의 농도": 지도는 배경이 아니라 캔버스다(규칙 4).
 *
 * 이 컴포넌트가 책임지는 것
 *  ① 지도 1회 생성 · idle 마다 bbox/zoom 을 위로 올림(조회는 부모가 디바운스해서 한다)
 *  ② **표현 단계 결정** — 지금 줌과 화면 안 단지 수로 dot/price/detail 을 고른다(lib/markerTiers)
 *  ③ 지도 위 컨트롤(확대/축소·범례·밀집 안내)
 *
 * SDK 키가 없으면 **빈 화면 대신 무슨 상황인지 설명**한다.
 * 마커 렌더링은 lib/mapMarkers 의 MarkerLayer 가 맡는다(SDK 목킹으로 단위 테스트 가능).
 *
 * ⚠️ 지도 위 컨트롤 위치: 카카오맵은 **좌하단에 로고·저작권 표기**를 강제로 그린다.
 *    그 위에 무엇도 올리지 않는다(가리면 이용약관 위반이다). 그래서 확대/축소는 우측,
 *    조건 진입점은 좌상단(App 의 조건 바), 범례는 좌상단 아래에 둔다.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { ClusterItem } from "../api/client";
import { lastCamera, rememberCamera } from "../lib/mapCamera";
import { MarkerLayer } from "../lib/mapMarkers";
import type { ScreenComplexItem } from "../lib/screenBudget";
import { baseTier, densityNotice } from "../lib/markerTiers";
import type { Place } from "../lib/placeSearch";
import { MapLegend } from "./MapLegend";
import { PlaceSearch } from "./PlaceSearch";
import "./MapView.css";

/**
 * 앱키는 **읽는 시점을 컴포넌트 안으로** 둔다.
 * 모듈 최상위에서 읽으면 import 시점에 값이 굳어져 테스트에서 주입할 수 없다
 * (운영 빌드에서는 어느 쪽이든 Vite 가 리터럴로 바꿔 넣는다 — 동작은 동일하다).
 */
function kakaoKey(): string | undefined {
  return import.meta.env.VITE_KAKAO_JS_APP_KEY as string | undefined;
}

/** 카카오 level 유효 범위. 밖으로 나가면 SDK 가 조용히 무시한다. */
const MIN_LEVEL = 1;
const MAX_LEVEL = 14;

interface Props {
  onBoundsChange: (bbox: string, zoom: number) => void;
  /**
   * zoom >= 13 : 단지 단위.
   *
   * **서버 항목(`ComplexItem`)을 그대로 받지 않는다.** `over_budget` 은 3값인데 화면이
   * 다시 판정해야 하고(정본 = 화면 판정, `lib/budgetStatus` 머리말), 그때 "모름"을
   * `false` 로 접어도 **화면에는 아무 변화가 없다**(배지는 `=== true` 에만 붙는다).
   * 그래서 타입으로 막는다 — `applyScreenBudget` 이 만든 값만 여기 들어온다(CR37-2).
   */
  items?: ScreenComplexItem[];
  clusters?: ClusterItem[]; // zoom < 13 : 군집
  selectedId?: number | null; // 리스트 카드 ↔ 마커 양방향 동기화
  hoveredId?: number | null; // 리스트 hover → 마커 강조
  onSelect?: (id: number) => void;
  rankById?: Record<number, number>; // 추천 순위 배지
}

declare global {
  interface Window {
    kakao?: any;
  }
}

/**
 * SDK 가 **실제로 쓸 수 있는** 상태인가.
 *
 * `window.kakao.maps` 가 있다는 것만으로는 부족하다. 로더 스크립트는 **첫 줄에서**
 * `window.kakao.maps = {}` 를 만들어 두고 본체(`kakao.js`)는 그 뒤에 비동기로 채운다.
 * 그 사이에 `new kakao.maps.Map(...)` 을 부르면 TypeError 다 — 지도를 다녀오는 왕복
 * (조건 화면 ↔ 지도)마다 재마운트되므로 이 창은 실제로 열린다.
 */
function sdkUsable(): boolean {
  return typeof window.kakao?.maps?.Map === "function";
}

/** SDK 가 200 으로 왔는데 SDK 가 아닌 경우(카카오가 오류 본문을 돌려주는 경우)의 문구. */
const SDK_BROKEN =
  "카카오맵 SDK 응답이 올바르지 않습니다. 지도 키와 등록 도메인을 확인해 주세요.";

function loadSdk(key: string): Promise<void> {
  if (sdkUsable()) return Promise.resolve();

  return new Promise((resolve, reject) => {
    // 로더는 실행됐지만 본체가 아직 로드 중인 상태(readyState 0/1). 스크립트를 **또** 붙이지
    // 않고 그 로드에 올라탄다 — 재마운트마다 <script> 를 쌓으면 요청만 늘고 경합이 생긴다.
    const pending = window.kakao?.maps?.load;
    if (typeof pending === "function") {
      pending(() => (sdkUsable() ? resolve() : reject(new Error(SDK_BROKEN))));
      return;
    }

    const script = document.createElement("script");
    // `services` 는 장소·역 검색용(PlaceSearch). REST API 를 브라우저에서 부르지 않기 위해
    // SDK 쪽을 쓴다 — REST 키는 서버 전용이다. 출처는 `dapi.kakao.com`(script-src 에 허용됨)이고
    // 검색 XHR 도 같은 출처(connect-src 에 허용됨)라 CSP 변경은 필요 없다(lib/placeSearch 머리말).
    script.src =
      `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${key}&autoload=false&libraries=services,clusterer`;
    script.onload = () => {
      // ⚠️ 예전에는 여기서 곧장 `window.kakao.maps.load(...)` 를 불렀다. 스크립트가 200 으로
      //    왔지만 SDK 가 아니면(카카오는 인증 실패를 JSON 본문으로 돌려준다) 이 줄이 TypeError 를
      //    던졌고, 그 예외는 **Promise 를 이행도 거부도 하지 못했다** — `ready` 도 `error` 도
      //    영원히 그대로라 지도는 빈 회색 화면으로 남고 아무 메시지도 뜨지 않았다.
      //    조용히 삼키지 않는다: 쓸 수 없으면 쓸 수 없다고 말한다.
      if (typeof window.kakao?.maps?.load !== "function") {
        reject(new Error(SDK_BROKEN));
        return;
      }
      window.kakao.maps.load(() => (sdkUsable() ? resolve() : reject(new Error(SDK_BROKEN))));
    };
    // 도메인이 콘솔에 등록돼 있지 않으면 카카오는 이 스크립트를 **401** 로 돌려주고,
    // 브라우저는 그걸 로드 실패로 처리해 여기로 온다. 그때 "로드 실패"만 적으면
    // 어디를 고쳐야 하는지 알 수 없다 — 실제로 고칠 곳을 적는다.
    script.onerror = () =>
      reject(
        new Error(
          "카카오맵 SDK 를 불러오지 못했습니다. 카카오 개발자 콘솔에 이 사이트 도메인이 등록됐는지 확인해 주세요.",
        ),
      );
    document.head.appendChild(script);
  });
}

export function MapView({
  onBoundsChange,
  items = [],
  clusters = [],
  selectedId = null,
  hoveredId = null,
  onSelect,
  rankById,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  /** 장소를 골랐는데 옮기지 못했을 때의 안내. 조용한 무반응을 만들지 않기 위한 것이다. */
  const [moveNotice, setMoveNotice] = useState<string | null>(null);
  /** 우리 규약(클수록 확대)의 현재 줌. 표현 단계를 고르는 입력이다. */
  const [zoom, setZoom] = useState(() => 20 - lastCamera().level);

  const mapRef = useRef<any>(null);
  const layerRef = useRef<MarkerLayer | null>(null);

  // 콜백을 ref 에 담아 지도 재생성 없이 항상 최신 핸들러를 쓰게 한다.
  const onBoundsRef = useRef(onBoundsChange);
  onBoundsRef.current = onBoundsChange;
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  // 지도 1회 생성(마커 갱신과 분리해 지도가 재생성되지 않게 한다).
  useEffect(() => {
    const key = kakaoKey();
    if (!key) {
      setError(
        "카카오맵 키가 설정되지 않았습니다. frontend/.env 에 VITE_KAKAO_JS_APP_KEY 를 넣으세요.",
      );
      return;
    }
    let cancelled = false;
    // SDK 로드가 끝난 뒤에야 리스너를 달 수 있으므로, 해제 함수를 여기에 담아 두고
    // cleanup 에서 호출한다(CR18-6: idle 리스너를 떼지 않으면 StrictMode 재마운트·HMR 마다 쌓인다).
    let removeIdle: (() => void) | null = null;

    loadSdk(key)
      .then(() => {
        if (cancelled || !ref.current) return;
        const kakao = window.kakao;
        // 조건 화면을 다녀와도 보던 자리로 돌아온다(lib/mapCamera).
        const camera = lastCamera();
        const map = new kakao.maps.Map(ref.current, {
          center: new kakao.maps.LatLng(camera.center[1], camera.center[0]),
          level: camera.level,
        });
        mapRef.current = map;
        layerRef.current = new MarkerLayer({ kakao, map });

        const emit = () => {
          const b = map.getBounds();
          const sw = b.getSouthWest();
          const ne = b.getNorthEast();
          const level = map.getLevel();
          const center = map.getCenter();
          rememberCamera({ center: [center.getLng(), center.getLat()], level });
          // 카카오 level 은 작을수록 확대 — 우리 zoom 규약(클수록 확대)으로 뒤집는다.
          const z = 20 - level;
          setZoom(z);
          onBoundsRef.current(
            `${sw.getLng()},${sw.getLat()},${ne.getLng()},${ne.getLat()}`,
            z,
          );
        };
        kakao.maps.event.addListener(map, "idle", emit);
        removeIdle = () => kakao.maps.event.removeListener(map, "idle", emit);
        emit();
        setReady(true);
      })
      .catch((e: Error) => !cancelled && setError(e.message));

    return () => {
      cancelled = true;
      removeIdle?.();
      removeIdle = null;
      layerRef.current?.destroy();
      layerRef.current = null;
      mapRef.current = null;
    };
  }, []);

  /**
   * 검색한 장소로 지도를 옮긴다.
   * `setCenter` 가 아니라 `panTo` 를 쓰면 먼 거리에서 화면이 길게 흐르므로 즉시 이동시키고,
   * 동네 단위가 보이도록 줌을 맞춘다(idle 이 뒤따라 발생해 조회가 갱신된다).
   */
  const moveTo = useCallback((place: Place) => {
    const map = mapRef.current;
    if (!map) {
      // 예전에는 여기서 그냥 return 했다. 그러면 결과를 눌렀는데 **아무 일도 일어나지 않고**
      // 사용자는 자기가 잘못 눌렀다고 생각한다. 못 옮기면 못 옮긴다고 말한다.
      setMoveNotice("지도를 아직 불러오지 못해 이동할 수 없습니다.");
      return;
    }
    setMoveNotice(null);
    // [경도, 위도] → LatLng(위도, 경도). 한 번만 뒤집혀도 태평양으로 간다(CR18-5).
    map.setCenter(new window.kakao.maps.LatLng(place.point[1], place.point[0]));
    if (map.getLevel() > 5) map.setLevel(5);
    else map.relayout?.(); // 줌이 그대로면 idle 이 안 뜰 수 있다 — 갱신을 확실히 시킨다
  }, []);

  /** 확대/축소 — 카카오 기본 컨트롤을 쓰지 않고 직접 그린다(우리 토큰·다크모드·터치 타깃 적용). */
  const zoomBy = useCallback((delta: number) => {
    const map = mapRef.current;
    if (!map) return;
    const next = Math.min(MAX_LEVEL, Math.max(MIN_LEVEL, map.getLevel() + delta));
    map.setLevel(next); // idle 이 뒤따라 발생해 조회·표현단계가 함께 갱신된다
  }, []);

  // 이번 화면의 기본 표현 단계 — 줌과 밀집으로 결정한다.
  const tier = baseTier(zoom, items.length);
  const notice = densityNotice(tier, items.length);

  // 단지 마커 동기화 (zoom >= 13)
  useEffect(() => {
    if (!ready || !layerRef.current) return;
    layerRef.current.setComplexes(items, {
      selectedId,
      hoveredId,
      rankById,
      tier,
      onSelect: (id) => onSelectRef.current?.(id),
    });
  }, [ready, items, selectedId, hoveredId, rankById, tier]);

  // 군집 마커 동기화 (zoom < 13) — 탭하면 해당 지역으로 한 단계 확대한다.
  useEffect(() => {
    if (!ready || !layerRef.current) return;
    layerRef.current.setClusters(clusters, (c) => {
      const map = mapRef.current;
      if (!map) return;
      map.panTo(new window.kakao.maps.LatLng(c.center[1], c.center[0]));
      map.setLevel(Math.max(MIN_LEVEL, map.getLevel() - 2));
    });
  }, [ready, clusters]);

  if (error) {
    return (
      <div className="mapzone">
        <div className="map map--error" role="status">
          <p className="map__error-title">지도를 표시할 수 없습니다</p>
          <p className="map__error-detail">{error}</p>
          <p className="map__error-hint">
            지도 없이도 목록으로 단지를 확인할 수 있습니다.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="mapzone">
      {/* 지도는 스크린리더로 못 읽는다 — 대체 경로(목록)를 명시한다(README §11) */}
      <p id="map-alt" className="sr-only">
        지도 내용은 목록에서 확인할 수 있습니다.
      </p>
      <div ref={ref} className="map" role="region" aria-label="단지 지도" aria-describedby="map-alt" />

      {/* 지도 위 레이어. 컨테이너는 클릭을 통과시키고(pointer-events:none) 자식만 받는다. */}
      <div className="map__overlays">
        {/* 역·장소로 지도를 옮긴다. **필터가 아니다** — 문구가 그렇게 말한다. */}
        <PlaceSearch onPick={moveTo} notice={moveNotice} />

        {/* 무엇을 왜 줄였는지 — 조용히 줄이면 그건 숨긴 것이다(markerTiers) */}
        {notice && (
          <div className="map__density" role="status">
            <span className="map__density-text">{notice}</span>
            {/* 접근명이 확대/축소 컨트롤과 겹치지 않게 목적까지 적는다
                ("확대" 버튼이 화면에 둘이면 스크린리더 사용자는 어느 쪽인지 알 수 없다) */}
            <button type="button" className="map__density-zoom" onClick={() => zoomBy(-1)}>
              확대해서 보기
            </button>
          </div>
        )}
        <MapLegend />
      </div>

      <div className="map__zoom">
        <button type="button" className="map__zoombtn" aria-label="확대" onClick={() => zoomBy(-1)}>
          <svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false">
            <path
              d="M10 4v12M4 10h12"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
            />
          </svg>
        </button>
        <button type="button" className="map__zoombtn" aria-label="축소" onClick={() => zoomBy(1)}>
          <svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false">
            <path d="M4 10h12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
        </button>
      </div>
    </div>
  );
}
