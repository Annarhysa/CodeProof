import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getProofPoints } from "../api.js";
import Spinner from "../components/Spinner.jsx";

export default function ProofPoints() {
  const [data, setData] = useState(undefined);

  useEffect(() => {
    getProofPoints().then(setData).catch(() => setData(null));
  }, []);

  const benchmark = data?.benchmark;
  const baseline = data?.baseline_comparison;

  return (
    <div className="container">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1>Proof Points</h1>
        <Link to="/"><button type="button">&larr; Back to Dashboard</button></Link>
      </div>

      <div className="card">
        <h3>An AI coding agent changed your code. Should you trust it?</h3>
        <p>
          CodeProof is an independent evaluation and verification layer for AI coding agents
          (Claude, Gemini, a local Ollama model, or a custom agent). It is not another coding
          assistant, and it does not generate code for you to trust on faith.
        </p>
        <p style={{ color: "var(--muted)" }}>
          The agent makes the claim. CodeProof provides the evidence.
        </p>
      </div>

      <div className="card">
        <h3>What it actually does</h3>
        <ol>
          <li>Clones the target repo into an isolated Docker sandbox — never on your machine</li>
          <li>Installs dependencies deterministically, before the agent gets involved</li>
          <li>Has the agent investigate the repo and try to <strong>reproduce the bug for real</strong> — no reproduction, no verdict</li>
          <li>Lets the agent propose and apply a fix, in that same sandbox</li>
          <li>Re-runs the reproduction and the existing test suite to check the fix actually holds</li>
          <li>Hands the patch to an independent <strong>Skeptic Agent</strong> whose only job is to try to break it</li>
          <li>If anything fails, classifies exactly why (<strong>Failure Autopsy</strong>) instead of a bare error</li>
          <li>Shows the full evidence trail so a human can make the final call</li>
        </ol>
      </div>

      {data === undefined && (
        <div className="card"><Spinner label="Loading real benchmark results..." /></div>
      )}

      {data === null && (
        <div className="card"><p style={{ color: "var(--fail)" }}>Could not load benchmark results.</p></div>
      )}

      {benchmark && (
        <div className="card">
          <h3>Benchmark — Robustly Correct Fix Rate</h3>
          <p style={{ color: "var(--muted)" }}>
            From an actual execution of every seeded benchmark case through the real pipeline —
            not a projection.
          </p>
          <h2 style={{ margin: "8px 0" }}>
            {benchmark.robustly_correct_fix_count} / {benchmark.n_cases} = {Math.round(benchmark.robustly_correct_fix_rate * 100)}%
          </h2>
          <div style={{ color: "var(--muted)", fontSize: 12 }}>Agent: {benchmark.agent} — Skeptic: {benchmark.run_skeptic ? "on" : "off"}</div>
          <table style={{ width: "100%", marginTop: 12, borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "1px solid var(--border)" }}>
                <th style={{ padding: 6 }}>Case</th>
                <th style={{ padding: 6 }}>Difficulty</th>
                <th style={{ padding: 6 }}>Verdict</th>
                <th style={{ padding: 6 }}>Robustly Correct</th>
              </tr>
            </thead>
            <tbody>
              {benchmark.results.map((r) => (
                <tr key={r.case_id} style={{ borderBottom: "1px solid var(--border)" }}>
                  <td style={{ padding: 6 }}>{r.case_id}</td>
                  <td style={{ padding: 6 }}>{r.difficulty}</td>
                  <td style={{ padding: 6 }}><span className={`badge ${r.actual_verdict}`}>{r.actual_verdict}</span></td>
                  <td style={{ padding: 6 }}>{r.robustly_correct_fix ? "✓" : "✗"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {baseline && (
        <div className="card">
          <h3>Baseline vs. CodeProof</h3>
          <p style={{ color: "var(--muted)" }}>
            Baseline = a naive, single-shot agent that reports success as soon as its patch applies
            cleanly — no reproduction check, no test run, no adversarial testing. Real numbers from
            an actual run of both against the same cases.
          </p>
          <p><strong>{baseline.headline}</strong></p>
          <div style={{ display: "flex", gap: 24, marginTop: 12, flexWrap: "wrap" }}>
            <div>
              <div style={{ color: "var(--muted)", fontSize: 12 }}>Baseline claims success</div>
              <div style={{ fontSize: 20 }}>{Math.round(baseline.baseline.claims_success_rate * 100)}%</div>
            </div>
            <div>
              <div style={{ color: "var(--muted)", fontSize: 12 }}>Baseline actually correct</div>
              <div style={{ fontSize: 20 }}>{Math.round(baseline.baseline.actually_correct_rate * 100)}%</div>
            </div>
            <div>
              <div style={{ color: "var(--muted)", fontSize: 12 }}>Baseline false positives</div>
              <div style={{ fontSize: 20, color: baseline.baseline.false_positive_count > 0 ? "var(--fail)" : "inherit" }}>
                {baseline.baseline.false_positive_count}
              </div>
            </div>
            <div>
              <div style={{ color: "var(--muted)", fontSize: 12 }}>CodeProof Robustly Correct</div>
              <div style={{ fontSize: 20, color: "var(--pass)" }}>{Math.round(baseline.codeproof.robustly_correct_fix_rate * 100)}%</div>
            </div>
          </div>
        </div>
      )}

      <div className="card">
        <h3>Honest limitations</h3>
        <ul>
          <li>The benchmark above is a 3-case seed set of real, deliberate, verified bugs — not the 20-30 real historical GitHub issues a full benchmark would need.</li>
          <li>These numbers are from the scripted <code>mock</code> agent, which validates that the <em>pipeline</em> works correctly — not any one live agent's real-world reasoning quality.</li>
          <li>Reproduce this yourself: <code>python -m benchmark.baseline</code> (see REPRODUCIBILITY.md).</li>
        </ul>
      </div>
    </div>
  );
}
