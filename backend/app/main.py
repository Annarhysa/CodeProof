"""
CodeProof backend (P0 vertical slice).

POST /evaluations            create + kick off an evaluation in the background
GET  /evaluations            list evaluations (dashboard)
GET  /evaluations/{id}       full evidence/verdict detail
POST /evaluations/{id}/review human decision (approve/revise/reject/abstain)
GET  /health                 liveness
"""
from __future__ import annotations

import os
import threading
import traceback
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from agents.claude_agent import ClaudeCodingAgent
from agents.gemini_agent import GeminiCodingAgent
from agents.mock import MockCodingAgent
from agents.ollama_agent import OllamaCodingAgent
from backend.app.auth import router as github_auth_router
from backend.app.db import EvaluationRecord, get_session, init_db
from backend.app.github import GitHubError, fetch_issue
from backend.app.schemas import (
    CreateEvaluationRequest,
    EvaluationDetail,
    EvaluationSummary,
    GitHubIssuePreview,
    HumanReviewRequest,
)
from benchmark.playbooks import PLAYBOOKS
from evaluator.pipeline import run_evaluation

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
            status="PENDING",
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        summary = _to_summary(record)

    thread = threading.Thread(target=_run_in_background, args=(evaluation_id, req), daemon=True)
    thread.start()

    return summary


@app.get("/evaluations", response_model=list[EvaluationSummary])
def list_evaluations() -> list[EvaluationSummary]:
    with get_session() as session:
        records = session.query(EvaluationRecord).order_by(EvaluationRecord.created_at.desc()).all()
        return [_to_summary(r) for r in records]


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


def _run_in_background(evaluation_id: str, req: CreateEvaluationRequest) -> None:
    with get_session() as session:
        record = session.get(EvaluationRecord, evaluation_id)
        record.status = "RUNNING"
        session.commit()

    try:
        if req.agent == "claude":
            def agent_factory(sandbox):
                return ClaudeCodingAgent(sandbox)
        elif req.agent == "gemini":
            def agent_factory(sandbox):
                return GeminiCodingAgent(sandbox)
        elif req.agent == "ollama":
            def agent_factory(sandbox):
                return OllamaCodingAgent(sandbox)
        else:
            playbook = PLAYBOOKS[req.benchmark_case_id]

            def agent_factory(sandbox):
                return MockCodingAgent(sandbox, playbook)

        result = run_evaluation(
            evaluation_id=evaluation_id,
            repo_url=req.repo_url,
            issue_title=req.issue_title,
            issue_body=req.issue_body,
            agent_factory=agent_factory,
            commit_sha=req.commit_sha,
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
            session.commit()
    except Exception as exc:  # noqa: BLE001 - surface any pipeline failure as evidence, not a crash
        with get_session() as session:
            record = session.get(EvaluationRecord, evaluation_id)
            record.status = "ERROR"
            record.error = f"{exc}\n{traceback.format_exc()}"
            session.commit()


def _to_summary(r: EvaluationRecord) -> EvaluationSummary:
    return EvaluationSummary(
        id=r.id,
        repo_url=r.repo_url,
        issue_title=r.issue_title,
        status=r.status,
        verdict=r.verdict,
        created_at=r.created_at.isoformat() if r.created_at else None,
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
        error=r.error,
        human_decision=r.human_decision,
        human_notes=r.human_notes,
    )
