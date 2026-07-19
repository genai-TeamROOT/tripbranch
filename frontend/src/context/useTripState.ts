// TripStateContext를 읽는 훅. Provider 밖에서 쓰면 에러를 던져 실수를 바로 알 수 있게 했다.
// 사용법: 컴포넌트에서 `const state = useTripState()`로 읽기 전용 상태에 접근.

import { useContext } from "react";
import { TripStateContext } from "./trip-context";
import type { TripState } from "./tripReducer";

export function useTripState(): TripState {
  const context = useContext(TripStateContext);
  if (context === undefined) {
    throw new Error("useTripState must be used within a TripProvider");
  }
  return context;
}
