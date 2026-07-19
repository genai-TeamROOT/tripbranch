// TripStateContext / TripDispatchContext의 createContext 선언만 있는 파일.
// 컴포넌트(TripContext.tsx)와 컨텍스트 객체를 분리해둔 이유: eslint의
// react-refresh/only-export-components 규칙이 "컴포넌트가 아닌 값과 컴포넌트를 같은 파일에서
// export하지 말라"고 요구하기 때문. 직접 이 파일을 import하지 말고 useTripState/useTripDispatch를 쓸 것.

import { createContext, type Dispatch } from "react";
import type { TripAction, TripState } from "./tripReducer";

export const TripStateContext = createContext<TripState | undefined>(undefined);
export const TripDispatchContext = createContext<Dispatch<TripAction> | undefined>(undefined);
