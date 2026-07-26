// @vitest-environment jsdom
/**
 * 마커 레이어 **성능 계측** — "빨라졌다"가 아니라 숫자로 남긴다.
 *
 * 기준선(직전 라운드 실측): 같은 목록 재조회 0.79ms · 팬 1회 5.43ms (500개 기준).
 * 이번 라운드에서 표현 단계(dot/price/detail)와 hover/muted 를 추가했으므로,
 * **재사용 경로가 그대로인지**를 여기서 확인한다. 단언은 넉넉한 상한으로 두고
 * (CI 머신 성능은 흔들린다), 정확한 값은 콘솔로 출력해 보고서에 옮긴다.
 *
 * ⚠️ 이 파일은 회귀 **탐지**용이지 최적화 목표가 아니다. 임계를 빡빡하게 잡으면
 *    느린 머신에서 무작위로 실패하는 테스트가 되어 아무도 안 믿게 된다.
 */
import { describe, expect, it } from "vitest";
import type { ComplexItem } from "../api/client";
import { MarkerLayer, type KakaoLike } from "./mapMarkers";

function mockKakao() {
  class LatLng {
    constructor(public lat: number, public lng: number) {}
  }
  class CustomOverlay {
    constructor(public opts: any) {
      created += 1;
    }
    setMap() {}
    setZIndex() {}
    setPosition() {}
  }
  let created = 0;
  return {
    kakao: { maps: { LatLng, CustomOverlay } } as unknown as KakaoLike,
    overlaysCreated: () => created,
  };
}

function complexRange(from: number, to: number): ComplexItem[] {
  const out: ComplexItem[] = [];
  for (let id = from; id <= to; id += 1) {
    out.push({
      id,
      name: `단지${id}`,
      point: [127 + id * 0.001, 37.5],
      households: 500,
      built_year: 2005,
      recent_price_krw: 840_000_000 + id * 1_000_000,
      price_as_of: "2026-06-30",
      price_confidence: "estimated",
      active_listings: 1,
      over_budget: false,
    });
  }
  return out;
}

/** 여러 번 재서 중앙값을 쓴다 — 한 번은 GC 한 방에 흔들린다. */
function median(run: () => void, times = 9): number {
  const samples: number[] = [];
  for (let i = 0; i < times; i += 1) {
    const t0 = performance.now();
    run();
    samples.push(performance.now() - t0);
  }
  samples.sort((a, b) => a - b);
  return samples[Math.floor(samples.length / 2)];
}

describe("MarkerLayer 성능 (500개 기준)", () => {
  it("같은 목록 재조회 — DOM 을 만들지 않으므로 1ms 언저리여야 한다", () => {
    const { kakao, overlaysCreated } = mockKakao();
    const layer = new MarkerLayer({ kakao, map: {}, doc: document });
    layer.setComplexes(complexRange(1, 500), { tier: "price" });
    const afterFirst = overlaysCreated();

    // App 은 조회할 때마다 **새 배열·새 객체**를 넣는다 — 그 상황 그대로.
    const ms = median(() => layer.setComplexes(complexRange(1, 500), { tier: "price" }));

    expect(overlaysCreated()).toBe(afterFirst); // 신규 오버레이 0 = 재사용률 100%
    expect(ms).toBeLessThan(8);
    console.log(`[perf] 같은 목록 재조회: ${ms.toFixed(2)}ms (기준선 0.79ms)`);
  });

  it("팬 1회(80% 겹침) — 겹치는 400개는 재사용된다", () => {
    const { kakao } = mockKakao();
    const layer = new MarkerLayer({ kakao, map: {}, doc: document });
    layer.setComplexes(complexRange(1, 500), { tier: "price" });

    let offset = 0;
    const ms = median(() => {
      offset += 100;
      layer.setComplexes(complexRange(1 + offset, 500 + offset), { tier: "price" });
    });

    expect(ms).toBeLessThan(30);
    console.log(`[perf] 팬 1회(100개 교체): ${ms.toFixed(2)}ms (기준선 5.43ms)`);
  });

  it("선택 변경 — 클래스 두 개만 바뀐다(전량 순회여도 DOM 쓰기는 2회)", () => {
    const { kakao } = mockKakao();
    const layer = new MarkerLayer({ kakao, map: {}, doc: document });
    const items = complexRange(1, 500);
    layer.setComplexes(items, { tier: "price" });

    let n = 0;
    const ms = median(() => {
      n += 1;
      layer.setComplexes(items, { tier: "price", selectedId: (n % 500) + 1 });
    });

    expect(ms).toBeLessThan(30);
    console.log(`[perf] 선택 변경: ${ms.toFixed(2)}ms`);
  });

  it("hover 이동 — 목록을 훑는 동안 매 프레임 도는 경로", () => {
    const { kakao } = mockKakao();
    const layer = new MarkerLayer({ kakao, map: {}, doc: document });
    const items = complexRange(1, 500);
    layer.setComplexes(items, { tier: "price" });

    let n = 0;
    const ms = median(() => {
      n += 1;
      layer.setComplexes(items, { tier: "price", hoveredId: (n % 500) + 1 });
    });

    expect(ms).toBeLessThan(30);
    console.log(`[perf] hover 이동: ${ms.toFixed(2)}ms`);
  });

  it("밀집 강등 전이(price→dot) — 줌을 넘길 때 한 번 도는 경로", () => {
    const { kakao, overlaysCreated } = mockKakao();
    const layer = new MarkerLayer({ kakao, map: {}, doc: document });
    const items = complexRange(1, 500);
    layer.setComplexes(items, { tier: "price" });
    const afterFirst = overlaysCreated();

    let toggle = false;
    const ms = median(() => {
      toggle = !toggle;
      layer.setComplexes(items, { tier: toggle ? "dot" : "price" });
    });

    // 앵커를 단계마다 바꿨다면 여기서 오버레이가 500개씩 새로 생겼을 것이다.
    expect(overlaysCreated()).toBe(afterFirst);
    expect(ms).toBeLessThan(60);
    console.log(`[perf] 단계 전이 price↔dot: ${ms.toFixed(2)}ms`);
  });
});
