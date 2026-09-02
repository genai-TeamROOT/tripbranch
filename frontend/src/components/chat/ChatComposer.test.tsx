/*
 * 역할: 응답 대기 중(disabled) 전송 버튼 자리에 중단 버튼이 뜨는지 검증한다.
 * 입력: disabled/onCancel prop 조합.
 * 출력: 중단 버튼 노출 여부, 클릭 시 onCancel 호출에 대한 assertion.
 * 근거: Figma node 28:235(Home — 응답 중 (중단 가능)).
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ChatComposer } from "./ChatComposer";

test("onCancel이 없으면 응답 대기 중에도 비활성화된 전송 버튼만 보인다", () => {
  render(<ChatComposer disabled onSubmit={vi.fn()} />);

  expect(screen.getByRole("button", { name: "보내기" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "중단" })).not.toBeInTheDocument();
});

test("onCancel이 있으면 응답 대기 중 전송 버튼 대신 중단 버튼이 뜬다", async () => {
  const user = userEvent.setup();
  const onCancel = vi.fn();
  render(<ChatComposer disabled onSubmit={vi.fn()} onCancel={onCancel} />);

  expect(screen.queryByRole("button", { name: "보내기" })).not.toBeInTheDocument();
  const cancelButton = screen.getByRole("button", { name: "중단" });
  await user.click(cancelButton);

  expect(onCancel).toHaveBeenCalledOnce();
});

test("대기 중이 아니면 onCancel이 있어도 전송 버튼이 그대로 보인다", () => {
  render(<ChatComposer disabled={false} onSubmit={vi.fn()} onCancel={vi.fn()} />);

  expect(screen.getByRole("button", { name: "보내기" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "중단" })).not.toBeInTheDocument();
});
