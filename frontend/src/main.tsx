// React 앱 진입점. #root DOM에 <App />을 마운트한다. Vite 기본 스캐폴드 그대로이며
// 이 파일에는 앱 로직을 추가하지 않는다(로직은 App.tsx 이하에서).

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App.tsx";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
