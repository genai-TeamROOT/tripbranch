import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import { FeedbackButtons } from "./FeedbackButtons";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("좋아요를 누르면 /api/feedback에 rating=like로 기록한다", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ recorded_at: "2026-08-21T00:00:00+09:00" }),
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<FeedbackButtons sessionId="sess_1" runId="run_1" />);
  await user.click(screen.getByRole("button", { name: "좋아요" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/feedback",
    expect.objectContaining({
      body: JSON.stringify({ session_id: "sess_1", run_id: "run_1", rating: "like" }),
    }),
  );
  expect(screen.getByRole("button", { name: "좋아요" })).toHaveAttribute("aria-pressed", "true");
});

it("싫어요를 누르면 rating=dislike로 기록한다", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ recorded_at: "2026-08-21T00:00:00+09:00" }),
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<FeedbackButtons sessionId="sess_1" runId="run_1" />);
  await user.click(screen.getByRole("button", { name: "별로예요" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/feedback",
    expect.objectContaining({
      body: JSON.stringify({ session_id: "sess_1", run_id: "run_1", rating: "dislike" }),
    }),
  );
  expect(screen.getByRole("button", { name: "별로예요" })).toHaveAttribute("aria-pressed", "true");
});

it("전송에 실패하면 에러 문구를 보여준다", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn().mockRejectedValue(new Error("network down"));
  vi.stubGlobal("fetch", fetchMock);

  render(<FeedbackButtons sessionId="sess_1" runId="run_1" />);
  await user.click(screen.getByRole("button", { name: "좋아요" }));

  expect(await screen.findByText("피드백 전송에 실패했어요. 다시 시도해주세요.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "좋아요" })).toHaveAttribute("aria-pressed", "false");
});

it("session_id나 run_id가 없으면 아무것도 렌더링하지 않는다", () => {
  const { container } = render(<FeedbackButtons sessionId="" runId="" />);
  expect(container).toBeEmptyDOMElement();
});
