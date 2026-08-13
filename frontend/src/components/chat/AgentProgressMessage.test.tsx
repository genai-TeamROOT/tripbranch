import { render, screen } from "@testing-library/react";
import { act } from "react";
import { vi } from "vitest";

import { AgentProgressMessage } from "./AgentProgressMessage";

it("안내 단계를 한 번 순차적으로 전환한 뒤 마지막 단계에 머문다", () => {
  vi.useFakeTimers();
  render(<AgentProgressMessage hasDeviceLocation />);

  expect(screen.getByText("요청 의도와 조건 파악 중")).toBeInTheDocument();

  act(() => {
    vi.advanceTimersByTime(1_700);
  });
  expect(screen.getByText("대화 조건 병합 중")).toBeInTheDocument();

  act(() => {
    vi.advanceTimersByTime(1_700 * 4);
  });
  expect(screen.getByText("답변 정리 중")).toBeInTheDocument();
  vi.useRealTimers();
});

it("일정 편성 중이면 로딩 단계 목록에 일정 편성을 추가한다", () => {
  render(<AgentProgressMessage hasDeviceLocation schedulePlanning />);

  expect(screen.getByText("일정 편성")).toBeInTheDocument();
});
