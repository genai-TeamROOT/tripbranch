import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import type { ReactNode } from "react";
import { TripProvider, useTripState } from "./state/TripContext";
import { InputPage } from "./pages/InputPage";
import { ConfirmPage } from "./pages/ConfirmPage";
import { ResultsPage } from "./pages/ResultsPage";

function RequireConditions({ children }: { children: ReactNode }) {
  const { interpreted_conditions } = useTripState();
  return interpreted_conditions ? children : <Navigate to="/" replace />;
}

function RequireResults({ children }: { children: ReactNode }) {
  const { interpreted_conditions, recommendations, unverified_recommendations } = useTripState();
  const hasResults = recommendations.length > 0 || unverified_recommendations.length > 0;
  return interpreted_conditions && hasResults ? children : <Navigate to="/" replace />;
}

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
              <RequireResults>
                <ResultsPage />
              </RequireResults>
            }
          />
        </Routes>
      </BrowserRouter>
    </TripProvider>
  );
}

export default App;
