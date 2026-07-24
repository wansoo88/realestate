/**
 * 지도 — 카카오맵 SDK.
 *
 * SDK 키가 없으면 **빈 화면 대신 무슨 상황인지 설명**한다.
 * 개발 중에 지도가 안 뜨는 이유를 모르면 시간이 그냥 날아간다.
 */
import { useEffect, useRef, useState } from "react";
import "./MapView.css";

const KAKAO_KEY = import.meta.env.VITE_KAKAO_JS_APP_KEY as string | undefined;

/** 서울시청 — 초기 중심 */
const DEFAULT_CENTER = { lat: 37.5665, lng: 126.978 };
const DEFAULT_LEVEL = 6;

interface Props {
  onBoundsChange: (bbox: string, zoom: number) => void;
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

export function MapView({ onBoundsChange }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!KAKAO_KEY) {
      setError(
        "카카오맵 키가 설정되지 않았습니다. frontend/.env 에 VITE_KAKAO_JS_APP_KEY 를 넣으세요.",
      );
      return;
    }
    let map: any;
    let cancelled = false;

    loadSdk(KAKAO_KEY)
      .then(() => {
        if (cancelled || !ref.current) return;
        const kakao = window.kakao;
        map = new kakao.maps.Map(ref.current, {
          center: new kakao.maps.LatLng(DEFAULT_CENTER.lat, DEFAULT_CENTER.lng),
          level: DEFAULT_LEVEL,
        });

        const emit = () => {
          const b = map.getBounds();
          const sw = b.getSouthWest();
          const ne = b.getNorthEast();
          // 카카오 level 은 작을수록 확대 — 우리 zoom 규약(클수록 확대)으로 뒤집는다
          const zoom = 20 - map.getLevel();
          onBoundsChange(
            `${sw.getLng()},${sw.getLat()},${ne.getLng()},${ne.getLat()}`,
            zoom,
          );
        };
        kakao.maps.event.addListener(map, "idle", emit);
        emit();
      })
      .catch((e: Error) => !cancelled && setError(e.message));

    return () => {
      cancelled = true;
    };
  }, [onBoundsChange]);

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

  return <div ref={ref} className="map" role="application" aria-label="지도" />;
}
