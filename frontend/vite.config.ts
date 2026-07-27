import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // 개발 중 API 는 백엔드로 프록시. 운영에서는 nginx 가 담당한다.
    proxy: { "/api": { target: "http://localhost:8000", changeOrigin: true } },
  },
  build: { outDir: "dist", sourcemap: false },
  test: {
    /* Vitest 는 기본적으로 모든 CSS import 를 **빈 문자열로 스텁**한다(속도 때문).
       그래서 `tokens.css?raw` 도 빈 값으로 와서 대비 회귀 테스트가 파일을 못 읽는다.
       tokens.css **한 개만** 실제로 로드하게 열어 준다 —
       전체를 켜면 38개 테스트 파일이 전부 CSS 파이프라인을 타서 느려지고,
       jsdom 에 실제 스타일이 주입돼 기존 테스트의 전제도 바뀐다. */
    css: { include: [/tokens\.css/] },
  },
});
