import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import App from "./App.jsx";
import NewEvaluation from "./pages/NewEvaluation.jsx";
import EvaluationDetail from "./pages/EvaluationDetail.jsx";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />} />
        <Route path="/new" element={<NewEvaluation />} />
        <Route path="/evaluations/:id" element={<EvaluationDetail />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
