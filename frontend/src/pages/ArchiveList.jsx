import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listEvaluations, unarchiveEvaluation } from "../api.js";

export default function ArchiveList() {
  const [evaluations, setEvaluations] = useState([]);

  function load() {
    listEvaluations(true).then(setEvaluations);
  }

  useEffect(() => {
    load();
  }, []);

  async function onUnarchive(e, id) {
    e.preventDefault();
    e.stopPropagation();
    await unarchiveEvaluation(id);
    load();
  }

  return (
    <div className="container">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1>Archive</h1>
        <Link to="/"><button type="button">&larr; Back to Dashboard</button></Link>
      </div>
      <p style={{ color: "var(--muted)" }}>Evaluations you've archived — hidden from the main dashboard, still fully viewable.</p>

      {evaluations.map((e) => (
        <Link key={e.id} to={`/evaluations/${e.id}`}>
          <div className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <div><strong>{e.issue_title}</strong></div>
              <div style={{ color: "var(--muted)", fontSize: 12 }}>{e.repo_url}</div>
              <span className={`badge ${e.verdict || e.status}`}>{e.verdict || e.status}</span>
            </div>
            <button type="button" onClick={(ev) => onUnarchive(ev, e.id)}>Unarchive</button>
          </div>
        </Link>
      ))}
      {evaluations.length === 0 && <p style={{ color: "var(--muted)" }}>Nothing archived yet.</p>}
    </div>
  );
}
