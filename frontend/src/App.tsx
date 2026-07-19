// 앱 최상위 컴포넌트. TripProvider(Context)로 감싸고 react-router-dom으로 3개 라우트
// (/, /confirm, /results)를 연결한다. /confirm과 /results는 RequireConditions로 보호된다.
// 사용법: 새 페이지/라우트를 추가할 땐 이 파일에 <Route>를 등록하고, 상태가 필요한
// 페이지라면 RequireConditions로 감쌀지 검토할 것.

import { BrowserRouter, Routes, Route } from "react-router-dom";
import { TripProvider } from "./context/TripContext";
import { RequireConditions } from "./routes/RequireConditions";
import { InputPage } from "./pages/InputPage";
import { ConfirmPage } from "./pages/ConfirmPage";
import { ResultsPage } from "./pages/ResultsPage";

function App() {
  return (
    <TripProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<InputPage />} />
          <Route
            path="/confirm"
            element={
              <RequireConditions>
                <ConfirmPage />
              </RequireConditions>
            }
          />
          <Route
            path="/results"
            element={
              <RequireConditions>
                <ResultsPage />
              </RequireConditions>
            }
          />
        </Routes>
      </BrowserRouter>
    </TripProvider>
  );
}

export default App;
