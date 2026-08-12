/*
 * 역할: C Tool 탭이 후보별 혼잡도 출처를 구분해 보여주는지 검증한다.
 * 입력: candidate_enrichment 실행 정보를 담은 감사 turn.
 * 출력: 근사치 표시, 직접 조회 표시, 해당 없는 행 숨김에 대한 assertion.
 * 호출 시점: vitest 실행 시 호출된다.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { DeveloperAuditTurn, ToolExecutionDebug } from "../../types";
import { DeveloperAuditPanel } from "./DeveloperAuditPanel";

const enrichmentExecution: ToolExecutionDebug = {
  operation: "candidate_enrichment",
  request_id: "enrich-1",
  status: "success",
  latency_ms: 180,
  providers: [],
  context_items: [],
  rule_versions: {},
  resolved_location_name: null,
  resolved_location_address: null,
  error_code: null,
  clarification_code: null,
  is_proxy: null,
  candidate_status_counts: { success: 2 },
  candidate_concentration: [
    {
      place_id: "126510",
      name: "종묘",
      status: "success",
      is_proxy: false,
      proxy_place_name: null,
      proxy_distance_km: null,
    },
    {
      place_id: "999999",
      name: "이름없는 카페",
      status: "success",
      is_proxy: true,
      proxy_place_name: "서울 운현궁",
      proxy_distance_km: 0.15,
    },
  ],
};

function _turn(execution: ToolExecutionDebug): DeveloperAuditTurn {
  return {
    id: "turn-1",
    userInput: "안국역 근처 한산한 곳",
    intent: "RECOMMEND",
    status: "complete",
    message: "추천 결과예요.",
    sessionId: "session-1",
    runId: "run-1",
    deviceLocation: null,
    elapsedMsClient: 1200,
    serverElapsedMs: 1100,
    stageTimings: [],
    extractedConditions: null,
    beforeConditions: null,
    afterConditions: null,
    recommendations: null,
    failure: null,
    response: {
      tool_executions: [execution],
      state: { api_context: null },
    } as unknown as DeveloperAuditTurn["response"],
  };
}

async function openToolsTab(execution: ToolExecutionDebug) {
  const user = userEvent.setup();
  render(
    <DeveloperAuditPanel
      turns={[_turn(execution)]}
      selectedTurnId="turn-1"
      onSelectTurn={() => {}}
    />,
  );
  await user.click(screen.getByRole("button", { name: "C Tool" }));
}

it("빌려온 값과 직접 조회한 값을 구분해서 보여준다", async () => {
  await openToolsTab(enrichmentExecution);

  expect(screen.getByText("후보별 혼잡도 출처")).toBeInTheDocument();
  // 어느 후보가 어디서 얼마나 떨어진 값을 빌렸는지가 핵심이다.
  expect(screen.getByText("근사치 ← 서울 운현궁 (0.15km)")).toBeInTheDocument();
  expect(screen.getByText("직접 조회")).toBeInTheDocument();
  expect(screen.getByText(/근사치 1건/)).toBeInTheDocument();
});

it("후보 보강 섹션에는 해석된 위치·주소를 띄우지 않는다", async () => {
  // 후보가 여럿이라 한 칸으로 표현되지 않는 항목이다. 빈 값으로 두면 채워져야
  // 하는데 빠진 것처럼 보인다.
  await openToolsTab(enrichmentExecution);

  expect(screen.queryByText("해석된 위치")).not.toBeInTheDocument();
  expect(screen.queryByText("해석된 주소")).not.toBeInTheDocument();
});

it("근사치가 없으면 전부 직접 조회했다고 알린다", async () => {
  await openToolsTab({
    ...enrichmentExecution,
    candidate_concentration: [enrichmentExecution.candidate_concentration![0]],
  });

  expect(
    screen.getByText("값이 있는 후보는 모두 자기 매핑으로 직접 조회했어요."),
  ).toBeInTheDocument();
});

it("소요시간 탭에서 단계별 합계와 C 세부 시간을 보여준다", async () => {
  const user = userEvent.setup();
  const turn = _turn(enrichmentExecution);
  turn.response = {
    ...turn.response,
    llm_execution: {
      calls: [
        {
          operation: "classify_intent",
          attempted_models: ["gemini-2.5-flash"],
          served_model: "gemini-2.5-flash",
          latency_ms: 420,
        },
        {
          operation: "extract_recommend_conditions",
          attempted_models: ["gemini-2.5-flash"],
          served_model: "gemini-2.5-flash",
          latency_ms: 1430,
        },
      ],
    },
  } as DeveloperAuditTurn["response"];
  turn.stageTimings = [
    {
      stage: "interpreting",
      message: "요청 의도와 조건을 파악하고 있어요.",
      started_at_ms: 0,
      duration_ms: 850,
    },
    {
      stage: "merging_conditions",
      message: "이전 대화 조건을 반영하고 있어요.",
      started_at_ms: 850,
      duration_ms: 30,
    },
    {
      stage: "fetching_context",
      message: "장소·운영시간·날씨 정보를 찾고 있어요.",
      started_at_ms: 880,
      duration_ms: 180,
    },
    {
      stage: "scoring",
      message: "조건에 맞게 장소 순위를 계산하고 있어요.",
      started_at_ms: 1060,
      duration_ms: 40,
    },
    {
      stage: "composing_message",
      message: "추천 결과를 안내하고 있어요.",
      started_at_ms: 1100,
      duration_ms: 600,
      time_to_first_token_ms: 240,
    },
  ];
  render(
    <DeveloperAuditPanel turns={[turn]} selectedTurnId="turn-1" onSelectTurn={() => {}} />,
  );

  await user.click(screen.getByRole("button", { name: "소요시간" }));

  expect(screen.getByText("이번 요청 총 소요")).toBeInTheDocument();
  expect(screen.getByText("LLM 의도·조건 추출")).toBeInTheDocument();
  expect(screen.getByText("세션 상태 병합")).toBeInTheDocument();
  expect(screen.getByText("장소·정보 조회")).toBeInTheDocument();
  expect(screen.getByText("추천 순위 계산")).toBeInTheDocument();
  expect(screen.getByText("답변 생성·정리")).toBeInTheDocument();
  expect(screen.getByText(/첫 글자 도착\(TTFT\) · 240ms/)).toBeInTheDocument();
  expect(screen.getByText(/classify_intent · gemini-2.5-flash · 420ms/)).toBeInTheDocument();
  expect(
    screen.getByText(/extract_recommend_conditions · gemini-2.5-flash · 1.4초/),
  ).toBeInTheDocument();
  expect(screen.getByText(/후보 혼잡도 보강 · 180ms · success/)).toBeInTheDocument();
});
