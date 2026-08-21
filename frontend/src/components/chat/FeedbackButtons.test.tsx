import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import { FeedbackButtons } from "./FeedbackButtons";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("좋아요를 누르면 클릭 즉시 /api/feedback에 rating=like로 기록한다", async () => {
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

it("싫어요를 누르면 즉시 전송하지 않고 코멘트 입력창을 펼친다", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);

  render(<FeedbackButtons sessionId="sess_1" runId="run_1" />);
  await user.click(screen.getByRole("button", { name: "별로예요" }));

  expect(fetchMock).not.toHaveBeenCalled();
  expect(screen.getByPlaceholderText("어떤 점이 아쉬웠나요? (선택)")).toBeInTheDocument();
});

it("코멘트를 적고 제출하면 rating=dislike와 comment를 함께 기록한다", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ recorded_at: "2026-08-21T00:00:00+09:00" }),
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<FeedbackButtons sessionId="sess_1" runId="run_1" />);
  await user.click(screen.getByRole("button", { name: "별로예요" }));
  await user.type(screen.getByPlaceholderText("어떤 점이 아쉬웠나요? (선택)"), "장소가 너무 멀어요");
  await user.click(screen.getByRole("button", { name: "제출" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/feedback",
    expect.objectContaining({
      body: JSON.stringify({
        session_id: "sess_1",
        run_id: "run_1",
        rating: "dislike",
        comment: "장소가 너무 멀어요",
      }),
    }),
  );
  expect(screen.getByRole("button", { name: "별로예요" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.queryByPlaceholderText("어떤 점이 아쉬웠나요? (선택)")).not.toBeInTheDocument();
});

it("건너뛰기를 누르면 comment 없이 rating=dislike만 기록한다", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ recorded_at: "2026-08-21T00:00:00+09:00" }),
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<FeedbackButtons sessionId="sess_1" runId="run_1" />);
  await user.click(screen.getByRole("button", { name: "별로예요" }));
  expect(fetchMock).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "건너뛰기" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/feedback",
    expect.objectContaining({
      body: JSON.stringify({ session_id: "sess_1", run_id: "run_1", rating: "dislike" }),
    }),
  );
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

it("userInput/assistantMessage/intent가 있으면 함께 전송한다", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ recorded_at: "2026-08-21T00:00:00+09:00" }),
  });
  vi.stubGlobal("fetch", fetchMock);

  render(
    <FeedbackButtons
      sessionId="sess_1"
      runId="run_1"
      userInput="경복궁 근처 카페 추천해줘"
      assistantMessage="이런 곳들을 찾아봤어요."
      intent="RECOMMEND"
    />,
  );
  await user.click(screen.getByRole("button", { name: "좋아요" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/feedback",
    expect.objectContaining({
      body: JSON.stringify({
        session_id: "sess_1",
        run_id: "run_1",
        rating: "like",
        user_input: "경복궁 근처 카페 추천해줘",
        assistant_message: "이런 곳들을 찾아봤어요.",
        intent: "RECOMMEND",
      }),
    }),
  );
});

it("session_id나 run_id가 없으면 아무것도 렌더링하지 않는다", () => {
  const { container } = render(<FeedbackButtons sessionId="" runId="" />);
  expect(container).toBeEmptyDOMElement();
});
