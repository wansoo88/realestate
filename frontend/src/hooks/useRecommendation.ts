/**
 * AI 추천 실행 + 결과 폴링 (F1·F3·F6).
 *
 * 서버는 `POST /recommendations` 로 202 를 주고 백그라운드에서 분석한다.
 * SSE(`stream_url`)는 모바일 백그라운드 전환에서 끊기므로 **폴링을 기본**으로 둔다
 * (api-spec §9 A1 — SSE 는 후속). 폴링은 반드시 끝나야 한다: 완료·실패·시간초과 셋 중 하나.
 * 'queued' 로 영영 멈춰 있는 화면이 가장 위험하다.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiException,
  api,
  type RecommendationJob,
  type RecommendationRequest,
} from "../api/client";
import { jobPhase, resolvePollPath, type JobPhase } from "../lib/recommendation";

export const POLL_INTERVAL_MS = 2000;
/** 이 시간이 지나면 포기하고 사용자에게 알린다(무한 폴링 금지). */
export const POLL_TIMEOUT_MS = 5 * 60 * 1000;

export interface RecommendationState {
  phase: JobPhase;
  jobId: string | null;
  job: RecommendationJob | null;
  error: string | null;
}

const IDLE: RecommendationState = { phase: "idle", jobId: null, job: null, error: null };

function messageOf(e: unknown, fallback: string): string {
  if (e instanceof ApiException) {
    if (e.status === 409) return "같은 조건의 분석이 이미 실행 중입니다.";
    if (e.status === 422) return e.error.message || "분석에 필요한 조건이 부족합니다.";
    return e.error.message || fallback;
  }
  return fallback;
}

export function useRecommendation() {
  const [state, setState] = useState<RecommendationState>(IDLE);

  const timer = useRef<number | null>(null);
  const alive = useRef(true);
  /** 현재 유효한 실행 번호. 새 실행·취소가 있으면 증가해 이전 폴링 결과를 버린다. */
  const runId = useRef(0);

  const clearTimer = useCallback(() => {
    if (timer.current) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, []);

  const cancel = useCallback(() => {
    runId.current += 1; // 진행 중 폴링의 결과를 무효화
    clearTimer();
    setState(IDLE);
  }, [clearTimer]);

  const start = useCallback(
    async (req: RecommendationRequest) => {
      runId.current += 1;
      const id = runId.current;
      clearTimer();
      setState({ phase: "queued", jobId: null, job: null, error: null });

      let path: string;
      let jobId: string;
      try {
        const accepted = await api.createRecommendation(req);
        if (!alive.current || id !== runId.current) return;
        jobId = accepted.job_id;
        // 서버가 준 poll_url 은 형식 검증을 통과할 때만 쓴다(lib/recommendation.ts).
        path = resolvePollPath(accepted.poll_url, accepted.job_id);
      } catch (e) {
        if (!alive.current || id !== runId.current) return;
        setState({
          phase: "error",
          jobId: null,
          job: null,
          error: messageOf(e, "분석을 시작하지 못했습니다."),
        });
        return;
      }

      setState({ phase: "queued", jobId, job: null, error: null });
      const deadline = Date.now() + POLL_TIMEOUT_MS;

      const poll = async (): Promise<void> => {
        let job: RecommendationJob;
        try {
          job = await api.recommendation(path);
        } catch (e) {
          if (!alive.current || id !== runId.current) return;
          setState((s) => ({
            ...s,
            phase: "error",
            error: messageOf(e, "분석 결과를 불러오지 못했습니다."),
          }));
          return;
        }
        if (!alive.current || id !== runId.current) return;

        const phase = jobPhase(job.status);
        setState({
          phase,
          jobId,
          job,
          error: phase === "error" ? "분석에 실패했습니다. 잠시 후 다시 시도해 주세요." : null,
        });
        if (phase === "done" || phase === "error") return;

        if (Date.now() >= deadline) {
          setState((s) => ({
            ...s,
            phase: "error",
            error: "분석이 시간 안에 끝나지 않았습니다. 다시 시도해 주세요.",
          }));
          return;
        }
        timer.current = window.setTimeout(() => void poll(), POLL_INTERVAL_MS);
      };

      await poll();
    },
    [clearTimer],
  );

  return { ...state, start, cancel };
}
