// TripDispatchContext를 읽는 훅. Provider 밖에서 쓰면 에러를 던진다.
// 사용법: 컴포넌트에서 `const dispatch = useTripDispatch()`로 액션을 보낸다.

import { useContext, type Dispatch } from "react";
import { TripDispatchContext } from "./trip-context";
import type { TripAction } from "./tripReducer";

export function useTripDispatch(): Dispatch<TripAction> {
  const context = useContext(TripDispatchContext);
  if (context === undefined) {
    throw new Error("useTripDispatch must be used within a TripProvider");
  }
  return context;
}
