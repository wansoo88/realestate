/**
 * 지도 — 카카오맵 SDK. 컨셉 "확신의 농도": 지도는 배경이 아니라 캔버스다(규칙 4).
 *
 * SDK 키가 없으면 **빈 화면 대신 무슨 상황인지 설명**한다.
 * 마커 렌더링은 lib/mapMarkers 의 MarkerLayer 가 맡는다(SDK 목킹으로 단위 테스트 가능).
 */
import { useEffect, useRef, useState } from "react";
import type { ClusterItem, ComplexItem } from "../api/client";
import { MarkerLayer } from "../lib/mapMarkers";
import "./MapView.css";

const KAKAO_KEY = import.meta.env.VITE_KAKAO_JS_APP_KEY as string | undefined;

/** 서울시청 — 초기 중심 */
const DEFAULT_CENTER = { lat: 37.5665, lng: 126.978 };
const DEFAULT_LEVEL = 6;

interface Props {
  onBoundsChange: (bbox: string, zoom: number) => void;
  items?: ComplexItem[]; // zoom >= 13 : 단지 단위
  clusters?: ClusterItem[]; // zoom < 13 : 군집
  selectedId?: number | null; // 리스트 카드 ↔ 마커 양방향 동기화
  onSelect?: (id: number) => void;
  rankById?: Record<number, number>; // 추천 순위 배지(①②③)
}

declare global {
  interface Window {
    kakao?: any;
  }
}

function loadSdk(key: string): Promise<void> {
  if (window.kakao?.maps) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src =
      `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${key}&autoload=false&libraries=clusterer`;
    script.onload = () => window.kakao.maps.load(() => resolve());
    script.onerror = () => reject(new Error("카카오맵 SDK 로드 실패"));
    document.head.appendChild(script);
  });
}

export function MapView({
  onBoundsChange,
  items = [],
  clusters = [],
  selectedId = null,
  onSelect,
  rankById,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  const mapRef = useRef<any>(null);
  const layerRef = useRef<MarkerLayer | null>(null);

  // 콜백을 ref 에 담아 지도 재생성 없이 항상 최신 핸들러를 쓰게 한다.
  const onBoundsRef = useRef(onBoundsChange);
  onBoundsRef.current = onBoundsChange;
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  // 지도 1회 생성(마커 갱신과 분리해 지도가 재생성되지 않게 한다).
  useEffect(() => {
    if (!KAKAO_KEY) {
      setError(
        "카카오맵 키가 설정되지 않았습니다. frontend/.env 에 VITE_KAKAO_JS_APP_KEY 를 넣으세요.",
      );
      return;
    }
    let cancelled = false;
    // SDK 로드가 끝난 뒤에야 리스너를 달 수 있으므로, 해제 함수를 여기에 담아 두고
    // cleanup 에서 호출한다(CR18-6: idle 리스너를 떼지 않으면 StrictMode 재마운트·HMR 마다 쌓인다).
    let removeIdle: (() => void) | null = null;

    loadSdk(KAKAO_KEY)
      .then(() => {
        if (cancelled || !ref.current) return;
        const kakao = window.kakao;
        const map = new kakao.maps.Map(ref.current, {
          center: new kakao.maps.LatLng(DEFAULT_CENTER.lat, DEFAULT_CENTER.lng),
          level: DEFAULT_LEVEL,
        });
        mapRef.current = map;
        layerRef.current = new MarkerLayer({ kakao, map });

        const emit = () => {
          const b = map.getBounds();
          const sw = b.getSouthWest();
          const ne = b.getNorthEast();
          // 카카오 level 은 작을수록 확대 — 우리 zoom 규약(클수록 확대)으로 뒤집는다.
          const zoom = 20 - map.getLevel();
          onBoundsRef.current(
            `${sw.getLng()},${sw.getLat()},${ne.getLng()},${ne.getLat()}`,
            zoom,
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

  // 단지 마커 동기화 (zoom >= 13)
  useEffect(() => {
    if (!ready || !layerRef.current) return;
    layerRef.current.setComplexes(items, {
      selectedId,
      rankById,
      onSelect: (id) => onSelectRef.current?.(id),
    });
  }, [ready, items, selectedId, rankById]);

  // 군집 마커 동기화 (zoom < 13) — 탭하면 해당 지역으로 한 단계 확대한다.
  useEffect(() => {
    if (!ready || !layerRef.current) return;
    layerRef.current.setClusters(clusters, (c) => {
      const map = mapRef.current;
      if (!map) return;
      map.panTo(new window.kakao.maps.LatLng(c.center[1], c.center[0]));
      map.setLevel(Math.max(1, map.getLevel() - 2));
    });
  }, [ready, clusters]);

  if (error) {
    return (
      <div className="map map--error" role="status">
        <p className="map__error-title">지도를 표시할 수 없습니다</p>
        <p className="map__error-detail">{error}</p>
        <p className="map__error-hint">
          지도 없이도 아래 목록으로 매물을 확인할 수 있습니다.
        </p>
      </div>
    );
  }

  return (
    <>
      {/* 지도는 스크린리더로 못 읽는다 — 대체 경로(목록)를 명시한다(README §11) */}
      <p id="map-alt" className="sr-only">
        지도 내용은 아래 매물 목록에서 확인할 수 있습니다.
      </p>
      <div ref={ref} className="map" role="region" aria-label="단지 지도" aria-describedby="map-alt" />
    </>
  );
}
