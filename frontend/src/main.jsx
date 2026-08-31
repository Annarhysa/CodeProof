import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import App from "./App.jsx";
import NewEvaluation from "./pages/NewEvaluation.jsx";
import EvaluationDetail from "./pages/EvaluationDetail.jsx";
import ReplayDetail from "./pages/ReplayDetail.jsx";
import ArchiveList from "./pages/ArchiveList.jsx";
import ProofPoints from "./pages/ProofPoints.jsx";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />} />
        <Route path="/new" element={<NewEvaluation />} />
        <Route path="/evaluations/:id" element={<EvaluationDetail />} />
        <Route path="/replay/:groupId" element={<ReplayDetail />} />
        <Route path="/archive" element={<ArchiveList />} />
        <Route path="/proof-points" element={<ProofPoints />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
