/*
 * 역할: streamPost의 externalSignal(중단 버튼)이 실제로 fetch를 끊고, AbortError가
 *   그대로(내부 오류로 뭉개지지 않고) 호출자에게 전달되는지 검증한다.
 * 입력: mock fetch, 외부에서 만든 AbortController.
 * 출력: 중단 시 streamPost 반환 Promise가 AbortError로 reject되는지에 대한 assertion.
 * 호출 시점: vitest 실행 시. ChatPage/HomePage의 "중단" 버튼(state/activeChatTurn.ts)이
 *   이 계약에 의존한다 — AbortError가 아닌 다른 에러로 바뀌면 취소가 조용히
 *   처리되지 못하고 화면에 오류 배너가 뜬다.
 */

import { afterEach, expect, test, vi } from "vitest";
import { streamPost } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

/** 실제 fetch처럼: 호출 시점에 이미 aborted면 즉시 reject, 아니면 이후 abort를 기다린다. */
function stubAbortAwareFetch() {
  let capturedSignal: AbortSignal | undefined;
  const fetchMock = vi.fn((_url: string, init: RequestInit) => {
    capturedSignal = init.signal as AbortSignal;
    if (capturedSignal.aborted) {
      return Promise.reject(new DOMException("aborted", "AbortError"));
    }
    return new Promise((_resolve, reject) => {
      capturedSignal!.addEventListener("abort", () => {
        reject(new DOMException("aborted", "AbortError"));
      });
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return () => capturedSignal;
}

test("헤더를 받기 전에 중단하면 AbortError로 끝난다(연결 실패로 뭉개지지 않는다)", async () => {
  const getCapturedSignal = stubAbortAwareFetch();

  const external = new AbortController();
  const promise = streamPost("/chat/stream", { user_input: "안녕" }, () => {}, external.signal);
  external.abort();

  await expect(promise).rejects.toMatchObject({ name: "AbortError" });
  expect(getCapturedSignal()?.aborted).toBe(true);
});

test("이미 중단된 signal을 넘기면 fetch 호출 시점부터 중단 상태다", async () => {
  const getCapturedSignal = stubAbortAwareFetch();

  const external = new AbortController();
  external.abort();

  await expect(
    streamPost("/chat/stream", { user_input: "안녕" }, () => {}, external.signal),
  ).rejects.toMatchObject({ name: "AbortError" });
  expect(getCapturedSignal()?.aborted).toBe(true);
});
