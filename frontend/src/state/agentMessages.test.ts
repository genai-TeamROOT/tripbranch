/*
 * 역할: buildAgentMessages가 한 턴을 어떤 화면 메시지들로 펴는지 검증한다.
 * 특히 **피드백 버튼이 붙는 턴과 안 붙는 턴**을 잠근다 — 이 판정은 되묻기에
 * 좋아요/싫어요가 매겨지는지를 가르고, 그 점수가 추천 품질 자료로 쓰인다.
 */

import { expect, it } from "vitest";

import type { AgentResponse, ClarificationOption } from "../types";
import { buildAgentMessages } from "./agentMessages";

/*
 * AgentResponse는 필드가 많고 대부분 이 함수가 보지 않는다(UserConditions,
 * api_context 등). 이 함수가 실제로 읽는 것만 채우고 한 번만 캐스팅한다 —
 * 전부 채우면 픽스처가 계약 변경마다 깨지는데, 여기서 보는 것은 메시지 조립
 * 규칙이지 계약의 완전성이 아니다.
 */
function response(overrides: Partial<AgentResponse> = {}): AgentResponse {
  return {
    llm_output: { intent: "RECOMMEND", status: "complete", clarification: null },
    state: { session_id: "sess_1", run_id: "run_1" },
    recommendations: null,
    message: "답변이에요",
    ...overrides,
  } as unknown as AgentResponse;
}

function clarification(options: ClarificationOption[]) {
  return {
    llm_output: {
      intent: "RECOMMEND",
      status: "needs_clarification",
      clarification: { missing_fields: [], ambiguous_fields: [], message: "", options },
    },
  } as unknown as Partial<AgentResponse>;
}

const OPTIONS: ClarificationOption[] = [
  { id: "indoor", label: "실내", resolved_intent: "RECOMMEND" },
];

function types(messages: ReturnType<typeof buildAgentMessages>) {
  return messages.map((message) => message.type);
}

it("보통 답변에는 피드백 버튼이 붙는다", () => {
  const messages = buildAgentMessages(response(), { userInput: "질문", elapsedMsClient: 0 });

  expect(types(messages)).toEqual(["assistant_text", "feedback"]);
});

it("되묻기만 한 턴에는 피드백 버튼을 붙이지 않는다", () => {
  /* 2026-09-08. 되묻기는 답이 아니라 질문이라, 좋아요/싫어요를 매기면 무엇에
     대한 평가인지 알 수 없다. mintee가 2d29192c에서 노출시킨 것을 되돌린 것이다. */
  const messages = buildAgentMessages(response(clarification(OPTIONS)), {
    userInput: "어디 갈지 모르겠어",
    elapsedMsClient: 0,
  });

  expect(types(messages)).toEqual(["clarification"]);
  expect(types(messages)).not.toContain("feedback");
});

it("되묻기와 결과 카드가 함께 오면 피드백 버튼이 그대로 붙는다", () => {
  /* 그 턴에는 평가할 대상(카드)이 있다. 없애면 카드에 대한 피드백까지 사라진다. */
  const messages = buildAgentMessages(
    response({
      ...clarification(OPTIONS),
      recommendations: {
        recommendations: [],
        unverified_recommendations: [],
        elapsed_ms: 10,
      },
    } as Partial<AgentResponse>),
    { userInput: "어디 갈지 모르겠어", elapsedMsClient: 0 },
  );

  expect(types(messages)).toContain("clarification");
  expect(types(messages)).toContain("feedback");
});

it("run_id가 없으면 어떤 턴이든 피드백 버튼이 없다", () => {
  const messages = buildAgentMessages(
    response({ state: { session_id: "sess_1", run_id: "" } } as Partial<AgentResponse>),
    { userInput: "질문", elapsedMsClient: 0 },
  );

  expect(types(messages)).not.toContain("feedback");
});
