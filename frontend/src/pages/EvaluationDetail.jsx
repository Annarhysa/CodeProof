import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { archiveEvaluation, getEvaluation, startReplay, submitReview, unarchiveEvaluation } from "../api.js";
import Spinner from "../components/Spinner.jsx";

export default function EvaluationDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [evaluation, setEvaluation] = useState(null);
  const [notes, setNotes] = useState("");
  const [replaying, setReplaying] = useState(false);

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

  if (!evaluation) {
    return (
      <div className="container">
        <Spinner label="Loading evaluation..." />
      </div>
    );
  }

  async function review(decision) {
    const updated = await submitReview(id, decision, notes);
    setEvaluation(updated);
  }

  function editAndRerun() {
    navigate("/new", {
      state: {
        repoUrl: evaluation.repo_url,
        issueTitle: evaluation.issue_title,
        issueBody: evaluation.issue_body,
        agent: evaluation.agent_name,
      },
    });
  }

  async function runReplay() {
    setReplaying(true);
    try {
      const group = await startReplay(id, 3);
      navigate(`/replay/${group.id}`);
    } catch (err) {
      alert(String(err.message || err));
    } finally {
      setReplaying(false);
    }
  }

  async function toggleArchive() {
    const updated = evaluation.archived ? await unarchiveEvaluation(id) : await archiveEvaluation(id);
    setEvaluation(updated);
  }

  const inProgress = evaluation.status === "PENDING" || evaluation.status === "RUNNING";
  const finished = evaluation.status === "DONE" || evaluation.status === "ERROR";

  return (
    <div className="container">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
        <h1 style={{ margin: 0 }}>{evaluation.issue_title}</h1>
        <button type="button" onClick={toggleArchive} style={{ flexShrink: 0 }}>
          {evaluation.archived ? "Unarchive" : "📦 Archive"}
        </button>
      </div>
      <span className={`badge ${evaluation.verdict || evaluation.status}`}>{evaluation.verdict || evaluation.status}</span>
      {evaluation.archived && <span className="badge" style={{ marginLeft: 8, background: "rgba(107,114,128,.15)", color: "var(--muted)" }}>ARCHIVED</span>}
      {evaluation.reason && <p>{evaluation.reason}</p>}

      {inProgress && (
        <div className="card progress-panel">
          <div className="spinner" />
          <h3>Evaluation in progress ({evaluation.status.toLowerCase()})</h3>
          <p style={{ color: "var(--muted)" }}>
            This can take 2–3 minutes (sometimes longer with a live agent on a large repo). This
            page updates automatically — feel free to head back and start another evaluation while
            you wait.
          </p>
          <Link to="/">
            <button type="button">Go to Dashboard</button>
          </Link>
        </div>
      )}

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

      {evaluation.skeptic && (
        <div className="card">
          <h3>Skeptic (Adversarial Testing)</h3>
          <div>{evaluation.skeptic.summary}</div>
          {evaluation.skeptic.scenarios?.map((s, i) => (
            <div key={i} className={`timeline-entry ${s.passed ? "pass" : "fail"}`}>
              <strong>{s.passed ? "✓" : "✗"} {s.name}</strong>
              <div style={{ fontSize: 12, color: "var(--muted)" }}>{s.notes}</div>
            </div>
          ))}
        </div>
      )}

      {evaluation.failure_autopsy && (
        <div className="card">
          <h3>Failure Autopsy</h3>
          <div><strong>Category:</strong> {evaluation.failure_autopsy.category}</div>
          <div><strong>Earliest detectable point:</strong> {evaluation.failure_autopsy.earliest_detectable_point}</div>
          <div style={{ marginTop: 8 }}><strong>Likely cause:</strong></div>
          <p>{evaluation.failure_autopsy.likely_cause}</p>
          <div><strong>Recommended action:</strong></div>
          <p>{evaluation.failure_autopsy.recommended_action}</p>
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

      {finished && (
        <div className="card" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button type="button" onClick={editAndRerun}>✎ Edit &amp; Re-run</button>
          {evaluation.status === "DONE" && !evaluation.replay_group_id && (
            <button type="button" onClick={runReplay} disabled={replaying}>
              {replaying ? <Spinner label="Starting..." /> : "↻ Replay (3x, check reproducibility)"}
            </button>
          )}
          <Link to="/new"><button type="button">+ New Evaluation</button></Link>
          <Link to="/"><button type="button">View All Evaluations</button></Link>
        </div>
      )}
    </div>
  );
}
