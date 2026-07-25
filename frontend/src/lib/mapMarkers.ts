/**
 * 지도 마커 레이어 — 카카오맵 CustomOverlay.
 *
 * 컨셉 "확신의 농도"(규칙 4: 지도는 캔버스): 마커는 **떠 있는 유리 pill** 이다.
 * 카카오 기본 핀 대신 CustomOverlay 로 그린다 — 흰 배경 가격 pill(HTML/CSS 로 헤어라인·
 * 옅은 그림자·다크모드를 정확히 표현), 선택 시에만 파란 채움, 군집은 반투명 파란 원.
 * (기본 Marker 이미지로는 이 재질을 낼 수 없다. 오케스트레이터 컨셉이 충돌 시 우선.)
 *
 * 왜 컴포넌트 밖의 별도 모듈인가:
 * 1) 마커 생성/정리 로직을 순수하게 빼야 **SDK 를 목(mock)해 단위 테스트**할 수 있다.
 *    (카카오 SDK 는 실제 브라우저에서만 로드된다 — 테스트는 window.kakao 를 주입한다.)
 * 2) 뷰(리액트)에 의존하지 않게 해 RN 이식 경계를 명확히 한다(ux §10).
 *
 * ⚠️ XSS: 서버가 준 문자열(단지명 '청담(103)' 등)을 라벨에 넣을 때 innerHTML 을 절대
 *    쓰지 않는다. textContent 로만 넣어 브라우저가 이스케이프하게 한다(SR-014 전방관찰).
 *    dangerouslySetInnerHTML 도 쓰지 않는다.
 */
import type { ClusterItem, ComplexItem } from "../api/client";
import { formatKrwShort } from "./format";

/** 마커 가격 라벨 텍스트. 추정치는 '추정' 접두로 확정치와 구분한다(규칙 1·2). */
export function complexMarkerText(item: ComplexItem): string {
  if (item.recent_price_krw === null) return "데이터 없음";
  const price = formatKrwShort(item.recent_price_krw);
  return item.price_confidence === "estimated" ? `추정 ${price}` : price;
}

/** 군집 라벨 — 개수(주인공)와 중위가. 중위가 없으면 개수만. */
export function clusterMarkerLines(c: ClusterItem): string[] {
  const lines = [`${c.count}`];
  if (c.median_price_krw !== null) lines.push(`중위 ${formatKrwShort(c.median_price_krw)}`);
  return lines;
}

/**
 * 라벨 DOM 생성 — **innerHTML 금지, textContent 만 사용**(XSS 방지).
 * 각 줄을 span 으로 쌓아 CSS 로 위계를 준다(숫자가 주인공).
 */
export function buildLabelEl(doc: Document, className: string, lines: string[]): HTMLElement {
  const el = doc.createElement("div");
  el.className = className;
  lines.forEach((line, i) => {
    const row = doc.createElement("span");
    row.className = i === 0 ? "map-pill__value" : "map-pill__sub";
    row.textContent = line; // ← 브라우저가 이스케이프한다
    el.appendChild(row);
  });
  return el;
}

/* 카카오 SDK 를 느슨하게 타입핑한다(전용 타입 패키지를 쓰지 않는다).
 * 테스트는 이 형태의 목을 주입한다. */
export interface KakaoLike {
  maps: {
    LatLng: new (lat: number, lng: number) => unknown;
    CustomOverlay: new (opts: Record<string, unknown>) => KakaoOverlay;
  };
}

export interface KakaoOverlay {
  setMap(map: unknown | null): void;
}

export interface KakaoMap {
  panTo?(latlng: unknown): void;
}

export interface ComplexLayerOpts {
  selectedId?: number | null;
  rankById?: Record<number, number>;
  onSelect?: (id: number) => void;
}

interface Tracked {
  overlay: KakaoOverlay;
  el: HTMLElement;
  handler: (e: Event) => void;
  keyHandler: (e: KeyboardEvent) => void;
}

/**
 * 지도 위 마커/군집 오버레이의 생성·교체·정리를 관리한다.
 * setComplexes / setClusters 는 각각 자기 레이어를 먼저 비우고 다시 그린다.
 */
export class MarkerLayer {
  private kakao: KakaoLike;
  private map: KakaoMap;
  private doc: Document;

  private complexes: Tracked[] = [];
  private clusters: Tracked[] = [];

  /**
   * 마지막으로 지도를 이동시킨 선택 단지 id (CR18-1).
   * setComplexes 는 items 가 바뀔 때마다(= 지도를 끌 때마다) 호출되므로,
   * "선택이 실제로 바뀐 순간"에만 panTo 하려면 직전 값을 기억해야 한다.
   */
  private lastPannedId: number | null = null;

  constructor(deps: { kakao: KakaoLike; map: KakaoMap; doc?: Document }) {
    this.kakao = deps.kakao;
    this.map = deps.map;
    this.doc = deps.doc ?? document;
  }

  private latLng(point: [number, number]) {
    // 우리 좌표 규약은 [경도, 위도]. 카카오 LatLng 은 (위도, 경도) 순서다.
    return new this.kakao.maps.LatLng(point[1], point[0]);
  }

