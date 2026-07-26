/**
 * 지도 범위 조회 — **내 조건을 반영해서**.
 *
 * 두 가지를 이 훅이 책임진다.
 *  ① 지도를 움직일 때마다 요청이 나가면 서버가 죽는다 → 350ms 디바운스(마지막 이동만).
 *  ② **조건이 바뀌면 같은 화면 범위로 즉시 다시 조회한다.** 이게 이 제품의 핵심 루프다 —
 *     예산 스위치를 껐는데 지도가 그대로면 사용자는 필터가 작동하는지 알 수 없다.
 *
 * 컴포넌트에서 fetch 를 부르지 않기 위해 훅으로 뺐다(components.md §1, RN 재사용).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiException, api, type ClusterItem, type ComplexItem } from "../api/client";
import { buildMapQuery, type MapFilterState } from "../lib/mapFilters";

/** 지도를 끌 때마다 요청이 나가지 않도록 하는 간격. */
export const MAP_DEBOUNCE_MS = 350;

export interface MapAreaState {
  level: "complex" | "cluster" | null;
  items: ComplexItem[];
  clusters: ClusterItem[];
  loading: boolean;
  error: string | null;
}

export function useMapArea(filters: MapFilterState) {
  const [state, setState] = useState<MapAreaState>({
    level: null,
    items: [],
    clusters: [],
    loading: false,
    error: null,
  });

  // 최신 필터를 콜백 재생성 없이 읽는다(지도 리스너를 매번 다시 달지 않기 위해).
  const filtersRef = useRef(filters);
  filtersRef.current = filters;

  const lastArea = useRef<{ bbox: string; zoom: number } | null>(null);
  const timer = useRef<number | null>(null);
  const reqId = useRef(0);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, []);

  const fetchNow = useCallback(async () => {
    const area = lastArea.current;
    if (!area) return;
    const id = (reqId.current += 1);
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const res = await api.mapComplexes(buildMapQuery(area.bbox, area.zoom, filtersRef.current));
      // 늦게 온 응답이 최신 화면을 덮지 않게 한다(팬을 빠르게 하면 순서가 뒤집힌다).
      if (!alive.current || id !== reqId.current) return;
      setState(
        res.level === "complex"
          ? { level: "complex", items: res.items, clusters: [], loading: false, error: null }
          : { level: "cluster", items: [], clusters: res.items, loading: false, error: null },
      );
    } catch (e) {
      if (!alive.current || id !== reqId.current) return;
      // 401 은 client.ts 가 로그아웃으로 방송한다 — 여기선 문구만 만든다.
      const msg =
        e instanceof ApiException
          ? e.error.code === "UNAUTHORIZED"
            ? "세션이 만료되었습니다. 다시 로그인해 주세요."
            : e.error.message
          : "네트워크 오류가 발생했습니다.";
      setState((s) => ({ ...s, loading: false, error: msg }));
    }
  }, []);

  const schedule = useCallback(
    (delay: number) => {
      if (timer.current) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => void fetchNow(), delay);
    },
    [fetchNow],
  );

  const onBoundsChange = useCallback(
    (bbox: string, zoom: number) => {
      lastArea.current = { bbox, zoom };
      schedule(MAP_DEBOUNCE_MS);
    },
    [schedule],
  );

  // 필터 **내용**이 바뀌면 즉시 재조회. 객체 정체성이 아니라 실제 쿼리로 비교해야
  // 부모가 매 렌더 새 객체를 만들어도 무한 루프가 나지 않는다.
  const filterKey = JSON.stringify(buildMapQuery("", 0, filters));
  const firstRun = useRef(true);
  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false;
      return; // 최초 조회는 지도의 첫 bounds 이벤트가 일으킨다
    }
    if (lastArea.current) schedule(0);
  }, [filterKey, schedule]);

  return { ...state, onBoundsChange, refresh: () => schedule(0) };
}
