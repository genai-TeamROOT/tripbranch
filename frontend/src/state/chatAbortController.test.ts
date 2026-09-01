/*
 * 역할: 채팅 요청 취소용 모듈 싱글턴 컨트롤러의 동작을 검증한다.
 * 호출 시점: vitest 실행 시.
 */

import { expect, test } from "vitest";
import { beginChatRequest, cancelChatRequest, endChatRequest } from "./chatAbortController";

test("cancelChatRequest는 마지막으로 시작한 요청을 중단시킨다", () => {
  const controller = beginChatRequest();

  cancelChatRequest();

  expect(controller.signal.aborted).toBe(true);
});

test("새 요청을 시작하면 아직 끝나지 않은 이전 요청을 먼저 중단한다", () => {
  const first = beginChatRequest();
  const second = beginChatRequest();

  expect(first.signal.aborted).toBe(true);
  expect(second.signal.aborted).toBe(false);
});

test("endChatRequest 이후에는 cancelChatRequest가 그 요청에 영향을 주지 않는다", () => {
  const controller = beginChatRequest();
  endChatRequest(controller);

  cancelChatRequest();

  expect(controller.signal.aborted).toBe(false);
});

test("이미 다른 요청이 시작된 뒤에는 예전 컨트롤러로 endChatRequest를 불러도 새 요청을 건드리지 않는다", () => {
  const first = beginChatRequest();
  const second = beginChatRequest();

  endChatRequest(first);
  cancelChatRequest();

  expect(second.signal.aborted).toBe(true);
});
