import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { restoreSession } from "./api/client";
import "./styles/tokens.css";

const root = document.getElementById("root");
if (!root) throw new Error("#root 를 찾을 수 없습니다");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

/**
 * 새로고침 세션 복원 — refresh **쿠키**로 access 를 1회 되찾는다(FE-1 §2).
 *
 * 저장소에서 토큰을 읽던 loadTokens 방식은 폐기했다(security.md §2.1):
 * 프론트는 refresh 토큰을 볼 수 없고, access 는 메모리라 새로고침이면 사라진다.
 * 렌더를 막지 않고 시작한다 — App 은 결과가 오기 전까지 "세션 확인 중"을 보이고,
 * 성공/401 이 방송되면 지도 또는 로그인 화면으로 전환된다.
 * (모듈 최상위 호출이라 StrictMode 이중 마운트에도 refresh 는 정확히 1회다.)
 */
void restoreSession();
