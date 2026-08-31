import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listEvaluations } from "./api.js";
import Spinner from "./components/Spinner.jsx";

export default function App() {
  const [evaluations, setEvaluations] = useState([]);

  useEffect(() => {
    listEvaluations().then(setEvaluations);
    const interval = setInterval(() => listEvaluations().then(setEvaluations), 3000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="container">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <h1>CodeProof</h1>
        <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
          <Link to="/archive"><button type="button">Archive</button></Link>
          <Link to="/proof-points"><button type="button">Proof Points</button></Link>
        </div>
      </div>
      <p style={{ color: "var(--muted)" }}>Independent evaluation and verification layer for AI coding agents.</p>
      <Link to="/new"><button>+ New Evaluation</button></Link>

      <h3>Recent Evaluations</h3>
      {evaluations.map((e) => (
        <Link key={e.id} to={`/evaluations/${e.id}`}>
          <div className="card">
            <div><strong>{e.issue_title}</strong></div>
            <div style={{ color: "var(--muted)", fontSize: 12 }}>{e.repo_url}</div>
            {(e.status === "PENDING" || e.status === "RUNNING") ? (
              <Spinner label={e.status} />
            ) : (
              <span className={`badge ${e.verdict || e.status}`}>{e.verdict || e.status}</span>
            )}
          </div>
        </Link>
      ))}
      {evaluations.length === 0 && <p style={{ color: "var(--muted)" }}>No evaluations yet.</p>}
    </div>
  );
}
