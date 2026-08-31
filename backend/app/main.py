"""
CodeProof backend.

POST /evaluations               create + kick off an evaluation in the background
GET  /evaluations               list evaluations (dashboard)
GET  /evaluations/{id}          full evidence/verdict detail
POST /evaluations/{id}/review   human decision (approve/revise/reject/abstain)
POST /evaluations/{id}/replay   run the same evaluation N times (reproducibility)
GET  /replay/{group_id}         replay group summary + constituent evaluations
GET  /health                    liveness
"""
from __future__ import annotations

import json
import os
import threading
import traceback
import uuid
from collections import Counter
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from agents.base import CodingAgent
from agents.claude_agent import ClaudeCodingAgent
from agents.gemini_agent import GeminiCodingAgent
from agents.mock import MockCodingAgent
from agents.ollama_agent import OllamaCodingAgent
from backend.app.auth import router as github_auth_router
from backend.app.db import EvaluationRecord, ReplayGroup, get_session, init_db
from backend.app.github import GitHubError, fetch_issue
from backend.app.schemas import (
    CreateEvaluationRequest,
    EvaluationDetail,
    EvaluationSummary,
    GitHubIssuePreview,
    HumanReviewRequest,
    ProofPointsResponse,
    ReplayRequest,
    ReplaySummaryResponse,
)
from benchmark.playbooks import PLAYBOOKS
from evaluator.pipeline import run_evaluation
from sandbox.runner import Sandbox

BENCHMARK_RESULTS_DIR = Path(__file__).resolve().parents[2] / "benchmark" / "results"

load_dotenv()

app = FastAPI(title="CodeProof API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,  # required so the browser sends the session cookie for GitHub OAuth
)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET_KEY", "dev-insecure-change-me"),
)

app.include_router(github_auth_router)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/github/issue", response_model=GitHubIssuePreview)
def get_github_issue(url: str) -> GitHubIssuePreview:
    try:
        info = fetch_issue(url)
    except GitHubError as exc:
        raise HTTPException(400, str(exc))
    return GitHubIssuePreview(
        owner=info.owner, repo=info.repo, number=info.number, title=info.title, body=info.body,
        state=info.state, html_url=info.html_url, repo_clone_url=info.repo_clone_url,
        repo_default_branch=info.repo_default_branch,
    )


