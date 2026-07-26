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
  fillLabelEl(doc, el, lines);
  return el;
}

/** 줄 span 을 채운다(생성·재구성 공용). textContent 만 쓴다. */
function fillLabelEl(doc: Document, el: HTMLElement, lines: string[]): void {
  lines.forEach((line, i) => {
    const row = doc.createElement("span");
    row.className = i === 0 ? "map-pill__value" : "map-pill__sub";
    row.textContent = line; // ← 브라우저가 이스케이프한다
    el.appendChild(row);
  });
}

/**
 * 이미 만들어진 라벨의 **텍스트만 갈아끼운다**(CR18-7 재사용 경로).
 *
 * 줄 수가 같으면(대부분) span 을 새로 만들지 않고 textContent 만 바꾼다 — 요소 생성 0.
 * 줄 수가 달라질 때만(순위 배지가 생기거나 사라질 때) 그 마커 하나를 다시 채운다.
 * ⚠️ 여기서도 innerHTML 을 쓰지 않는다. 재사용 경로가 XSS 우회로가 되면 안 된다.
 */
export function patchLabelEl(doc: Document, el: HTMLElement, lines: string[]): void {
  const rows = el.children;
  if (rows.length === lines.length) {
    for (let i = 0; i < lines.length; i += 1) {
      const row = rows[i] as HTMLElement;
      if (row.textContent !== lines[i]) row.textContent = lines[i]; // ← 이스케이프됨
    }
    return;
  }
  el.textContent = ""; // 자식 제거(innerHTML="" 대신)
  fillLabelEl(doc, el, lines);
}

function sameLines(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) if (a[i] !== b[i]) return false;
  return true;
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
  /* 재사용 시 위치·z-order 만 고쳐 쓰기 위한 실제 CustomOverlay API.
   * 오래된 SDK/축소된 목에서 없을 수 있으므로 옵셔널로 두고 호출부에서 가드한다. */
  setPosition?(latlng: unknown): void;
  setZIndex?(zIndex: number): void;
}

export interface KakaoMap {
  panTo?(latlng: unknown): void;
}

export interface ComplexLayerOpts {
  selectedId?: number | null;
  rankById?: Record<number, number>;
  onSelect?: (id: number) => void;
}

/**
 * "이번 갱신에 이 마커가 어떻게 보여야 하는가" — 신규 생성과 재사용(patch)이
 * **같은 스펙**을 쓰게 해서 두 경로의 결과가 어긋나지 않게 한다.
 */
interface MarkerSpec {
  lines: string[];
  className: string;
  ariaLabel: string;
  zIndex: number;
  point: [number, number];
  yAnchor: number;
  xAnchor?: number;
  /** 탭·Enter 시 실행할 동작. 갱신마다 새 클로저가 오지만 리스너는 재부착하지 않는다. */
  activate: () => void;
}

interface Tracked {
  overlay: KakaoOverlay;
  el: HTMLElement;
  handler: (e: Event) => void;
  keyHandler: (e: KeyboardEvent) => void;
  /**
   * 리스너가 참조하는 **가변 상자**. 콜백이 바뀌어도 상자 안의 함수만 갈아끼우면 되므로
   * removeEventListener/addEventListener 를 다시 하지 않는다(리스너 재부착 0).
   * 상자 없이 클로저를 직접 잡으면 재사용 마커가 **옛 콜백**을 부른다 — 테스트로 못박았다.
   */
  cb: { activate: () => void };
  /* 마지막으로 그린 상태. 달라진 것만 DOM/오버레이에 반영한다. */
  lines: string[];
  className: string;
  ariaLabel: string;
  zIndex: number;
  point: [number, number];
}

/**
 * 지도 위 마커/군집 오버레이의 생성·재사용·정리를 관리한다.
 *
 * ⚡ CR18-7 — **id 기준 diff**. 예전엔 갱신마다 전량 파괴 후 재생성했다:
 * 상한 500개 기준 팬 1회에 요소 1,000개 생성 + addEventListener 1,000회 + 오버레이 500개
 * 재생성. 밀집 지역(강남·송파는 한 화면에 수백 개)에서 팬마다 프레임이 끊긴다.
 * 이제 살아남은 마커는 **DOM·리스너·오버레이를 그대로 두고 달라진 속성만 고쳐 쓰고**,
 * 사라진 것만 떼어내고 새로 생긴 것만 만든다. 겹치는 구간의 재생성 비용이 0이 된다.
 */
export class MarkerLayer {
  private kakao: KakaoLike;
  private map: KakaoMap;
  private doc: Document;

  /* 배열이 아니라 Map(key→마커) 이다. 갱신 때 O(1) 로 이전 마커를 찾아야 diff 가 성립한다. */
  private complexes = new Map<number, Tracked>();
  private clusters = new Map<string, Tracked>();

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

  /** 신규 마커 1개 생성 — 요소 2~3개 + 리스너 2개. 여기가 유일한 생성 지점이다. */
  private create(spec: MarkerSpec): Tracked {
    const el = buildLabelEl(this.doc, spec.className, spec.lines);
    el.setAttribute("aria-label", spec.ariaLabel);
    // 지도 위 pill 도 탭·키보드로 조작 가능해야 한다(지도 자체는 스크린리더로 못 읽지만
    // 대체 경로인 목록과 별개로, 마우스·터치·키보드 조작은 열어둔다).
    el.setAttribute("role", "button");
    el.tabIndex = 0;

    const cb = { activate: spec.activate };
    const handler = (e: Event) => {
      e.stopPropagation();
      cb.activate();
    };
    const keyHandler = (e: KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        cb.activate();
      }
    };
    el.addEventListener("click", handler);
    el.addEventListener("keydown", keyHandler);

