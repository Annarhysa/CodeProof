import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listEvaluations } from "./api.js";

export default function App() {
  const [evaluations, setEvaluations] = useState([]);

  useEffect(() => {
    listEvaluations().then(setEvaluations);
    const interval = setInterval(() => listEvaluations().then(setEvaluations), 3000);
    return () => clearInterval(interval);
  }, []);

  const done = evaluations.filter((e) => e.status === "DONE");
  const passRate = done.length ? Math.round((done.filter((e) => e.verdict === "PASS").length / done.length) * 100) : null;

  return (
    <div className="container">
      <h1>CodeProof</h1>
      <p style={{ color: "var(--muted)" }}>Independent evaluation and verification layer for AI coding agents.</p>

      <div className="card">
        <strong>Robustly Correct Fix Rate:</strong> {passRate === null ? "n/a" : `${passRate}%`}{" "}
        <span style={{ color: "var(--muted)" }}>({done.length} evaluated)</span>
        <div style={{ marginTop: 8 }}>
          <Link to="/new"><button>+ New Evaluation</button></Link>
        </div>
      </div>

      <h3>Recent Evaluations</h3>
      {evaluations.map((e) => (
        <Link key={e.id} to={`/evaluations/${e.id}`}>
          <div className="card">
            <div><strong>{e.issue_title}</strong></div>
            <div style={{ color: "var(--muted)", fontSize: 12 }}>{e.repo_url}</div>
            <span className={`badge ${e.verdict || e.status}`}>{e.verdict || e.status}</span>
          </div>
        </Link>
      ))}
      {evaluations.length === 0 && <p style={{ color: "var(--muted)" }}>No evaluations yet.</p>}
    </div>
  );
}
