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
import { bboxTooLarge } from "../lib/bbox";
import { buildMapQuery, type MapFilterState } from "../lib/mapFilters";

/** 지도를 끌 때마다 요청이 나가지 않도록 하는 간격. */
export const MAP_DEBOUNCE_MS = 350;

export interface MapAreaState {
  level: "complex" | "cluster" | null;
  items: ComplexItem[];
  clusters: ClusterItem[];
  loading: boolean;
  error: string | null;
  /**
   * 지도가 **지금** 보고 있는 범위(`minLon,minLat,maxLon,maxLat`).
   * 지도가 아직 준비되지 않았으면 null — 화면은 이 값으로 "이 주변에서 찾기"를 켤지 정한다.
   *
   * 왜 ref 가 아니라 state 인가: 버튼 활성/비활성과 "지도를 옮겼다" 표시가 이 값으로 갈리는데,
   * ref 는 다시 그리지 않으므로 지도가 준비돼도 버튼이 계속 죽어 있게 된다.
   * (idle 은 지도가 멈출 때만 오므로 렌더 폭풍이 되지 않는다)
   */
  bbox: string | null;
}

export function useMapArea(filters: MapFilterState) {
  const [state, setState] = useState<MapAreaState>({
    level: null,
    items: [],
    clusters: [],
    loading: false,
    error: null,
    bbox: null,
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
      // ⚠️ 통째로 갈아끼우지 않는다(updater 로 이전 상태를 이어받는다) —
      //    조회 응답이 화면 범위(bbox)를 덮어 지우면 "이 주변에서 찾기"가 조회 때마다 꺼진다.
      setState((s) =>
        res.level === "complex"
          ? { ...s, level: "complex", items: res.items, clusters: [], loading: false, error: null }
          : { ...s, level: "cluster", items: [], clusters: res.items, loading: false, error: null },
      );
    } catch (e) {
      if (!alive.current || id !== reqId.current) return;
      // 401 은 client.ts 가 로그아웃으로 방송한다 — 여기선 문구만 만든다.
      // 400 중에는 **지도를 너무 많이 축소한 경우**가 섞여 있다(서버 상한: 한 변 2도).
      // 서버 문구는 파라미터 검증 오류라 사용자가 고칠 방법을 알려주지 못한다 —
      // 우리가 보낸 bbox 로 그 사유를 짚어낼 수 있으면 그렇게 말한다.
      const msg =
        e instanceof ApiException
          ? e.error.code === "UNAUTHORIZED"
            ? "세션이 만료되었습니다. 다시 로그인해 주세요."
            : (e.status === 400 || e.status === 422) && bboxTooLarge(area.bbox)
              ? "지도 범위가 너무 넓어 단지를 불러올 수 없습니다 — 확대하면 표시됩니다."
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
      // 조회는 디바운스하지만 **범위 자체는 즉시** 반영한다. 이건 요청이 아니라
      // "지금 어디를 보고 있나"이고, 화면(이 주변에서 찾기)이 곧바로 알아야 한다.
      // 같은 값이면 새 객체를 만들지 않는다(불필요한 리렌더 금지).
      setState((s) => (s.bbox === bbox ? s : { ...s, bbox }));
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
