import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getEvaluation, submitReview } from "../api.js";

export default function EvaluationDetail() {
  const { id } = useParams();
  const [evaluation, setEvaluation] = useState(null);
  const [notes, setNotes] = useState("");

  useEffect(() => {
    let stop = false;
    async function poll() {
      const data = await getEvaluation(id);
      if (!stop) setEvaluation(data);
      if (!stop && (data.status === "PENDING" || data.status === "RUNNING")) {
        setTimeout(poll, 1500);
      }
    }
    poll();
    return () => { stop = true; };
  }, [id]);

  if (!evaluation) return <div className="container">Loading...</div>;

  async function review(decision) {
    const updated = await submitReview(id, decision, notes);
    setEvaluation(updated);
  }

  return (
    <div className="container">
      <h1>{evaluation.issue_title}</h1>
      <span className={`badge ${evaluation.verdict || evaluation.status}`}>{evaluation.verdict || evaluation.status}</span>
      {evaluation.reason && <p>{evaluation.reason}</p>}

      {evaluation.error && (
        <div className="card">
          <h3 style={{ color: "var(--fail)" }}>Pipeline error</h3>
          <pre>{evaluation.error}</pre>
        </div>
      )}

      {evaluation.reproduction && (
        <div className="card">
          <h3>Reproduction</h3>
          <div>Command: <code>{evaluation.reproduction.command}</code></div>
          <div>Status: {evaluation.reproduction.reproduced ? "✓ BUG REPRODUCED" : "⚠ COULD NOT REPRODUCE"}</div>
          <pre>{evaluation.reproduction.observed}</pre>
        </div>
      )}

      {evaluation.patch && (
        <div className="card">
          <h3>Patch</h3>
          <div>{evaluation.patch.explanation}</div>
          <div>Files: {evaluation.patch.files_changed?.join(", ")} (+{evaluation.patch.lines_added}/-{evaluation.patch.lines_removed})</div>
          <pre>{evaluation.patch.diff}</pre>
        </div>
      )}

      {evaluation.test_results && (
        <div className="card">
          <h3>Tests</h3>
          <div>{evaluation.test_results.passed} / {evaluation.test_results.total} passed</div>
        </div>
      )}

      {evaluation.evidence && (
        <div className="card">
          <h3>Evidence Timeline</h3>
          {evaluation.evidence.map((e, i) => (
            <div key={i} className={`timeline-entry ${e.passed === true ? "pass" : e.passed === false ? "fail" : ""}`}>
              <strong>{e.claim}</strong>
              <pre>{e.evidence}</pre>
            </div>
          ))}
        </div>
      )}

      {evaluation.trajectory && (
        <div className="card">
          <h3>Agent Trajectory</h3>
          {evaluation.trajectory.map((s, i) => (
            <div key={i} className="timeline-entry">
              <strong>{s.step_type}</strong>
              <pre>{s.content}</pre>
            </div>
          ))}
        </div>
      )}

      {evaluation.status === "DONE" && (
        <div className="card">
          <h3>Human Review</h3>
          <div>Current decision: {evaluation.human_decision || "none"}</div>
          <textarea placeholder="notes" value={notes} onChange={(e) => setNotes(e.target.value)} style={{ width: "100%" }} />
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button onClick={() => review("APPROVE")}>✓ Approve</button>
            <button onClick={() => review("REQUEST_REVISION")}>↻ Request Revision</button>
            <button onClick={() => review("REJECT")}>✕ Reject</button>
            <button onClick={() => review("ABSTAIN")}>⚠ Abstain</button>
          </div>
        </div>
      )}
    </div>
  );
}
