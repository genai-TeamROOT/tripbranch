import type { ChatMessage } from "../types";
import { findTurnText } from "./turnText";

function userText(text: string): ChatMessage {
  return { id: `u-${text}`, type: "user_text", text };
}

function assistantText(text: string): ChatMessage {
  return { id: `a-${text}`, type: "assistant_text", text };
}

function assistantTextWithIntent(text: string, intent: "RECOMMEND" | "INFO"): ChatMessage {
  return { id: `a-${text}`, type: "assistant_text", text, intent };
}

function recommendationResult(id: string): ChatMessage {
  return {
    id,
    type: "recommendation_result",
    recommendations: [],
    unverified_recommendations: [],
    elapsed_ms: 0,
    server_elapsed_ms: 0,
    sessionId: "sess_1",
    runId: "run_1",
  };
}

it("바로 앞의 user_text/assistant_text를 찾는다", () => {
  const messages = [userText("질문"), assistantText("답변"), recommendationResult("card")];

  const result = findTurnText(messages, 2);

  expect(result.userInput).toBe("질문");
  expect(result.assistantMessage).toBe("답변");
});

it("이전 턴의 user_text 경계를 넘어가지 않는다", () => {
  const messages = [
    userText("첫 질문"),
    assistantText("첫 답변"),
    recommendationResult("card-1"),
    userText("둘째 질문"),
    // 이 턴은 assistant_text 없이 바로 카드가 옴(스트리밍 텍스트가 아직 없는 경우 등)
    recommendationResult("card-2"),
  ];

  const result = findTurnText(messages, 4);

  expect(result.userInput).toBe("둘째 질문");
  expect(result.assistantMessage).toBeUndefined();
});

it("앞에 아무 메시지도 없으면 셋 다 undefined다", () => {
  const messages = [recommendationResult("card")];

  const result = findTurnText(messages, 0);

  expect(result.userInput).toBeUndefined();
  expect(result.assistantMessage).toBeUndefined();
  expect(result.intent).toBeUndefined();
});

it("assistant_text의 intent도 함께 찾는다", () => {
  const messages = [
    userText("질문"),
    assistantTextWithIntent("답변", "RECOMMEND"),
    recommendationResult("card"),
  ];

  const result = findTurnText(messages, 2);

  expect(result.intent).toBe("RECOMMEND");
});
