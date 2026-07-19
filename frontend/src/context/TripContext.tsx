// TripProvider 컴포넌트. useReducer(tripReducer)로 상태를 만들고, sessionStorage에서
// 복구(loadState)하며, 상태가 바뀔 때마다 저장(saveState)한다.
// 사용법: App.tsx 최상단에서 한 번만 감싸면 되고, 하위 컴포넌트는 useTripState/useTripDispatch로 접근.

import { useEffect, useReducer, type ReactNode } from "react";
import { initialTripState, tripReducer } from "./tripReducer";
import { loadState, saveState } from "./storage";
import { TripDispatchContext, TripStateContext } from "./trip-context";

export function TripProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(
    tripReducer,
    initialTripState,
    () => loadState() ?? initialTripState,
  );

  useEffect(() => {
    saveState(state);
  }, [state]);

  return (
    <TripStateContext.Provider value={state}>
      <TripDispatchContext.Provider value={dispatch}>{children}</TripDispatchContext.Provider>
    </TripStateContext.Provider>
  );
}
