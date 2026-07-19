// Vitest 전역 셋업. @testing-library/jest-dom의 커스텀 matcher(toBeInTheDocument 등)를 등록한다.
// vite.config.ts의 test.setupFiles에서 자동으로 로드되며, 개별 테스트 파일에서 다시 import할 필요 없음.

import "@testing-library/jest-dom/vitest";
