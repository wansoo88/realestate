/**
 * 실구매 가능 금액 (F2).
 *
 * 계산은 **서버가** 한다(세법·대출 규제 기반 결정론적 계산). 프론트는 표시만 —
 * 여기서 다시 계산하면 진실이 두 개가 되고, 둘이 어긋나는 날 사용자는 둘 다 못 믿는다.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiException, api, type AffordabilityResponse } from "../api/client";

export interface AffordabilityState {
  data: AffordabilityResponse | null;
  loading: boolean;
  /** 자산 미입력(422 INSUFFICIENT_DATA) — 에러가 아니라 "먼저 입력하세요" 신호다. */
  needsProfile: boolean;
  error: string | null;
}

export type Purpose = "live" | "invest";

export function useAffordability(enabled: boolean, purpose: Purpose = "live") {
  const [state, setState] = useState<AffordabilityState>({
    data: null,
    loading: false,
    needsProfile: false,
    error: null,
  });

  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // 요청 순서가 바뀌어 늦게 온 응답이 최신 결과를 덮지 않게 한다.
  const reqId = useRef(0);

  const run = useCallback(async (p: Purpose) => {
    const id = (reqId.current += 1);
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      // ⚠️ 지역(권역)은 **보내지 않는다.** 서버가 판정한다(CR10-1: 클라이언트가 권역을
      //    고르면 6억 캡을 우회해 예산을 부풀릴 수 있다).
      const data = await api.affordability({ purpose: p });
      if (!alive.current || id !== reqId.current) return;
      setState({ data, loading: false, needsProfile: false, error: null });
    } catch (e) {
      if (!alive.current || id !== reqId.current) return;
      const insufficient = e instanceof ApiException && e.status === 422;
      setState({
        data: null,
        loading: false,
        needsProfile: insufficient,
        error: insufficient
          ? null
          : e instanceof ApiException
            ? e.error.message || "실구매 가능 금액을 계산하지 못했습니다."
            : "네트워크 오류로 계산하지 못했습니다.",
      });
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void run(purpose);
  }, [enabled, purpose, run]);

  return { ...state, refresh: () => run(purpose) };
}
