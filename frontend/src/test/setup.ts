/*
 * 역할: Vitest에서 React Testing Library matcher를 전역으로 등록한다.
 * 입력: Vitest setupFiles 실행 컨텍스트.
 * 출력: expect(...).toBeInTheDocument 같은 jest-dom matcher 사용 가능 상태.
 * 호출 시점: vitest가 테스트 파일을 실행하기 전에 자동으로 로드한다.
 * TODO: 공통 fetch/router mock이 많아지면 여기 또는 별도 test utils로 옮긴다.
 */

import "@testing-library/jest-dom/vitest";
