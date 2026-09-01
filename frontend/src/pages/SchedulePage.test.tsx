/*
 * 역할: 일정 화면의 빈 상태(짠 일정 없음)를 검증한다.
 * 호출 시점: vitest 실행 시.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { AppShellProvider } from "../components/layout/AppShellContext";
import { TripProvider } from "../state/TripContext";
import { SchedulePage } from "./SchedulePage";

beforeEach(() => {
  sessionStorage.clear();
});

test("짠 일정이 없으면 채팅으로 돌아가자는 안내를 보여준다", async () => {
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={["/schedule"]}>
      <AppShellProvider>
        <TripProvider>
          <SchedulePage />
        </TripProvider>
      </AppShellProvider>
    </MemoryRouter>,
  );

  expect(screen.getByText("아직 짠 일정이 없어요.")).toBeInTheDocument();

  const cta = screen.getByRole("button", { name: "채팅에서 일정 짜기" });
  await user.click(cta);
});