    const overlay = new this.kakao.maps.CustomOverlay({
      position: this.latLng(spec.point),
      content: el,
      yAnchor: spec.yAnchor,
      ...(spec.xAnchor === undefined ? {} : { xAnchor: spec.xAnchor }),
      clickable: true,
      zIndex: spec.zIndex,
    });
    overlay.setMap(this.map);

    return {
      overlay,
      el,
      handler,
      keyHandler,
      cb,
      lines: spec.lines,
      className: spec.className,
      ariaLabel: spec.ariaLabel,
      zIndex: spec.zIndex,
      point: spec.point,
    };
  }

  /** 살아남은 마커 갱신 — **달라진 것만** 건드린다. 아무것도 안 바뀌면 DOM 접근이 0회다. */
  private patch(t: Tracked, spec: MarkerSpec): void {
    if (t.className !== spec.className) {
      t.el.className = spec.className;
      t.className = spec.className;
    }
    if (!sameLines(t.lines, spec.lines)) {
      patchLabelEl(this.doc, t.el, spec.lines);
      t.lines = spec.lines;
    }
    if (t.ariaLabel !== spec.ariaLabel) {
      t.el.setAttribute("aria-label", spec.ariaLabel);
      t.ariaLabel = spec.ariaLabel;
    }
    if (t.zIndex !== spec.zIndex) {
      t.overlay.setZIndex?.(spec.zIndex);
      t.zIndex = spec.zIndex;
    }
    // 단지 좌표는 보통 고정이지만 군집 중심은 재계산되어 움직인다.
    if (t.point[0] !== spec.point[0] || t.point[1] !== spec.point[1]) {
      t.overlay.setPosition?.(this.latLng(spec.point));
      t.point = spec.point;
    }
    // 콜백은 항상 최신으로(리스너는 그대로 둔 채 상자 안만 교체).
    t.cb.activate = spec.activate;
  }

  /**
   * 키(단지 id / 군집 region_code) 기준 diff 의 공통 몸통.
   * 이전 Map 에서 꺼내 쓰고(=재사용), 끝까지 안 꺼내진 것만 제거한다.
   */
  private reconcile<K, T>(
    prev: Map<K, Tracked>,
    items: T[],
    keyOf: (item: T) => K,
    specOf: (item: T) => MarkerSpec,
  ): Map<K, Tracked> {
    const next = new Map<K, Tracked>();

    for (const item of items) {
      const key = keyOf(item);
      // 같은 응답에 키가 중복되면(방어) 뒤엣것을 버린다 — 안 버리면 오버레이가 새어나간다.
      if (next.has(key)) continue;

      const found = prev.get(key);
      if (found) {
        prev.delete(key); // prev 에 남는 것 = 이번에 사라진 마커
        this.patch(found, specOf(item));
        next.set(key, found);
        continue;
      }
      next.set(key, this.create(specOf(item)));
    }

    for (const t of prev.values()) this.detach(t); // 사라진 것만 정리
    return next;
  }

  setComplexes(items: ComplexItem[], opts: ComplexLayerOpts = {}): void {
    this.complexes = this.reconcile(
      this.complexes,
      items,
      (item) => item.id,
      (item) => {
        const rank = opts.rankById?.[item.id];
        const selected = opts.selectedId != null && opts.selectedId === item.id;

        const lines: string[] = [];
        if (rank) lines.push(`${rank}위`);
        lines.push(complexMarkerText(item));

        return {
          lines,
          className:
            "map-pill map-pill--complex" +
            (selected ? " map-pill--selected" : "") +
            (item.over_budget ? " map-pill--over" : "") +
            (item.price_confidence === "estimated" ? " map-pill--est" : ""),
          ariaLabel: `${item.name} ${lines.join(" ")}`,
          zIndex: selected ? 100 : rank ? 50 : 10,
          point: item.point,
          yAnchor: 1.35,
          activate: () => opts.onSelect?.(item.id),
        };
      },
    );

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
    // 군집도 같은 diff 를 탄다. 키는 region_code — 줌 단계가 그대로면 대부분 재사용된다.
    this.clusters = this.reconcile(
      this.clusters,
      clusters,
      (c) => c.region_code,
      (c) => ({
        lines: clusterMarkerLines(c),
        className: "map-pill map-pill--cluster",
        ariaLabel: `${c.count}개 단지 지역, 확대하려면 선택`,
        zIndex: 5,
        point: c.center,
        yAnchor: 0.5,
        xAnchor: 0.5,
        activate: () => onSelect?.(c),
      }),
    );
  }

  private detach(t: Tracked): void {
    t.el.removeEventListener("click", t.handler);
    t.el.removeEventListener("keydown", t.keyHandler);
    t.overlay.setMap(null);
  }

  private clear<K>(layer: Map<K, Tracked>): void {
    for (const t of layer.values()) this.detach(t);
    layer.clear();
  }

  destroy(): void {
    this.clear(this.complexes);
    this.clear(this.clusters);
    this.lastPannedId = null;
  }
}
