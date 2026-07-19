// RequireConditions 가드 테스트: interpreted_conditions가 없는 상태로 /confirm에 진입하면
// "/"로 리다이렉트되는지 MemoryRouter로 확인한다.

import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { RequireConditions } from "./RequireConditions";
import { TripProvider } from "../context/TripContext";

function renderAt(path: string) {
  return render(
    <TripProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/" element={<div>InputPage</div>} />
          <Route
            path="/confirm"
            element={
              <RequireConditions>
                <div>ConfirmPage</div>
              </RequireConditions>
            }
          />
        </Routes>
      </MemoryRouter>
    </TripProvider>,
  );
}

describe("RequireConditions", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("redirects to / when there are no interpreted conditions", () => {
    renderAt("/confirm");

    expect(screen.getByText("InputPage")).toBeInTheDocument();
    expect(screen.queryByText("ConfirmPage")).not.toBeInTheDocument();
  });
});
