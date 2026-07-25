/**
 * 인증 상태를 리액트에 연결하는 **얇은** 훅.
 *
 * 실제 로직(토큰 수명·401 재시도·로그아웃 방송)은 api/client.ts 에 있다(뷰 비의존, RN 재사용).
 * 이 훅은 그 상태를 렌더링에 잇기만 한다 — 비즈니스 로직을 컴포넌트에 넣지 않는다(ux §10 규칙).
 */
import { useEffect, useState } from "react";
import { getAuthState, subscribeAuth, type AuthState } from "../api/client";

export function useAuth(): AuthState {
  const [state, setState] = useState<AuthState>(getAuthState);

  useEffect(() => {
    // 마운트 직전에 세션 복원이 끝났을 수 있다(main.tsx 가 렌더와 병렬로 돌린다).
    // 구독 시점에 한 번 당겨와 그 사이 놓친 변화를 메운다.
    setState(getAuthState());
    return subscribeAuth(setState);
  }, []);

  return state;
}
