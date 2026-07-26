/**
 * 실구매 가능 금액 + 자금계획 (F2).
 *
 * 계산은 **서버가** 한다(세법·대출 규제 기반 결정론적 계산). 프론트는 표시만 —
 * 여기서 다시 계산하면 진실이 두 개가 되고, 둘이 어긋나는 날 사용자는 둘 다 못 믿는다.
 *
 * 희망 매매가(`targetPriceKrw`)를 함께 보내면 응답에 `plan` 이 붙는다.
 *  - 조건 화면에서 정한 값(선호에 저장된 값), 또는
 *  - **지금 고른 단지의 가격**(what-if). 단지를 바꿀 때마다 요청이 나가면 과하므로
 *    아래 디바운스가 마지막 선택만 보낸다.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiException, api, type AffordabilityResponse } from "../api/client";

/**
 * 희망가·단지 선택이 바뀐 뒤 요청까지의 간격.
 * 지도 조회(MAP_DEBOUNCE_MS)와 같은 값으로 둔다 — 마커를 훑으며 클릭할 때
 * 지도 조회와 자금계산이 서로 다른 박자로 깜빡이면 화면이 불안해 보인다.
 */
export const AFFORD_DEBOUNCE_MS = 350;

export interface AffordabilityState {
  data: AffordabilityResponse | null;
  loading: boolean;
  /** 자산 미입력(422 INSUFFICIENT_DATA) — 에러가 아니라 "먼저 입력하세요" 신호다. */
  needsProfile: boolean;
  error: string | null;
}

export type Purpose = "live" | "invest";

export function useAffordability(
  enabled: boolean,
  purpose: Purpose = "live",
  targetPriceKrw: number | null = null,
) {
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

  const run = useCallback(async (p: Purpose, target: number | null) => {
    const id = (reqId.current += 1);
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      // ⚠️ 지역(권역)은 **보내지 않는다.** 서버가 판정한다(CR10-1: 클라이언트가 권역을
      //    고르면 6억 캡을 우회해 예산을 부풀릴 수 있다).
      //    희망가는 반대다 — 예산을 **부풀리는 값이 아니라** "이걸 사려면 뭐가 필요한가"를
      //    묻는 입력이고, 한도(max_purchase_krw)는 서버가 이 값과 무관하게 계산한다.
      const data = await api.affordability(
        target !== null && target > 0
          ? { purpose: p, target_price_krw: target }
          : { purpose: p },
      );
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

  /**
   * 첫 조회는 **즉시** 한다. 화면을 여는 순간의 350ms 지연은 "느린 앱"으로 보이고,
   * 디바운스가 막아야 하는 것은 그게 아니라 **연속으로 바뀌는 희망가·단지 선택**이다.
   */
  const ranOnce = useRef(false);
  useEffect(() => {
    if (!enabled) return;
    if (!ranOnce.current) {
      ranOnce.current = true;
      void run(purpose, targetPriceKrw);
      return;
    }
    const t = window.setTimeout(() => void run(purpose, targetPriceKrw), AFFORD_DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [enabled, purpose, targetPriceKrw, run]);

  return { ...state, refresh: () => run(purpose, targetPriceKrw) };
}
