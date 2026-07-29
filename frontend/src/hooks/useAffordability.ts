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
import {
  ApiException,
  api,
  type AffordabilityRequest,
  type AffordabilityResponse,
} from "../api/client";
import { DEFAULT_PURPOSE, type Purpose } from "../lib/purpose";

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

/**
 * 목적은 **한 곳(`lib/purpose.ts`)에서만** 정의한다 — 지도 조회도 같은 값을 써야 하므로
 * 훅마다 리터럴을 적으면 언젠가 한쪽만 바뀐다. 여기서는 이름만 다시 내보낸다.
 */
export type { Purpose };

/**
 * 이 계획을 **무엇을 기준으로** 세울 것인가.
 *
 *  · 숫자(또는 `{kind:"target"}`) — 사용자가 직접 정한 희망가. 그대로 실어 보낸다.
 *  · `{kind:"complex"}`           — **단지 기준**. 금액을 화면이 정하지 않고 `complex_id` 를
 *    보내 서버가 추천 카드와 **같은 함수**로 산출하게 한다(CR35-4).
 *
 * 왜 단지일 때 금액을 안 보내나: 지도의 `recent_price_krw` 는 "최근 체결 1건"이고 추천
 * 카드는 "창 중위를 기준월로 환산한 추정가"다. 화면이 지도 값을 실어 보내면 같은 단지의
 * 자금계획과 추천 카드가 **다른 금액**으로 서고, 실측으로 부족액이 최대 3.19억 벌어졌다.
 */
export type PlanTarget =
  | { kind: "target"; krw: number }
  | { kind: "complex"; complexId: number; areaM2: number };

/**
 * 요청 본문. **없는 값은 키 자체를 싣지 않는다** — `null`·0 을 보내면 서버가 "0원 예산"으로
 * 읽을 여지가 생긴다(계약상 `target_price_krw` 는 gt=0).
 */
export function planRequest(
  purpose: Purpose,
  target: number | null | PlanTarget,
): AffordabilityRequest {
  if (typeof target === "number") {
    return target > 0 ? { purpose, target_price_krw: target } : { purpose };
  }
  if (target && target.kind === "target") {
    return target.krw > 0 ? { purpose, target_price_krw: target.krw } : { purpose };
  }
  if (target && target.kind === "complex") {
    // 금액은 **보내지 않는다**. 서버가 이 단지·면적으로 추천과 같은 기준가를 만든다.
    return { purpose, complex_id: target.complexId, area_m2: target.areaM2 };
  }
  return { purpose };
}

export function useAffordability(
  enabled: boolean,
  purpose: Purpose = DEFAULT_PURPOSE,
  target: number | null | PlanTarget = null,
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

  const run = useCallback(async (p: Purpose, t: number | null | PlanTarget) => {
    const id = (reqId.current += 1);
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      // ⚠️ 지역(권역)은 **보내지 않는다.** 서버가 판정한다(CR10-1: 클라이언트가 권역을
      //    고르면 6억 캡을 우회해 예산을 부풀릴 수 있다).
      //    희망가는 반대다 — 예산을 **부풀리는 값이 아니라** "이걸 사려면 뭐가 필요한가"를
      //    묻는 입력이고, 한도(max_purchase_krw)는 서버가 이 값과 무관하게 계산한다.
      const data = await api.affordability(planRequest(p, t));
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
  /**
   * 의존성은 **요청 내용**으로 비교한다. 부모가 매 렌더 새 객체(`{kind:"complex",…}`)를
   * 만들어도 내용이 같으면 요청이 다시 나가지 않는다 — 객체 정체성으로 비교하면
   * 지도를 다시 조회할 때마다 자금계산이 한 번 더 나간다(useMapArea 와 같은 규칙).
   */
  const key = JSON.stringify(planRequest(purpose, target));
  const latest = useRef(target);
  latest.current = target;

  useEffect(() => {
    if (!enabled) return;
    if (!ranOnce.current) {
      ranOnce.current = true;
      void run(purpose, latest.current);
      return;
    }
    const t = window.setTimeout(() => void run(purpose, latest.current), AFFORD_DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [enabled, purpose, key, run]);

  return { ...state, refresh: () => run(purpose, latest.current) };
}
