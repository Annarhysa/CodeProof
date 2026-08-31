import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getReplay } from "../api.js";
import Spinner from "../components/Spinner.jsx";

export default function ReplayDetail() {
  const { groupId } = useParams();
  const [replay, setReplay] = useState(null);

  useEffect(() => {
    let stop = false;
    async function poll() {
      const data = await getReplay(groupId);
      if (!stop) setReplay(data);
      if (!stop && data.status === "RUNNING") setTimeout(poll, 2000);
    }
    poll();
    return () => { stop = true; };
  }, [groupId]);

  if (!replay) return <div className="container"><Spinner label="Loading replay..." /></div>;

  const summary = replay.consistency_summary;

  return (
    <div className="container">
      <h1>Reproducibility Replay</h1>
      <p style={{ color: "var(--muted)" }}>{replay.issue_title} — {replay.agent_name} — {replay.n} runs</p>

      <div className="card">
        {replay.status === "RUNNING" && <Spinner label={`Running (${replay.evaluations.length}/${replay.n} started)...`} />}
        {summary && (
          <>
            <h3>{summary.consistent_count} / {replay.n} consistent ({Math.round(summary.consistency_rate * 100)}%)</h3>
            <div>Modal verdict: <span className={`badge ${summary.modal_verdict}`}>{summary.modal_verdict}</span></div>
            <div style={{ marginTop: 8 }}>
              {Object.entries(summary.verdict_counts).map(([v, count]) => (
                <span key={v} className={`badge ${v}`} style={{ marginRight: 8 }}>{v}: {count}</span>
              ))}
            </div>
          </>
        )}
      </div>

      <h3>Individual Runs</h3>
      {replay.evaluations.map((e) => (
        <Link key={e.id} to={`/evaluations/${e.id}`}>
          <div className="card">
            <div><strong>{e.issue_title}</strong></div>
            {(e.status === "PENDING" || e.status === "RUNNING") ? (
              <Spinner label={e.status} />
            ) : (
              <span className={`badge ${e.verdict || e.status}`}>{e.verdict || e.status}</span>
            )}
          </div>
        </Link>
      ))}
    </div>
  );
}
