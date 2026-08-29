from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class CreateEvaluationRequest(BaseModel):
    repo_url: str
    issue_title: str
    issue_body: str
    commit_sha: str | None = None
    agent: Literal["mock", "claude", "gemini"] = "mock"
    benchmark_case_id: str | None = None  # required for agent="mock" (selects its scripted Playbook)


class EvaluationSummary(BaseModel):
    id: str
    repo_url: str
    issue_title: str
    status: str
    verdict: str | None
    created_at: str | None


class EvaluationDetail(BaseModel):
    id: str
    repo_url: str
    issue_title: str
    issue_body: str
    commit_sha: str | None
    agent_name: str
    status: str
    verdict: str | None
    reason: str | None
    reproduction: dict[str, Any] | None
    patch: dict[str, Any] | None
    test_results: dict[str, Any] | None
    evidence: list[dict[str, Any]] | None
    trajectory: list[dict[str, Any]] | None
    error: str | None
    human_decision: str | None
    human_notes: str | None


class HumanReviewRequest(BaseModel):
    decision: Literal["APPROVE", "REQUEST_REVISION", "REJECT", "ABSTAIN"]
    notes: str | None = None


class GitHubIssuePreview(BaseModel):
    owner: str
    repo: str
    number: int
    title: str
    body: str
    state: str
    html_url: str
    repo_clone_url: str
    repo_default_branch: str
