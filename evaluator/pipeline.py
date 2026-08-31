"""
Core CodeProof evaluation pipeline:

GitHub Issue -> Sandbox -> Dependencies -> Agent -> Reproduction -> Patch
             -> Tests -> Skeptic (adversarial) -> Evidence -> Verdict -> Autopsy

Every step writes to an EvidenceTimeline so the final verdict is always
traceable to real command output, never to an agent's unverified self-report.
"""
from __future__ import annotations

import dataclasses
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Literal

from agents.base import CodingAgent
from evaluator.dependencies import format_evidence, install_dependencies
from evaluator.evidence import EvidenceTimeline
from evaluator.failure_autopsy import FailureAutopsy, classify_failure
from evaluator.skeptic import SkepticResult, run_skeptic_review
from sandbox.runner import Sandbox, clone_repo

Verdict = Literal["PASS", "FAIL", "ABSTAIN"]


@dataclasses.dataclass
class EvaluationResult:
    evaluation_id: str
    verdict: Verdict
    reason: str
    reproduction: dict | None
    patch: dict | None
    test_results: dict | None
    evidence: list[dict]
    trajectory: list[dict]
    skeptic: dict | None = None
    failure_autopsy: dict | None = None


def run_evaluation(
    evaluation_id: str,
    repo_url: str,
    issue_title: str,
    issue_body: str,
    agent_factory: Callable[[Sandbox], CodingAgent],
    commit_sha: str | None = None,
    keep_workdir: bool = False,
    run_skeptic: bool = True,
) -> EvaluationResult:
    timeline = EvidenceTimeline()
    workdir = Path(tempfile.mkdtemp(prefix=f"codeproof-{evaluation_id}-"))
    repo_path = workdir / "repo"

    try:
        # 1. Clone the target repo at the exact commit under evaluation.
        clone_result = clone_repo(repo_url, repo_path, commit_sha)
        timeline.record(
            claim=f"Repository cloned at {commit_sha or 'HEAD'}",
            evidence=f"$ {clone_result.command}\nexit={clone_result.exit_code}\n{clone_result.stderr}",
            passed=clone_result.exit_code == 0,
        )
        if clone_result.exit_code != 0:
            return _abstain(evaluation_id, timeline, [], "Could not clone repository; no evidence collected.")

        with Sandbox(repo_path, evaluation_id) as sandbox:
            # 2. Dependency installation — deterministic, run once, before
            # the agent gets control. This is what previously kept failing
            # when left to the agent: forgetting to install, picking the
            # wrong command, or retrying on top of a corrupted partial
            # install after a timeout. A failed install isn't fatal here —
            # it's recorded as evidence and the agent still gets a chance
            # (e.g. the bug might not need the missing dependency at all).
            dep_result = install_dependencies(sandbox)
            if dep_result.attempted:
                timeline.record(
                    claim=f"Dependencies installed ({', '.join(dep_result.detected)})",
                    evidence=format_evidence(dep_result),
                    passed=dep_result.success,
                )

            agent = agent_factory(sandbox)

            # 3-4. Repository inspection and bug reproduction. Same
            # rationale as the patch-stage try/except below: a live agent
            # (especially a weaker local model) can crash unpredictably here
            # — a malformed tool call, missing arguments, etc. — and that is
            # a real, expected agent failure, not a CodeProof bug. ABSTAIN
            # with the failure as evidence rather than an unhandled crash.
            try:
                # Agent initializes + inspects the repository.
                agent.initialize(issue_title, issue_body, repo_path)
                summary = agent.inspect_repository()
                timeline.record(claim="Repository inspected", evidence=summary, passed=True)

                # Bug reproduction — the load-bearing gate. If we can't
                # reproduce the bug, CodeProof must ABSTAIN rather than
                # pretend a fix was verified.
                repro = agent.reproduce_issue()
                timeline.record(
                    claim="Bug reproduced" if repro.reproduced else "Bug reproduction FAILED",
                    evidence=f"$ {repro.command}\nexpected substring: {repro.expected!r}\nobserved:\n{repro.observed}",
                    passed=repro.reproduced,
                )
            except Exception as exc:  # noqa: BLE001 - agent failure is expected, not a CodeProof bug
                timeline.record(claim="Agent failed during inspection/reproduction", evidence=str(exc), passed=False)
                return _abstain(
                    evaluation_id, timeline, agent.trajectory,
                    f"Agent failed while inspecting the repository or reproducing the issue: {exc}",
                )

            if not repro.reproduced:
                return _abstain(
                    evaluation_id, timeline, agent.trajectory,
                    "Could not reproduce the reported bug at this commit; insufficient evidence to evaluate a fix.",
                    reproduction=dataclasses.asdict(repro),
                )

            # 5-7. Patch generation, application, and verification. A live
            # agent can fail unpredictably here (claim a fix it never wrote,
            # error mid-tool-call, etc.) — that is a real, expected outcome,
            # not a bug in CodeProof. Catch it and ABSTAIN with the failure
            # as evidence rather than letting an unhandled exception look
            # like a crash.
            try:
                # Patch generation (kept isolated — only applied to this
                # sandboxed working copy, never the user's original repo).
                patch = agent.propose_fix()
                timeline.record(
                    claim=f"Patch proposed ({len(patch.files_changed)} file(s), +{patch.lines_added}/-{patch.lines_removed})",
                    evidence=patch.diff,
                    passed=None,
                )

                agent.apply_patch(patch)
                timeline.record(claim="Patch applied to isolated sandbox working copy", evidence=patch.diff[:500], passed=True)

                # Re-run the reproduction — must now show the bug is gone.
                post_patch_repro = agent.reproduce_issue()
                fixed = not post_patch_repro.reproduced
                timeline.record(
                    claim="Reproduction re-run after patch",
                    evidence=f"observed:\n{post_patch_repro.observed}",
                    passed=fixed,
                )

                # Existing test suite.
                test_results = agent.run_tests()
                tests_passed = test_results.failed == 0
                timeline.record(
                    claim=f"Existing tests: {test_results.passed}/{test_results.total} passed",
                    evidence=test_results.raw_output[-3000:],
                    passed=tests_passed,
                )
            except Exception as exc:  # noqa: BLE001 - agent failure is expected, not a CodeProof bug
                timeline.record(claim="Agent failed during patch generation/verification", evidence=str(exc), passed=False)
                return _abstain(
                    evaluation_id, timeline, agent.trajectory,
                    f"Agent failed while generating or verifying a patch: {exc}",
                    reproduction=dataclasses.asdict(repro),
                )

            # 8. Skeptic Agent — independent adversarial testing. Only
            # worth running against a patch that otherwise looks like a
            # PASS; no point attacking a fix that already failed its own
            # reproduction or the existing test suite.
            skeptic_result: SkepticResult | None = None
            if fixed and tests_passed and run_skeptic:
                skeptic_agent = agent_factory(sandbox)
                skeptic_agent.initialize(issue_title, issue_body, repo_path)
                skeptic_result = run_skeptic_review(
                    skeptic_agent, issue_title, issue_body, patch.diff, patch.explanation,
                )
                timeline.record(
                    claim="Skeptic adversarial testing",
                    evidence=skeptic_result.summary + "\n\n" + "\n".join(
                        f"- {s.name}: {'PASS' if s.passed else 'FAIL'} — {s.notes}" for s in skeptic_result.scenarios
                    ),
                    passed=(skeptic_result.failed == 0) if skeptic_result.ran else None,
                )

            skeptic_failed = bool(skeptic_result and skeptic_result.ran and skeptic_result.failed > 0)

            if fixed and tests_passed and not skeptic_failed:
                verdict: Verdict = "PASS"
                reason = "Bug reproduced, patch resolves reproduction, existing tests pass."
                if skeptic_result and skeptic_result.ran:
                    reason += f" Skeptic ran {skeptic_result.generated} adversarial scenario(s), all passed."
            else:
                verdict = "FAIL"
                reasons = []
                if not fixed:
                    reasons.append("reproduction still fails after patch")
                if not tests_passed:
                    reasons.append(f"{test_results.failed} existing test(s) failed")
                if skeptic_failed:
                    reasons.append(f"{skeptic_result.failed} adversarial scenario(s) failed — patch not fully verified")
                reason = "; ".join(reasons)

            timeline.record(claim=f"Verdict: {verdict}", evidence=reason, passed=(verdict == "PASS"))

            autopsy = classify_failure(verdict, reason, timeline.to_list(), skeptic_failed=skeptic_failed)

            return EvaluationResult(
                evaluation_id=evaluation_id,
                verdict=verdict,
                reason=reason,
                reproduction=dataclasses.asdict(repro),
                patch=dataclasses.asdict(patch),
                test_results=dataclasses.asdict(test_results),
                evidence=timeline.to_list(),
                trajectory=[dataclasses.asdict(s) for s in agent.trajectory],
                skeptic=dataclasses.asdict(skeptic_result) if skeptic_result else None,
                failure_autopsy=dataclasses.asdict(autopsy) if autopsy else None,
            )
    finally:
        if not keep_workdir:
            shutil.rmtree(workdir, ignore_errors=True)


def _abstain(
    evaluation_id: str, timeline: EvidenceTimeline, trajectory: list, reason: str, reproduction: dict | None = None,
) -> EvaluationResult:
    timeline.record(claim="Verdict: ABSTAIN", evidence=reason, passed=None)
    autopsy = classify_failure("ABSTAIN", reason, timeline.to_list())
    return EvaluationResult(
        evaluation_id=evaluation_id,
        verdict="ABSTAIN",
        reason=reason,
        reproduction=reproduction,
        patch=None,
        test_results=None,
        evidence=timeline.to_list(),
        trajectory=[dataclasses.asdict(s) for s in trajectory],
        failure_autopsy=dataclasses.asdict(autopsy) if autopsy else None,
    )
