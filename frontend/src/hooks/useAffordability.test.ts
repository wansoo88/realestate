// @vitest-environment jsdom
/**
 * 희망가가 **실제로 서버 요청에 실리는지**, 그리고 단지를 훑을 때 요청이 폭주하지 않는지.
 *
 * 이 훅에서 조용히 깨지기 쉬운 두 지점을 고정한다.
 *  ① 첫 조회는 **즉시** — 화면을 여는 순간의 지연은 "느린 앱"으로 보인다.
 *  ② 그 뒤 값 변경은 **디바운스** — 마커를 훑으며 클릭하면 요청이 클릭 수만큼 나간다.
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiException, api, type AffordabilityResponse } from "../api/client";
import { AFFORD_DEBOUNCE_MS, useAffordability } from "./useAffordability";

const RES: AffordabilityResponse = {
  max_purchase_krw: 850_000_000,
  breakdown: {
    own_cash_krw: 300_000_000,
    max_loan_krw: 550_000_000,
    binding_constraint: "DSR",
  },
  acquisition_cost_krw: {
    tax: 9_350_000,
    brokerage: 5_100_000,
    registration: 1_000_000,
    total: 15_450_000,
  },
  assumptions: [],
  evidence: [],
  warnings: [],
  disclaimer: "…",
};

let spy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  vi.useFakeTimers();
  spy = vi.spyOn(api, "affordability").mockResolvedValue(RES) as never;
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

describe("useAffordability", () => {
  it("첫 조회는 기다리지 않는다", async () => {
    renderHook(() => useAffordability(true, "live", null));
    await act(async () => {});

    expect(spy).toHaveBeenCalledTimes(1);
    // 희망가가 없으면 **키 자체를 보내지 않는다**(0 이나 null 을 서버가 예산으로 읽지 않게)
    expect("target_price_krw" in (spy.mock.calls[0][0] as object)).toBe(false);
  });

  it("희망가가 있으면 target_price_krw 로 실어 보낸다", async () => {
    renderHook(() => useAffordability(true, "live", 900_000_000));
    await act(async () => {});

    expect(spy).toHaveBeenCalledWith({ purpose: "live", target_price_krw: 900_000_000 });
  });

  it("값이 연속으로 바뀌면 **마지막 하나만** 나간다", async () => {
    const { rerender } = renderHook(({ t }) => useAffordability(true, "live", t), {
      initialProps: { t: null as number | null },
    });
    await act(async () => {});
    expect(spy).toHaveBeenCalledTimes(1);

    rerender({ t: 800_000_000 });
    rerender({ t: 900_000_000 });
    rerender({ t: 1_000_000_000 });
    await tick(AFFORD_DEBOUNCE_MS - 1);
    expect(spy).toHaveBeenCalledTimes(1); // 아직 아무것도 안 나갔다

    await tick(2);
    expect(spy).toHaveBeenCalledTimes(2);
    expect(spy.mock.calls[1][0]).toMatchObject({ target_price_krw: 1_000_000_000 });
  });

  it("자산이 없으면(422) 에러가 아니라 '먼저 입력하세요' 신호다", async () => {
    spy.mockRejectedValue(
      new ApiException(422, { code: "INSUFFICIENT_DATA", message: "자산 없음" }),
    );

    const { result } = renderHook(() => useAffordability(true, "live", null));
    await act(async () => {});

    expect(result.current.needsProfile).toBe(true);
    expect(result.current.error).toBeNull();
  });

  it("enabled 가 false 면 아예 부르지 않는다(자산 없이 422 를 일부러 받지 않는다)", async () => {
    renderHook(() => useAffordability(false, "live", 900_000_000));
    await tick(AFFORD_DEBOUNCE_MS * 3);

    expect(spy).not.toHaveBeenCalled();
  });

  it("늦게 온 응답이 최신 결과를 덮지 않는다", async () => {
    let resolveFirst: (v: AffordabilityResponse) => void = () => {};
    spy
      .mockImplementationOnce(
        () => new Promise<AffordabilityResponse>((r) => (resolveFirst = r)) as never,
      )
      .mockResolvedValue({ ...RES, max_purchase_krw: 999 } as never);

    const { result, rerender } = renderHook(({ t }) => useAffordability(true, "live", t), {
      initialProps: { t: null as number | null },
    });
    await act(async () => {});

    rerender({ t: 900_000_000 });
    await tick(AFFORD_DEBOUNCE_MS + 1);
    expect(result.current.data?.max_purchase_krw).toBe(999);

    // 이제서야 도착한 첫 응답은 버려진다
    await act(async () => {
      resolveFirst(RES);
    });
    expect(result.current.data?.max_purchase_krw).toBe(999);
  });
});
