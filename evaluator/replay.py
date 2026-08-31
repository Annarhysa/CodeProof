"""
Phase 9 — Reproducibility / Replay (spec section 14).

Runs the same evaluation N times and reports how consistent the verdict is.
Each run gets its own fresh clone, sandbox, and agent instance (via
run_evaluation) — nothing is shared between replay runs except the inputs,
so consistency here reflects genuine run-to-run variance (model
non-determinism, transient infra issues), not shared state artificially
stabilizing the result.
"""
from __future__ import annotations

import dataclasses
from collections import Counter
from typing import Callable

from agents.base import CodingAgent
from evaluator.pipeline import EvaluationResult, run_evaluation
from sandbox.runner import Sandbox


@dataclasses.dataclass
class ReplaySummary:
    n: int
    verdicts: list[str]
    verdict_counts: dict[str, int]
    modal_verdict: str
    consistent_count: int  # how many runs matched the modal verdict
    consistency_rate: float  # consistent_count / n


def run_replay(
    n: int,
    repo_url: str,
    issue_title: str,
    issue_body: str,
    agent_factory: Callable[[Sandbox], CodingAgent],
    commit_sha: str | None = None,
    run_skeptic: bool = True,
    evaluation_id_prefix: str = "replay",
) -> tuple[list[EvaluationResult], ReplaySummary]:
    results: list[EvaluationResult] = []
    for i in range(n):
        result = run_evaluation(
            evaluation_id=f"{evaluation_id_prefix}-{i + 1}",
            repo_url=repo_url,
            issue_title=issue_title,
            issue_body=issue_body,
            agent_factory=agent_factory,
            commit_sha=commit_sha,
            run_skeptic=run_skeptic,
        )
        results.append(result)

    verdicts = [r.verdict for r in results]
    counts = dict(Counter(verdicts))
    modal_verdict = Counter(verdicts).most_common(1)[0][0]
    consistent_count = counts[modal_verdict]

    summary = ReplaySummary(
        n=n,
        verdicts=verdicts,
        verdict_counts=counts,
        modal_verdict=modal_verdict,
        consistent_count=consistent_count,
        consistency_rate=round(consistent_count / n, 3) if n else 0.0,
    )
    return results, summary
