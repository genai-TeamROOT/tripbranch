/*
 * 역할: 화면 기록 하나를 되돌릴 때 사진 검색 턴을 알아보는지 검증한다.
 *
 * 사진 검색은 조건 병합을 타지 않아 화면 기록의 payload가 AgentResponse가
 * 아니다. 가르지 못하면 buildAgentMessages가 llm_output을 읽다가 터져 그
 * 대화 전체가 복원되지 않는다.
 */

import { describe, expect, it } from "vitest";
import type { PhotoSimilarPlacesResponse } from "../types";
import { buildPhotoSimilarMessage, isPhotoSimilarRecord } from "./agentMessages";

function record(): PhotoSimilarPlacesResponse & { kind: string } {
  return {
    kind: "photo_similar",
    session_id: "s-1",
    center_name: "성수동",
    candidate_count: 42,
    truncated_count: 0,
    elapsed_ms: 1200,
    places: [{ content_id: "2946087", title: "마우스래빗", similarity: 0.89, photo_count: 5 }],
  };
}

describe("isPhotoSimilarRecord", () => {
  it("표시가 붙은 기록을 알아본다", () => {
    expect(isPhotoSimilarRecord(record())).toBe(true);
  });

  it("표시가 없으면 AgentResponse로 본다", () => {
    // 이 키가 생기기 전의 기록에는 표시가 없다. 없는 쪽이 기존 동작이어야
    // 옛 대화가 그대로 복원된다.
    expect(isPhotoSimilarRecord({ message: "박물관을 찾아봤어요" })).toBe(false);
    expect(isPhotoSimilarRecord(null)).toBe(false);
    expect(isPhotoSimilarRecord(undefined)).toBe(false);
  });
});

describe("buildPhotoSimilarMessage", () => {
  it("결과와 기준점을 그대로 되돌린다", () => {
    const message = buildPhotoSimilarMessage(record());

    expect(message.type).toBe("photo_similar_result");
    if (message.type !== "photo_similar_result") return;
    expect(message.centerName).toBe("성수동");
    expect(message.candidateCount).toBe(42);
    expect(message.places[0].title).toBe("마우스래빗");
    expect(message.status).toBe("done");
  });

  it("사진은 비운다", () => {
    // 원본은 서버가 임베딩만 하고 버렸고 축소본은 그 브라우저에만 있다.
    // 다른 기기에서 열면 가져올 데가 없으므로 사진 자리를 건너뛴다.
    const message = buildPhotoSimilarMessage(record());

    expect(message.type).toBe("photo_similar_result");
    if (message.type !== "photo_similar_result") return;
    expect(message.imageUrl).toBeNull();
  });
});
