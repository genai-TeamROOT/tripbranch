/*
 * 역할: useScrollEdgeButton의 "맨 위 근처 판정"과 "스크롤할 내용이 있는지 판정",
 * scrollToTop/scrollToBottom 동작을 검증한다.
 *
 * jsdom에는 ResizeObserver가 없어(test/setup.ts가 빈 스텁으로 막아둔다) 실제
 * 리사이즈를 재현할 수 없다 — 이 테스트에서만 콜백을 손으로 실행할 수 있는
 * 가짜 ResizeObserver로 바꿔치기해서 검증한다.
 */

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it } from "vitest";
import { useScrollEdgeButton } from "./useScrollEdgeButton";

let triggerResize: () => void;
let originalResizeObserver: typeof ResizeObserver;

beforeEach(() => {
  originalResizeObserver = window.ResizeObserver;
  class FakeResizeObserver {
    constructor(callback: ResizeObserverCallback) {
      triggerResize = () => callback([], this as unknown as ResizeObserver);
    }
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  window.ResizeObserver = FakeResizeObserver as unknown as typeof ResizeObserver;
});

afterEach(() => {
  window.ResizeObserver = originalResizeObserver;
});

function setUpShellAndContainer() {
  const shell = document.createElement("div");
  shell.style.overflowY = "auto";
  Object.defineProperty(shell, "scrollHeight", { value: 2000, configurable: true });
  Object.defineProperty(shell, "clientHeight", { value: 500, configurable: true });
  shell.scrollTop = 0;

  const container = document.createElement("div");
  shell.appendChild(container);
  document.body.appendChild(shell);

  return { shell, container };
}

it("스크롤할 내용이 있으면 isScrollable이 true가 되고, 맨 위에 있으면 isNearTop도 true다", () => {
  const { shell, container } = setUpShellAndContainer();
  // ref 객체를 매 렌더마다 새로 만들면(예: 렌더 콜백 안에서 리터럴로 넘기면) effect의
  // 의존성이 매번 "바뀐" 것으로 보여 update()의 setState → 재렌더 → effect 재실행이
  // 무한 반복된다. 실제 화면에서는 useRef가 안정적인 참조를 주지만, 테스트에서는
  // 직접 안정적인 참조를 만들어 넘겨야 한다.
  const containerRef = { current: container };

  const { result } = renderHook(() => useScrollEdgeButton(containerRef));
  act(() => triggerResize());

  expect(result.current.isScrollable).toBe(true);
  expect(result.current.isNearTop).toBe(true);

  document.body.removeChild(shell);
});

it("바닥 쪽으로 스크롤하면 isNearTop이 false가 된다", () => {
  const { shell, container } = setUpShellAndContainer();
  const containerRef = { current: container };

  const { result } = renderHook(() => useScrollEdgeButton(containerRef));
  act(() => triggerResize());

  act(() => {
    shell.scrollTop = 1000;
    shell.dispatchEvent(new Event("scroll"));
  });

  expect(result.current.isNearTop).toBe(false);

  document.body.removeChild(shell);
});

it("scrollToBottom은 스크롤 조상을 바닥까지, scrollToTop은 꼭대기까지 옮긴다", () => {
  const { shell, container } = setUpShellAndContainer();
  shell.scrollTop = 500;
  const containerRef = { current: container };

  const { result } = renderHook(() => useScrollEdgeButton(containerRef));

  act(() => result.current.scrollToBottom());
  expect(shell.scrollTop).toBe(2000);

  act(() => result.current.scrollToTop());
  expect(shell.scrollTop).toBe(0);

  document.body.removeChild(shell);
});

it("내용이 한 화면을 안 넘으면 isScrollable이 false로 남는다", () => {
  const shell = document.createElement("div");
  shell.style.overflowY = "auto";
  Object.defineProperty(shell, "scrollHeight", { value: 400, configurable: true });
  Object.defineProperty(shell, "clientHeight", { value: 500, configurable: true });
  const container = document.createElement("div");
  shell.appendChild(container);
  document.body.appendChild(shell);
  const containerRef = { current: container };

  const { result } = renderHook(() => useScrollEdgeButton(containerRef));
  act(() => triggerResize());

  expect(result.current.isScrollable).toBe(false);

  document.body.removeChild(shell);
});
