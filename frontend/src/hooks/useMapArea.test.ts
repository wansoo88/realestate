// @vitest-environment jsdom
/**
 * 지도 조회가 **내 조건을 실제로 들고 나가는지** 못박는다.
 * (조건이 화면에만 있고 요청에 안 실리면 사용자는 필터가 작동한다고 착각한다)
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { api } from "../api/client";
import type { MapFilterState } from "../lib/mapFilters";
import { MAP_DEBOUNCE_MS, useMapArea } from "./useMapArea";

const EMPTY = { level: "complex" as const, items: [], note: "" };

const FILTERS: MapFilterState = {
  budgetKrw: 850_000_000,
  budgetApplied: true,
  prefer: { built_after: 2010 },
  preferApplied: true,
  purpose: "live",
};

let spy: MockInstance<typeof api.mapComplexes>;

beforeEach(() => {
  vi.useFakeTimers();
  spy = vi.spyOn(api, "mapComplexes").mockResolvedValue(EMPTY);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

async function tick(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("useMapArea", () => {
  it("디바운스 전에는 요청하지 않고, 마지막 이동만 보낸다", async () => {
    const { result } = renderHook(() => useMapArea(FILTERS));

    act(() => {
      result.current.onBoundsChange("1,2,3,4", 15);
      result.current.onBoundsChange("5,6,7,8", 15);
    });
    expect(spy).not.toHaveBeenCalled();

    await tick(MAP_DEBOUNCE_MS);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy.mock.calls[0][0]).toMatchObject({ bbox: "5,6,7,8" });
  });

  it("내 예산과 선호가 요청 파라미터로 나간다 — 예산은 **금액이 아니라 플래그**(SR32-1)", async () => {
    const { result } = renderHook(() => useMapArea(FILTERS));
    act(() => result.current.onBoundsChange("1,2,3,4", 15));
    await tick(MAP_DEBOUNCE_MS);

    expect(spy.mock.calls[0][0]).toMatchObject({
      budget: "mine", // 8.5억이 아니다 — 상한은 서버가 저장된 프로필로 만든다
      built_after: 2010,
    });
  });

  /**
   * 서버가 말한 예산 기준(`budget` 블록)을 **응답마다 새로 쓴다**.
   *
   * 옛 값을 이어받으면(`res.budget ?? 이전값`) 서버가 말을 멈춘 뒤에도 화면이 지난
   * 응답의 "적용됨"을 계속 말한다 — 조건이 풀렸는데 걸린 것처럼 보이는 상태다.
   */
  it("예산 블록을 응답마다 갈아끼운다(옛 값을 물려주지 않는다)", async () => {
    spy.mockResolvedValueOnce({
      ...EMPTY,
      budget: { applied: true, basis: "target_price", reason: null },
    });
    const { result } = renderHook(() => useMapArea(FILTERS));

    act(() => result.current.onBoundsChange("1,2,3,4", 15));
    await tick(MAP_DEBOUNCE_MS);
    expect(result.current.budget).toEqual({
      applied: true,
      basis: "target_price",
      reason: null,
    });

    // 다음 응답에는 블록이 없다 → **모름**으로 되돌아간다("적용됨"이 남으면 안 된다)
    act(() => result.current.onBoundsChange("5,6,7,8", 15));
    await tick(MAP_DEBOUNCE_MS);
    expect(result.current.budget).toBeNull();
  });

  it("예산 스위치를 끄면 **같은 화면 범위로 즉시 다시 조회**하고 예산이 빠진다", async () => {
    const { result, rerender } = renderHook((f: MapFilterState) => useMapArea(f), {
      initialProps: FILTERS,
    });
    act(() => result.current.onBoundsChange("1,2,3,4", 15));
    await tick(MAP_DEBOUNCE_MS);
    expect(spy).toHaveBeenCalledTimes(1);

    rerender({ ...FILTERS, budgetApplied: false });
    await tick(1); // 디바운스를 기다리지 않는다(사용자가 방금 스위치를 눌렀다)

    expect(spy).toHaveBeenCalledTimes(2);
    const second = spy.mock.calls[1][0] as Record<string, unknown>;
    expect(second.bbox).toBe("1,2,3,4"); // 범위는 그대로
    expect(second.budget).toBeUndefined();
  });

  /**
   * SR32-1 이후 생긴 함정: 쿼리에는 금액이 없고 `budget=mine` 플래그만 실린다.
   * 그래서 **쿼리로만 변경을 감지하면** 희망가를 바꿔도 요청이 한 글자도 안 달라져
   * 지도가 옛 결과 그대로 남는다(서버가 산출할 상한은 바뀌었는데 화면은 모른다).
   */
  it("희망가를 바꾸면 쿼리가 같아도 다시 조회한다(금액을 안 보내기 때문에 필요한 검사)", async () => {
    const { result, rerender } = renderHook((f: MapFilterState) => useMapArea(f), {
      initialProps: { ...FILTERS, targetPriceKrw: 900_000_000 },
    });
    act(() => result.current.onBoundsChange("1,2,3,4", 15));
    await tick(MAP_DEBOUNCE_MS);
    expect(spy).toHaveBeenCalledTimes(1);

    rerender({ ...FILTERS, targetPriceKrw: 700_000_000 });
    await tick(1);

    expect(spy).toHaveBeenCalledTimes(2);
    // 요청 자체는 이전과 **같다**(금액이 안 실리므로) — 그래도 다시 물어봐야 한다
    expect(spy.mock.calls[1][0]).toEqual(spy.mock.calls[0][0]);
  });

  it("필터 객체가 새로 만들어져도 내용이 같으면 재조회하지 않는다(무한 루프 방지)", async () => {
    const { result, rerender } = renderHook((f: MapFilterState) => useMapArea(f), {
      initialProps: { ...FILTERS },
    });
    act(() => result.current.onBoundsChange("1,2,3,4", 15));
    await tick(MAP_DEBOUNCE_MS);

    rerender({ ...FILTERS, prefer: { built_after: 2010 } }); // 새 객체, 같은 내용
    await tick(10);

    expect(spy).toHaveBeenCalledTimes(1);
  });

  /**
   * "이 주변에서 찾기"는 이 훅이 들고 있는 범위를 그대로 쓴다(화면이 다시 계산하지 않는다).
   * 그래서 범위가 **밖에서 읽히고**, 조회 응답에 덮여 사라지지 않아야 한다.
   */
  describe("현재 지도 범위 노출", () => {
    it("지도를 움직이기 전에는 범위가 없다(= 아직 준비 안 됨)", () => {
      const { result } = renderHook(() => useMapArea(FILTERS));
      expect(result.current.bbox).toBeNull();
    });

    it("디바운스를 기다리지 않고 즉시 반영된다(버튼이 늦게 켜지면 안 된다)", () => {
      const { result } = renderHook(() => useMapArea(FILTERS));
      act(() => result.current.onBoundsChange("1,2,3,4", 15));
      expect(result.current.bbox).toBe("1,2,3,4");
      expect(spy).not.toHaveBeenCalled(); // 조회는 여전히 디바운스된다
    });

    it("조회 응답이 도착해도 범위를 덮어 지우지 않는다", async () => {
      const { result } = renderHook(() => useMapArea(FILTERS));
      act(() => result.current.onBoundsChange("1,2,3,4", 15));
      await tick(MAP_DEBOUNCE_MS);

      expect(spy).toHaveBeenCalledTimes(1);
      expect(result.current.bbox).toBe("1,2,3,4");
      expect(result.current.level).toBe("complex"); // 응답도 정상 반영됐다
    });

    it("마지막으로 본 범위를 들고 있는다", async () => {
      const { result } = renderHook(() => useMapArea(FILTERS));
      act(() => {
        result.current.onBoundsChange("1,2,3,4", 15);
        result.current.onBoundsChange("5,6,7,8", 15);
      });
      expect(result.current.bbox).toBe("5,6,7,8");
    });
  });

  it("지도를 아직 안 움직였으면 조건이 바뀌어도 요청하지 않는다(bbox 없는 호출 금지)", async () => {
    const { rerender } = renderHook((f: MapFilterState) => useMapArea(f), {
      initialProps: FILTERS,
    });
    rerender({ ...FILTERS, budgetApplied: false });
    await tick(10);
    expect(spy).not.toHaveBeenCalled();
  });
});
