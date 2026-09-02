/*
 * 역할: 약관 모달이 목차를 보여주고 닫히는지, 그리고 **없는 내용을 있는 척하지
 *   않는지** 검증한다.
 * 호출 시점: vitest 실행 시.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { TermsModal } from "./TermsModal";

test("조항 목차를 보여준다", () => {
  render(<TermsModal onClose={vi.fn()} />);

  expect(screen.getByRole("dialog")).toHaveAccessibleName("이용약관 및 개인정보처리방침");
  for (const 조항 of [
    "제1조 (목적)",
    "제2조 (서비스 이용)",
    "제3조 (개인정보 수집 및 이용)",
    "제4조 (이용자의 의무)",
  ]) {
    expect(screen.getByText(조항)).toBeInTheDocument();
  }
});

/*
 * 이 파일에서 가장 중요한 테스트다. Figma 시안에는 조항 본문이 채워져 있지만
 * 그 문장이 지금 코드가 하는 일과 어긋난다(GPS 원본 저장·대화 원문 국외 이전·
 * 보관기간 수동 삭제). 지키지 못하는 문장을 약관에 적는 것이 안 적는 것보다 나쁘다.
 */
test("아직 지킬 수 없는 문장을 적지 않는다", () => {
  render(<TermsModal onClose={vi.fn()} />);

  const body = screen.getByRole("dialog").textContent ?? "";
  expect(body).toContain("준비 중");
  for (const 지킬수_없는_약속 of [/안전하게 보관/, /목적으로만 사용/, /관련 법령에 따라/]) {
    expect(body).not.toMatch(지킬수_없는_약속);
  }
});

test("닫기 버튼과 확인 버튼 모두 모달을 닫는다", async () => {
  const onClose = vi.fn();
  render(<TermsModal onClose={onClose} />);

  await userEvent.click(screen.getByRole("button", { name: "확인했어요" }));
  expect(onClose).toHaveBeenCalledTimes(1);

  await userEvent.click(screen.getAllByRole("button", { name: "닫기" })[0]);
  expect(onClose).toHaveBeenCalledTimes(2);
});

/* 본문이 길어지면 X 버튼이 스크롤 밖으로 밀린다 — 키보드로도 빠져나갈 수 있어야 한다. */
test("Escape로 닫힌다", async () => {
  const onClose = vi.fn();
  render(<TermsModal onClose={onClose} />);

  await userEvent.keyboard("{Escape}");

  expect(onClose).toHaveBeenCalled();
});

/* "읽었다"와 "동의한다"는 다르다. 모달이 동의를 대신 켜주면 안 된다. */
test("확인했어요가 동의를 대신 눌러주지 않는다", async () => {
  const onClose = vi.fn();
  render(<TermsModal onClose={onClose} />);

  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
});
