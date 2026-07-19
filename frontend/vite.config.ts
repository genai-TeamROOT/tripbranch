// Vite 설정: React/Tailwind 플러그인, 개발 서버의 "/api" -> localhost:8000 프록시,
// Vitest 설정(jsdom 환경, 전역 matcher, setupFiles)을 한 파일에서 관리한다.
// 사용법: 백엔드 포트를 바꾸면 이 파일의 proxy target도 같이 수정할 것.

/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
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
