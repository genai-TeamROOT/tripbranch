// sessionStorage 저장/복구 유틸(storage.ts) 테스트: 정상 저장/복구, 잘못된 데이터/버전
// 불일치 시 null로 무시되는지, clearState가 실제로 지우는지 확인한다.

import { beforeEach, describe, expect, it } from "vitest";
import { clearState, loadState, saveState } from "./storage";
import { initialTripState } from "./tripReducer";

describe("session storage persistence", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("returns null when nothing is stored", () => {
    expect(loadState()).toBeNull();
  });

  it("saves and restores state", () => {
    const state = { ...initialTripState, user_input: "경복궁 근처 카페" };
    saveState(state);

    expect(loadState()).toEqual(state);
  });

  it("ignores invalid stored data", () => {
    sessionStorage.setItem("tripbranch_state", JSON.stringify({ version: 1, state: { foo: 1 } }));
    expect(loadState()).toBeNull();
  });

  it("ignores stored data with a mismatched version", () => {
    saveState(initialTripState);
    const raw = JSON.parse(sessionStorage.getItem("tripbranch_state")!);
    sessionStorage.setItem(
      "tripbranch_state",
      JSON.stringify({ ...raw, version: raw.version + 1 }),
    );

    expect(loadState()).toBeNull();
  });

  it("clears stored state", () => {
    saveState(initialTripState);
    clearState();
    expect(loadState()).toBeNull();
  });
});
