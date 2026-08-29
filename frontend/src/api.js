const BASE = "/api";

export async function listEvaluations() {
  const res = await fetch(`${BASE}/evaluations`);
  return res.json();
}

export async function getEvaluation(id) {
  const res = await fetch(`${BASE}/evaluations/${id}`);
  return res.json();
}

export async function createEvaluation(payload) {
  const res = await fetch(`${BASE}/evaluations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function fetchGithubIssue(issueUrl) {
  const res = await fetch(`${BASE}/github/issue?url=${encodeURIComponent(issueUrl)}`);
  if (!res.ok) {
    const bodyText = await res.text();
    let message = bodyText;
    try {
      message = JSON.parse(bodyText).detail || bodyText;
    } catch {
      // body wasn't JSON; use raw text
    }
    throw new Error(message);
  }
  return res.json();
}

export const githubLoginUrl = `${BASE}/auth/github/login`;

export async function getGithubMe() {
  const res = await fetch(`${BASE}/auth/github/me`, { credentials: "include" });
  if (!res.ok) return null;
  return res.json();
}

export async function githubLogout() {
  await fetch(`${BASE}/auth/github/logout`, { method: "POST", credentials: "include" });
}

export async function listMyRepos() {
  const res = await fetch(`${BASE}/auth/github/repos`, { credentials: "include" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listRepoIssues(owner, repo) {
  const res = await fetch(`${BASE}/auth/github/repos/${owner}/${repo}/issues`, { credentials: "include" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function submitReview(id, decision, notes) {
  const res = await fetch(`${BASE}/evaluations/${id}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, notes }),
  });
  return res.json();
}
