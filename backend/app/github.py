"""
GitHub issue input (spec Phase 2). Fetches a real issue's title/body/repo
metadata via the GitHub REST API so a user can paste an issue URL instead of
typing everything by hand. Read-only — never writes to GitHub.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

import requests

GITHUB_API = "https://api.github.com"
_ISSUE_URL_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<number>\d+)/?$"
)


class GitHubError(RuntimeError):
    pass


@dataclass
class IssueInfo:
    owner: str
    repo: str
    number: int
    title: str
    body: str
    state: str
    html_url: str
    repo_clone_url: str
    repo_default_branch: str


def parse_issue_url(issue_url: str) -> tuple[str, str, int]:
    match = _ISSUE_URL_RE.match(issue_url.strip())
    if not match:
        raise GitHubError(
            f"Not a recognizable GitHub issue URL: {issue_url!r}. "
            "Expected https://github.com/<owner>/<repo>/issues/<number>"
        )
    return match.group("owner"), match.group("repo"), int(match.group("number"))


def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_issue(issue_url: str, timeout: int = 15) -> IssueInfo:
    owner, repo, number = parse_issue_url(issue_url)

    issue_resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/issues/{number}", headers=_headers(), timeout=timeout,
    )
    if issue_resp.status_code == 404:
        raise GitHubError(f"Issue not found (or private + no GITHUB_TOKEN): {issue_url}")
    if issue_resp.status_code == 403:
        raise GitHubError("GitHub API rate-limited or forbidden — set GITHUB_TOKEN in .env to raise the limit.")
    if issue_resp.status_code != 200:
        raise GitHubError(f"GitHub API error {issue_resp.status_code}: {issue_resp.text[:300]}")
    issue_data = issue_resp.json()

    if "pull_request" in issue_data:
        raise GitHubError(f"{issue_url} is a pull request, not an issue.")

    repo_resp = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}", headers=_headers(), timeout=timeout)
    if repo_resp.status_code != 200:
        raise GitHubError(f"Could not fetch repository metadata for {owner}/{repo}: {repo_resp.status_code}")
    repo_data = repo_resp.json()

    return IssueInfo(
        owner=owner,
        repo=repo,
        number=number,
        title=issue_data.get("title", ""),
        body=issue_data.get("body") or "",
        state=issue_data.get("state", "unknown"),
        html_url=issue_data.get("html_url", issue_url),
        repo_clone_url=repo_data.get("clone_url", f"https://github.com/{owner}/{repo}.git"),
        repo_default_branch=repo_data.get("default_branch", "main"),
    )
