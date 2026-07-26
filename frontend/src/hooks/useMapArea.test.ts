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

  it("내 예산과 선호가 요청 파라미터로 나간다", async () => {
    const { result } = renderHook(() => useMapArea(FILTERS));
    act(() => result.current.onBoundsChange("1,2,3,4", 15));
    await tick(MAP_DEBOUNCE_MS);

    expect(spy.mock.calls[0][0]).toMatchObject({
      max_price_krw: 850_000_000,
      built_after: 2010,
    });
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
    expect(second.max_price_krw).toBeUndefined();
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
