// InputPage 테스트: 입력 제출 성공 시 /confirm으로 이동하는지, interpretUserInput이
// 실패(ApiError)했을 때 에러 배너가 표시되는지 확인한다. api/interpret 모듈을 mocking해서
// 실제 네트워크 호출 없이 검증한다.

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { InputPage } from "./InputPage";
import { TripProvider } from "../context/TripContext";
import { ApiError } from "../api/client";
import * as interpretApi from "../api/interpret";

function renderInputPage() {
  return render(
    <TripProvider>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<InputPage />} />
          <Route path="/confirm" element={<div>ConfirmPage</div>} />
        </Routes>
      </MemoryRouter>
    </TripProvider>,
  );
}

describe("InputPage", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("navigates to /confirm after a successful submit", async () => {
    vi.spyOn(interpretApi, "interpretUserInput").mockResolvedValue({
      location_query: "경복궁",
      preferred_categories: ["museum"],
      weather_condition: "bad",
      search_radius_km: 1.0,
    });

    const user = userEvent.setup();
    renderInputPage();

    await user.type(screen.getByPlaceholderText(/경복궁 근처에서/), "비 오는 날 근처 박물관");
    await user.click(screen.getByRole("button", { name: "조건 확인하기" }));

    await waitFor(() => expect(screen.getByText("ConfirmPage")).toBeInTheDocument());
  });

  it("shows an error message when the request fails", async () => {
    vi.spyOn(interpretApi, "interpretUserInput").mockRejectedValue(
      new ApiError({
        code: "llm_interpretation_failed",
        message: "입력을 이해하지 못했어요.",
        retryable: true,
        details: null,
      }),
    );

    const user = userEvent.setup();
    renderInputPage();

    await user.type(screen.getByPlaceholderText(/경복궁 근처에서/), "아무 말이나 입력");
    await user.click(screen.getByRole("button", { name: "조건 확인하기" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("입력을 이해하지 못했어요.");
  });
});