@app.post("/evaluations", response_model=EvaluationSummary, status_code=201)
def create_evaluation(req: CreateEvaluationRequest) -> EvaluationSummary:
    if req.agent == "mock" and req.benchmark_case_id not in PLAYBOOKS:
        raise HTTPException(
            400,
            f"benchmark_case_id must be one of {list(PLAYBOOKS)} for the mock agent "
            "(no live LLM adapter is configured yet).",
        )

    evaluation_id = str(uuid.uuid4())[:8]
    with get_session() as session:
        record = EvaluationRecord(
            id=evaluation_id,
            repo_url=req.repo_url,
            issue_title=req.issue_title,
            issue_body=req.issue_body,
            commit_sha=req.commit_sha,
            agent_name=req.agent,
            benchmark_case_id=req.benchmark_case_id,
            status="PENDING",
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        summary = _to_summary(record)

    thread = threading.Thread(target=_run_in_background, args=(evaluation_id, req, None), daemon=True)
    thread.start()

    return summary


@app.get("/evaluations", response_model=list[EvaluationSummary])
def list_evaluations(archived: bool = False) -> list[EvaluationSummary]:
    with get_session() as session:
        records = (
            session.query(EvaluationRecord)
            .filter(EvaluationRecord.archived == archived)
            .order_by(EvaluationRecord.created_at.desc())
            .all()
        )
        return [_to_summary(r) for r in records]


@app.post("/evaluations/{evaluation_id}/archive", response_model=EvaluationDetail)
def archive_evaluation(evaluation_id: str) -> EvaluationDetail:
    with get_session() as session:
        record = session.get(EvaluationRecord, evaluation_id)
        if record is None:
            raise HTTPException(404, "evaluation not found")
        record.archived = True
        session.commit()
        session.refresh(record)
        return _to_detail(record)


@app.post("/evaluations/{evaluation_id}/unarchive", response_model=EvaluationDetail)
def unarchive_evaluation(evaluation_id: str) -> EvaluationDetail:
    with get_session() as session:
        record = session.get(EvaluationRecord, evaluation_id)
        if record is None:
            raise HTTPException(404, "evaluation not found")
        record.archived = False
        session.commit()
        session.refresh(record)
        return _to_detail(record)


@app.get("/proof-points", response_model=ProofPointsResponse)
def get_proof_points() -> ProofPointsResponse:
    """Real numbers from the most recent actual benchmark/baseline runs
    (benchmark/results/*.json) — never hardcoded, never invented. Fields
    are null if no run has been executed yet on this machine."""
    return ProofPointsResponse(
        benchmark=_latest_json(BENCHMARK_RESULTS_DIR, "benchmark_*.json"),
        baseline_comparison=_latest_json(BENCHMARK_RESULTS_DIR, "baseline_vs_codeproof_*.json"),
    )


def _latest_json(directory: Path, pattern: str) -> dict | None:
    if not directory.exists():
        return None
    files = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    return json.loads(files[0].read_text())


@app.get("/evaluations/{evaluation_id}", response_model=EvaluationDetail)
def get_evaluation(evaluation_id: str) -> EvaluationDetail:
    with get_session() as session:
        record = session.get(EvaluationRecord, evaluation_id)
        if record is None:
            raise HTTPException(404, "evaluation not found")
        return _to_detail(record)


@app.post("/evaluations/{evaluation_id}/review", response_model=EvaluationDetail)
def review_evaluation(evaluation_id: str, req: HumanReviewRequest) -> EvaluationDetail:
    with get_session() as session:
        record = session.get(EvaluationRecord, evaluation_id)
        if record is None:
            raise HTTPException(404, "evaluation not found")
        record.human_decision = req.decision
        record.human_notes = req.notes
        session.commit()
        session.refresh(record)
        return _to_detail(record)


@app.post("/evaluations/{evaluation_id}/replay", response_model=ReplaySummaryResponse, status_code=201)
def replay_evaluation(evaluation_id: str, req: ReplayRequest) -> ReplaySummaryResponse:
    """Phase 9 — Reproducibility. Re-runs the same inputs `n` times (fresh
    clone/sandbox/agent each time) and reports verdict consistency. Cost
    warning: this is n full evaluations, each its own set of live-agent API
    calls if using a live agent — same cost as running the evaluation n
    times manually."""
    if req.n < 2 or req.n > 10:
        raise HTTPException(400, "n must be between 2 and 10")

    with get_session() as session:
        source = session.get(EvaluationRecord, evaluation_id)
        if source is None:
            raise HTTPException(404, "evaluation not found")
        base_req = CreateEvaluationRequest(
            repo_url=source.repo_url,
            issue_title=source.issue_title,
            issue_body=source.issue_body,
            commit_sha=source.commit_sha,
            agent=source.agent_name,  # type: ignore[arg-type]
            benchmark_case_id=source.benchmark_case_id,
            run_skeptic=False,  # replay is about verdict consistency, not re-spending on adversarial testing each run
        )
        group_id = str(uuid.uuid4())[:8]
        group = ReplayGroup(
            id=group_id,
            repo_url=source.repo_url,
            issue_title=source.issue_title,
            issue_body=source.issue_body,
            agent_name=source.agent_name,
            n=req.n,
            status="RUNNING",
        )
        session.add(group)
        session.commit()

    thread = threading.Thread(target=_run_replay_in_background, args=(group_id, base_req, req.n), daemon=True)
    thread.start()

    return _to_replay_summary(group_id)


@app.get("/replay/{group_id}", response_model=ReplaySummaryResponse)
def get_replay(group_id: str) -> ReplaySummaryResponse:
    return _to_replay_summary(group_id)


def _agent_factory_for(req: CreateEvaluationRequest) -> Callable[[Sandbox], CodingAgent]:
    if req.agent == "claude":
        return lambda sandbox: ClaudeCodingAgent(sandbox)
    if req.agent == "gemini":
        return lambda sandbox: GeminiCodingAgent(sandbox)
    if req.agent == "ollama":
        return lambda sandbox: OllamaCodingAgent(sandbox)
    playbook = PLAYBOOKS[req.benchmark_case_id]
    return lambda sandbox: MockCodingAgent(sandbox, playbook)


def _run_in_background(evaluation_id: str, req: CreateEvaluationRequest, replay_group_id: str | None) -> None:
    with get_session() as session:
        record = session.get(EvaluationRecord, evaluation_id)
        record.status = "RUNNING"
        if replay_group_id:
            record.replay_group_id = replay_group_id
        session.commit()

    try:
        agent_factory = _agent_factory_for(req)
        result = run_evaluation(
            evaluation_id=evaluation_id,
            repo_url=req.repo_url,
            issue_title=req.issue_title,
            issue_body=req.issue_body,
            agent_factory=agent_factory,
            commit_sha=req.commit_sha,
            run_skeptic=req.run_skeptic,
        )
        with get_session() as session:
            record = session.get(EvaluationRecord, evaluation_id)
            record.status = "DONE"
            record.verdict = result.verdict
            record.reason = result.reason
            record.reproduction = result.reproduction
            record.patch = result.patch
            record.test_results = result.test_results
            record.evidence = result.evidence
            record.trajectory = result.trajectory
            record.skeptic = result.skeptic
            record.failure_autopsy = result.failure_autopsy
            session.commit()
    except Exception as exc:  # noqa: BLE001 - surface any pipeline failure as evidence, not a crash
        with get_session() as session:
            record = session.get(EvaluationRecord, evaluation_id)
            record.status = "ERROR"
            record.error = f"{exc}\n{traceback.format_exc()}"
            session.commit()


def _run_replay_in_background(group_id: str, base_req: CreateEvaluationRequest, n: int) -> None:
    verdicts: list[str] = []
    for i in range(n):
        run_id = f"{group_id}-{i + 1}"
        with get_session() as session:
            session.add(EvaluationRecord(
                id=run_id,
                repo_url=base_req.repo_url,
                issue_title=f"{base_req.issue_title} (replay {i + 1}/{n})",
                issue_body=base_req.issue_body,
                commit_sha=base_req.commit_sha,
                agent_name=base_req.agent,
                benchmark_case_id=base_req.benchmark_case_id,
                status="PENDING",
            ))
            session.commit()
        _run_in_background(run_id, base_req, group_id)
        with get_session() as session:
            record = session.get(EvaluationRecord, run_id)
            if record and record.verdict:
                verdicts.append(record.verdict)

    counts = dict(Counter(verdicts))
    modal = Counter(verdicts).most_common(1)[0][0] if verdicts else None
    consistent = counts.get(modal, 0) if modal else 0
    with get_session() as session:
        group = session.get(ReplayGroup, group_id)
        group.status = "DONE"
        group.consistency_summary = {
            "verdicts": verdicts,
            "verdict_counts": counts,
            "modal_verdict": modal,
            "consistent_count": consistent,
            "consistency_rate": round(consistent / len(verdicts), 3) if verdicts else 0.0,
        }
        session.commit()


def _to_summary(r: EvaluationRecord) -> EvaluationSummary:
    return EvaluationSummary(
        id=r.id,
        repo_url=r.repo_url,
        issue_title=r.issue_title,
        status=r.status,
        verdict=r.verdict,
        created_at=r.created_at.isoformat() if r.created_at else None,
        archived=bool(r.archived),
    )


def _to_detail(r: EvaluationRecord) -> EvaluationDetail:
    return EvaluationDetail(
        id=r.id,
        repo_url=r.repo_url,
        issue_title=r.issue_title,
        issue_body=r.issue_body,
        commit_sha=r.commit_sha,
        agent_name=r.agent_name,
        status=r.status,
        verdict=r.verdict,
        reason=r.reason,
        reproduction=r.reproduction,
        patch=r.patch,
        test_results=r.test_results,
        evidence=r.evidence,
        trajectory=r.trajectory,
        skeptic=r.skeptic,
        failure_autopsy=r.failure_autopsy,
        error=r.error,
        human_decision=r.human_decision,
        human_notes=r.human_notes,
        replay_group_id=r.replay_group_id,
        archived=bool(r.archived),
    )


def _to_replay_summary(group_id: str) -> ReplaySummaryResponse:
    with get_session() as session:
        group = session.get(ReplayGroup, group_id)
        if group is None:
            raise HTTPException(404, "replay group not found")
        runs = (
            session.query(EvaluationRecord)
            .filter(EvaluationRecord.replay_group_id == group_id)
            .order_by(EvaluationRecord.created_at)
            .all()
        )
        return ReplaySummaryResponse(
            id=group.id,
            repo_url=group.repo_url,
            issue_title=group.issue_title,
            agent_name=group.agent_name,
            n=group.n,
            status=group.status,
            consistency_summary=group.consistency_summary,
            evaluations=[_to_summary(r) for r in runs],
        )
