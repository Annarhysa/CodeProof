import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  createEvaluation,
  fetchGithubIssue,
  getGithubMe,
  githubLoginUrl,
  githubLogout,
  listMyRepos,
  listRepoIssues,
} from "../api.js";

export default function NewEvaluation() {
  const navigate = useNavigate();

  // GitHub OAuth connect -> repo picker -> issue picker
  const [githubUser, setGithubUser] = useState(undefined); // undefined = loading, null = not connected
  const [repos, setRepos] = useState([]);
  const [reposLoading, setReposLoading] = useState(false);
  const [selectedRepo, setSelectedRepo] = useState("");
  const [issues, setIssues] = useState([]);
  const [issuesLoading, setIssuesLoading] = useState(false);
  const [pickerError, setPickerError] = useState(null);

  // Paste-a-URL fallback
  const [githubUrl, setGithubUrl] = useState("");
  const [fetchingIssue, setFetchingIssue] = useState(false);
  const [githubError, setGithubError] = useState(null);

  const [issuePreview, setIssuePreview] = useState(null);
  const [repoUrl, setRepoUrl] = useState("");
  const [issueTitle, setIssueTitle] = useState("");
  const [issueBody, setIssueBody] = useState("");
  const [agent, setAgent] = useState("gemini");
  const [benchmarkCaseId, setBenchmarkCaseId] = useState("sample-001-average-int-division");
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    getGithubMe().then(setGithubUser).catch(() => setGithubUser(null));
  }, []);

  useEffect(() => {
    if (!githubUser) return;
    setReposLoading(true);
    setPickerError(null);
    listMyRepos()
      .then(setRepos)
      .catch((err) => setPickerError(String(err.message || err)))
      .finally(() => setReposLoading(false));
  }, [githubUser]);

  async function onSelectRepo(fullName) {
    setSelectedRepo(fullName);
    setIssues([]);
    if (!fullName) return;
    const [owner, repo] = fullName.split("/");
    setIssuesLoading(true);
    setPickerError(null);
    try {
      setIssues(await listRepoIssues(owner, repo));
    } catch (err) {
      setPickerError(String(err.message || err));
    } finally {
      setIssuesLoading(false);
    }
  }

  async function onSelectIssue(issueUrl) {
    if (!issueUrl) return;
    await loadIssuePreview(issueUrl);
  }

  async function loadIssuePreview(url) {
    setGithubError(null);
    setPickerError(null);
    try {
      const info = await fetchGithubIssue(url);
      setIssuePreview(info);
      setRepoUrl(info.repo_clone_url);
      setIssueTitle(info.title);
      setIssueBody(info.body);
    } catch (err) {
      setPickerError(String(err.message || err));
    }
  }

  async function onFetchIssueByUrl(e) {
    e.preventDefault();
    setFetchingIssue(true);
    setGithubError(null);
    setIssuePreview(null);
    try {
      await loadIssuePreview(githubUrl);
    } catch (err) {
      setGithubError(String(err.message || err));
    } finally {
      setFetchingIssue(false);
    }
  }

  async function onDisconnect() {
    await githubLogout();
    setGithubUser(null);
    setRepos([]);
    setSelectedRepo("");
    setIssues([]);
  }

  async function onSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const evaluation = await createEvaluation({
        repo_url: repoUrl,
        issue_title: issueTitle,
        issue_body: issueBody,
        agent,
        benchmark_case_id: agent === "mock" ? benchmarkCaseId : null,
      });
      navigate(`/evaluations/${evaluation.id}`);
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="container">
      <h1>New Evaluation</h1>

      <div className="card">
        <h3>Connect GitHub</h3>
        {githubUser === undefined && <p style={{ color: "var(--muted)" }}>Checking connection...</p>}
        {githubUser === null && (
          <a href={githubLoginUrl}>
            <button type="button">Connect GitHub</button>
          </a>
        )}
        {githubUser && (
          <>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span>Connected as <strong>{githubUser.login}</strong></span>
              <button type="button" onClick={onDisconnect}>Disconnect</button>
            </div>
            <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
              <label>
                Repository
                <select
                  value={selectedRepo}
                  onChange={(e) => onSelectRepo(e.target.value)}
                  style={{ width: "100%" }}
                  disabled={reposLoading}
                >
                  <option value="">{reposLoading ? "Loading repositories..." : "Select a repository"}</option>
                  {repos.map((r) => (
                    <option key={r.full_name} value={r.full_name}>
                      {r.full_name} {r.private ? "(private)" : ""} — {r.open_issues_count} open issue(s)
                    </option>
                  ))}
                </select>
              </label>
              {selectedRepo && (
                <label>
                  Issue
                  <select onChange={(e) => onSelectIssue(e.target.value)} style={{ width: "100%" }} disabled={issuesLoading}>
                    <option value="">{issuesLoading ? "Loading issues..." : `Select an issue (${issues.length} open)`}</option>
                    {issues.map((i) => (
                      <option key={i.number} value={i.html_url}>
                        #{i.number} — {i.title}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </div>
          </>
        )}
        {pickerError && <pre style={{ color: "var(--fail)" }}>{pickerError}</pre>}
      </div>

      <details className="card">
        <summary style={{ cursor: "pointer" }}>Or paste a GitHub issue URL directly</summary>
        <form onSubmit={onFetchIssueByUrl} style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
          <input
            value={githubUrl}
            onChange={(e) => setGithubUrl(e.target.value)}
            placeholder="https://github.com/owner/repo/issues/123"
            style={{ width: "100%" }}
          />
          {githubError && <pre style={{ color: "var(--fail)" }}>{githubError}</pre>}
          <button type="submit" disabled={fetchingIssue || !githubUrl}>
            {fetchingIssue ? "Fetching..." : "Load Issue"}
          </button>
        </form>
      </details>

      {issuePreview && (
        <div className="card">
          <h3>ISSUE</h3>
          <div><strong>Repository:</strong> {issuePreview.owner}/{issuePreview.repo}</div>
          <div><strong>Issue number:</strong> #{issuePreview.number}</div>
          <div><strong>Status:</strong> {issuePreview.state}</div>
          <div style={{ marginTop: 8 }}><strong>Description:</strong></div>
          <pre>{issuePreview.body || "(no description)"}</pre>
        </div>
      )}

      <form onSubmit={onSubmit} className="card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <label>
          Repository URL (auto-filled from GitHub, or paste a local path / git URL directly)
          <input value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} required style={{ width: "100%" }} />
        </label>
        <label>
          Issue title
          <input value={issueTitle} onChange={(e) => setIssueTitle(e.target.value)} required style={{ width: "100%" }} />
        </label>
        <label>
          Issue description
          <textarea value={issueBody} onChange={(e) => setIssueBody(e.target.value)} rows={4} style={{ width: "100%" }} />
        </label>
        <label>
          Agent
          <select value={agent} onChange={(e) => setAgent(e.target.value)} style={{ width: "100%" }}>
            <option value="gemini">gemini (live, reasons about any repo — needs GEMINI_API_KEY)</option>
            <option value="claude">claude (live, reasons about any repo — needs ANTHROPIC_API_KEY)</option>
            <option value="mock">mock (scripted, no LLM — only works on the seeded benchmark case)</option>
          </select>
        </label>
        {agent === "mock" && (
          <label>
            Benchmark playbook
            <input value={benchmarkCaseId} onChange={(e) => setBenchmarkCaseId(e.target.value)} style={{ width: "100%" }} />
          </label>
        )}
        {error && <pre style={{ color: "var(--fail)" }}>{error}</pre>}
        <button type="submit" disabled={submitting}>{submitting ? "Starting..." : "[ START EVALUATION ]"}</button>
      </form>
    </div>
  );
}
