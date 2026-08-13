/*
 * 역할: Vite, React, Tailwind, Vitest 실행 환경을 설정한다.
 * 입력: 개발 서버/빌드/테스트 명령과 환경 설정.
 * 출력: 프론트엔드 번들링, dev proxy, 테스트 환경 구성.
 * 호출 시점: npm scripts가 vite 또는 vitest를 실행할 때 로드된다.
 * TODO: 배포 환경별 API base URL과 프록시 정책이 생기면 mode별로 분기한다.
 */

/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // PORT가 지정되면 그대로 따른다 — 안 지키면 5173이 이미 쓰이고 있을 때 Vite가
    // 조용히 다른 포트로 넘어가버려서, 이 포트를 기대하는 프리뷰 도구와 어긋난다.
    port: process.env.PORT ? Number(process.env.PORT) : 5173,
    strictPort: Boolean(process.env.PORT),
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
