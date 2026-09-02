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
  build: {
    rollupOptions: {
      output: {
        /*
         * 자주 바뀌는 앱 코드와 거의 안 바뀌는 라이브러리를 갈라 둔다.
         *
         * 이유는 두 가지다. ① 한 덩어리로 두면 앱 코드 한 줄만 고쳐도 사용자가
         * 라이브러리 전부를 다시 받는다. ② 통짜 청크가 Vite의 500 kB 경고를
         * 넘고 있었다.
         *
         * 실측(2026-09-02): react 225 kB · supabase 208 kB · framer-motion 125 kB ·
         * 앱 코드 187 kB · lucide 16 kB. supabase가 인증에만 쓰이는데도 큰 편인데,
         * AuthProvider가 앱을 통째로 감싸 부팅 경로에 있어 지금은 나중에 받아올 수 없다.
         *
         * 총 바이트는 줄지 않는다 — 줄어드는 것은 "다시 받는 양"이다.
         */
        manualChunks(id: string) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("/@supabase/")) return "vendor-supabase";
          if (id.includes("/framer-motion/")) return "vendor-motion";
          if (
            id.includes("/react-dom/") ||
            id.includes("/react-router") ||
            id.includes("/react/")
          )
            return "vendor-react";
          return undefined;
        },
      },
    },
  },
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
