/*
 * 역할: useVisualViewportHeight의 "키보드가 가릴 때만 값을 낸다" / "평소·미지원
 * 환경에서는 null" 두 분기를 검증한다.
 *
 * jsdom에는 window.visualViewport가 없다 — 이 테스트에서만 addEventListener를
 * 손으로 실행할 수 있는 가짜 VisualViewport로 채워 넣어 검증한다.
 */

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it } from "vitest";
import { useVisualViewportHeight } from "./useVisualViewportHeight";

let triggerResize: () => void;
let fakeViewport: { height: number };
const originalInnerHeight = window.innerHeight;
const originalVisualViewport = window.visualViewport;

beforeEach(() => {
  Object.defineProperty(window, "innerHeight", { value: 800, configurable: true });
  fakeViewport = { height: 800 };
  const listeners: Array<() => void> = [];
  window.visualViewport = {
    get height() {
      return fakeViewport.height;
    },
    addEventListener: (_event: string, listener: () => void) => {
      listeners.push(listener);
    },
    removeEventListener: (_event: string, listener: () => void) => {
      const index = listeners.indexOf(listener);
      if (index >= 0) listeners.splice(index, 1);
    },
  } as unknown as VisualViewport;
  triggerResize = () => listeners.forEach((listener) => listener());
});

afterEach(() => {
  Object.defineProperty(window, "innerHeight", {
    value: originalInnerHeight,
    configurable: true,
  });
  window.visualViewport = originalVisualViewport;
});

it("visualViewport가 layout viewport보다 작아지면(키보드) 그 높이를 낸다", () => {
  const { result } = renderHook(() => useVisualViewportHeight());

  expect(result.current).toBeNull();

  fakeViewport.height = 480; // 키보드가 320px을 가렸다고 가정
  act(() => triggerResize());

  expect(result.current).toBe(480);
});

it("키보드가 내려가 다시 같아지면 null로 돌아간다", () => {
  const { result } = renderHook(() => useVisualViewportHeight());

  fakeViewport.height = 480;
  act(() => triggerResize());
  expect(result.current).toBe(480);

  fakeViewport.height = 800;
  act(() => triggerResize());
  expect(result.current).toBeNull();
});

it("visualViewport를 지원하지 않는 환경에서는 항상 null이다", () => {
  window.visualViewport = undefined as unknown as VisualViewport;

  const { result } = renderHook(() => useVisualViewportHeight());

  expect(result.current).toBeNull();
});