  private attach(el: HTMLElement, onActivate: () => void): Pick<Tracked, "handler" | "keyHandler"> {
    // 지도 위 pill 도 탭·키보드로 조작 가능해야 한다(지도 자체는 스크린리더로 못 읽지만
    // 대체 경로인 목록과 별개로, 마우스·터치·키보드 조작은 열어둔다).
    el.setAttribute("role", "button");
    el.tabIndex = 0;
    const handler = (e: Event) => {
      e.stopPropagation();
      onActivate();
    };
    const keyHandler = (e: KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onActivate();
      }
    };
    el.addEventListener("click", handler);
    el.addEventListener("keydown", keyHandler);
    return { handler, keyHandler };
  }

  setComplexes(items: ComplexItem[], opts: ComplexLayerOpts = {}): void {
    this.clearComplexes();
    const { kakao, map } = this;

    for (const item of items) {
      const rank = opts.rankById?.[item.id];
      const selected = opts.selectedId != null && opts.selectedId === item.id;

      const lines: string[] = [];
      if (rank) lines.push(`${rank}위`);
      lines.push(complexMarkerText(item));

      const cls =
        "map-pill map-pill--complex" +
        (selected ? " map-pill--selected" : "") +
        (item.over_budget ? " map-pill--over" : "") +
        (item.price_confidence === "estimated" ? " map-pill--est" : "");

      const el = buildLabelEl(this.doc, cls, lines);
      el.setAttribute("aria-label", `${item.name} ${lines.join(" ")}`);
      const { handler, keyHandler } = this.attach(el, () => opts.onSelect?.(item.id));

      const overlay = new kakao.maps.CustomOverlay({
        position: this.latLng(item.point),
        content: el,
        yAnchor: 1.35,
        clickable: true,
        zIndex: selected ? 100 : rank ? 50 : 10,
      });
      overlay.setMap(map);
      this.complexes.push({ overlay, el, handler, keyHandler });
    }

    this.syncFocus(items, opts.selectedId ?? null);
  }

  /**
   * 선택된 단지로 지도를 이동시킨다 — **선택이 바뀐 경우에만**(CR18-1).
   *
   * 왜 조건이 필요한가: 예전엔 그릴 때마다 panTo 했다. 그런데 마커를 탭한 뒤 지도를 조금 끌면
   * idle → 조회 → setItems → 이 함수 → panTo 로 **지도가 원래 자리로 되감겼다**.
   * 되감김이 다시 idle 을 유발해 팬 1회에 서버 조회가 2회 나갔다(디바운스 절약분 상쇄).
   * 이제 lastPannedId 와 다를 때만 움직인다 — "리스트 카드 탭 → 지도 이동"(ux §3)은 그대로다.
   */
  private syncFocus(items: ComplexItem[], selectedId: number | null): void {
    if (selectedId === null) {
      // 선택 해제 → 같은 단지를 다시 고르면 그때는 이동해야 하므로 기억을 지운다.
      this.lastPannedId = null;
      return;
    }
    // 핵심 가드: 이미 그 단지로 이동해 뒀으면 다시 움직이지 않는다(되감김 방지).
    if (selectedId === this.lastPannedId) return;

    const sel = items.find((i) => i.id === selectedId);
    // 선택 단지가 이번 응답에 없으면(범위 밖) 이동하지 않는다. 기억도 남기지 않아
    // 나중에 다시 들어왔을 때 한 번은 이동한다.
    if (!sel || typeof this.map.panTo !== "function") return;

    this.map.panTo(this.latLng(sel.point));
    this.lastPannedId = selectedId;
  }

  setClusters(clusters: ClusterItem[], onSelect?: (c: ClusterItem) => void): void {
    this.clearClusters();
    const { kakao, map } = this;

    for (const c of clusters) {
      const el = buildLabelEl(this.doc, "map-pill map-pill--cluster", clusterMarkerLines(c));
      el.setAttribute("aria-label", `${c.count}개 단지 지역, 확대하려면 선택`);
      const { handler, keyHandler } = this.attach(el, () => onSelect?.(c));

      const overlay = new kakao.maps.CustomOverlay({
        position: this.latLng(c.center),
        content: el,
        yAnchor: 0.5,
        xAnchor: 0.5,
        clickable: true,
        zIndex: 5,
      });
      overlay.setMap(map);
      this.clusters.push({ overlay, el, handler, keyHandler });
    }
  }

  private detach(t: Tracked): void {
    t.el.removeEventListener("click", t.handler);
    t.el.removeEventListener("keydown", t.keyHandler);
    t.overlay.setMap(null);
  }

  private clearComplexes(): void {
    for (const t of this.complexes) this.detach(t);
    this.complexes = [];
  }

  private clearClusters(): void {
    for (const t of this.clusters) this.detach(t);
    this.clusters = [];
  }

  destroy(): void {
    this.clearComplexes();
    this.clearClusters();
    this.lastPannedId = null;
  }
}
