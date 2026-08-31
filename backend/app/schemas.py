from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class CreateEvaluationRequest(BaseModel):
    repo_url: str
    issue_title: str
    issue_body: str
    commit_sha: str | None = None
    agent: Literal["mock", "claude", "gemini", "ollama"] = "mock"
    benchmark_case_id: str | None = None  # required for agent="mock" (selects its scripted Playbook)
    run_skeptic: bool = True  # adversarial testing after an otherwise-PASS result; costs extra agent turns


class EvaluationSummary(BaseModel):
    id: str
    repo_url: str
    issue_title: str
    status: str
    verdict: str | None
    created_at: str | None
    archived: bool


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
    skeptic: dict[str, Any] | None
    failure_autopsy: dict[str, Any] | None
    error: str | None
    human_decision: str | None
    human_notes: str | None
    replay_group_id: str | None
    archived: bool


class ReplayRequest(BaseModel):
    n: int = 3


class ReplaySummaryResponse(BaseModel):
    id: str
    repo_url: str
    issue_title: str
    agent_name: str
    n: int
    status: str
    consistency_summary: dict[str, Any] | None
    evaluations: list[EvaluationSummary]


class HumanReviewRequest(BaseModel):
    decision: Literal["APPROVE", "REQUEST_REVISION", "REJECT", "ABSTAIN"]
    notes: str | None = None


class ProofPointsResponse(BaseModel):
    benchmark: dict[str, Any] | None  # latest benchmark/results/benchmark_*.json
    baseline_comparison: dict[str, Any] | None  # latest benchmark/results/baseline_vs_codeproof_*.json


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
