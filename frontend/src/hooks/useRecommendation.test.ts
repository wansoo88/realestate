// @vitest-environment jsdom
/**
 * 추천 실행 → 폴링 → 완료 상태 전이.
 *
 * 가장 위험한 실패는 크래시가 아니라 **'분석 중'에서 영영 멈추는 화면**이다.
 * 그래서 완료·실패·시간초과 셋 중 하나로 반드시 끝나는지 못박는다.
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiException, api, type RecommendationJob } from "../api/client";
import { POLL_INTERVAL_MS, POLL_TIMEOUT_MS, useRecommendation } from "./useRecommendation";

const ACCEPTED = {
  job_id: "rec_abc123",
  status: "queued",
  poll_url: "/api/v1/recommendations/rec_abc123",
};

function job(status: string, items: RecommendationJob["items"] = []): RecommendationJob {
  return { job_id: "rec_abc123", status, items };
}

beforeEach(() => {
  vi.useFakeTimers();
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

describe("useRecommendation", () => {
  it("queued → running → done 으로 전이하고 결과를 담는다", async () => {
    vi.spyOn(api, "createRecommendation").mockResolvedValue(ACCEPTED);
    const poll = vi
      .spyOn(api, "recommendation")
      .mockResolvedValueOnce(job("running"))
      .mockResolvedValueOnce(job("done", [{ complex: { id: 1, name: "A" } } as never]));

    const { result } = renderHook(() => useRecommendation());
    await act(async () => {
      await result.current.start({ purpose: "live" });
    });

    // 검증된 poll_url 을 BASE 제거한 경로로 쓴다
    expect(poll).toHaveBeenCalledWith("/recommendations/rec_abc123");
    expect(result.current.phase).toBe("running");

    await tick(POLL_INTERVAL_MS);
    expect(result.current.phase).toBe("done");
    expect(result.current.job?.items).toHaveLength(1);
  });

  it("완료되면 폴링을 멈춘다(끝난 작업을 계속 두드리지 않는다)", async () => {
    vi.spyOn(api, "createRecommendation").mockResolvedValue(ACCEPTED);
    const poll = vi.spyOn(api, "recommendation").mockResolvedValue(job("done"));

    const { result } = renderHook(() => useRecommendation());
    await act(async () => {
      await result.current.start({});
    });
    await tick(POLL_INTERVAL_MS * 5);

    expect(poll).toHaveBeenCalledTimes(1);
    expect(result.current.phase).toBe("done");
  });

  it("서버가 error 를 주면 사용자에게 알리고 멈춘다", async () => {
    vi.spyOn(api, "createRecommendation").mockResolvedValue(ACCEPTED);
    vi.spyOn(api, "recommendation").mockResolvedValue(job("error"));

    const { result } = renderHook(() => useRecommendation());
    await act(async () => {
      await result.current.start({});
    });

    expect(result.current.phase).toBe("error");
    expect(result.current.error).toBeTruthy();
  });

  it("끝나지 않으면 시간 초과로 종료한다 — '분석 중'에 갇히지 않는다", async () => {
    vi.spyOn(api, "createRecommendation").mockResolvedValue(ACCEPTED);
    vi.spyOn(api, "recommendation").mockResolvedValue(job("running"));

    const { result } = renderHook(() => useRecommendation());
    await act(async () => {
      await result.current.start({});
    });
    await tick(POLL_TIMEOUT_MS + POLL_INTERVAL_MS);

    expect(result.current.phase).toBe("error");
    expect(result.current.error).toContain("시간");
  });

  it("실행 요청이 실패하면 그 자리에서 에러로 끝낸다", async () => {
    vi.spyOn(api, "createRecommendation").mockRejectedValue(
      new ApiException(409, { code: "JOB_IN_PROGRESS", message: "이미 실행 중" }),
    );

    const { result } = renderHook(() => useRecommendation());
    await act(async () => {
      await result.current.start({});
    });

    expect(result.current.phase).toBe("error");
    expect(result.current.error).toContain("이미 실행 중");
  });

  it("중단하면 이후 폴링 결과를 버린다", async () => {
    vi.spyOn(api, "createRecommendation").mockResolvedValue(ACCEPTED);
    vi.spyOn(api, "recommendation").mockResolvedValue(job("running"));

    const { result } = renderHook(() => useRecommendation());
    await act(async () => {
      await result.current.start({});
    });
    act(() => result.current.cancel());
    await tick(POLL_INTERVAL_MS * 3);

    expect(result.current.phase).toBe("idle");
    expect(result.current.job).toBeNull();
  });
});
