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

it("실제 progress 이벤트가 있으면 가상 타이머 대신 그 단계·문구를 그대로 보여준다", () => {
  vi.useFakeTimers();
  const { rerender } = render(
    <AgentProgressMessage
      hasDeviceLocation
      schedulePlanning
      progress={{ stage: "scheduling", message: "장소 순서를 계산하고 있어요.", elapsed_ms: 12_000 }}
    />,
  );

  // 경과 시간(12초)만 보면 가상 회전 로직은 이미 마지막 단계로 넘어가 있어야
  // 하지만, 실제 progress가 "scheduling"을 가리키면 그 단계에 머물러야 한다.
  expect(screen.getByText("일정 편성 중")).toBeInTheDocument();
  expect(screen.getByText("장소 순서를 계산하고 있어요.")).toBeInTheDocument();

  // heartbeat로 문구만 바뀌어도 즉시 반영된다(타이머 진행과 무관).
  rerender(
    <AgentProgressMessage
      hasDeviceLocation
      schedulePlanning
      progress={{ stage: "scheduling", message: "거의 다 됐어요.", elapsed_ms: 18_000 }}
    />,
  );
  expect(screen.getByText("거의 다 됐어요.")).toBeInTheDocument();
  vi.useRealTimers();
});
