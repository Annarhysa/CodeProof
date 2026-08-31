"""
Phase 10 — Failure Autopsy (spec section 15).

Rule-based, not LLM-based: every category here is derived from the same
evidence timeline / reason text CodeProof already produced, matched against
patterns actually observed running this pipeline against real repos this
session. Deterministic and free — no reason to spend an LLM call
classifying a failure CodeProof already has the evidence to explain itself.
"""
from __future__ import annotations

import dataclasses

CATEGORIES = [
    "Missing context",
    "Wrong hypothesis",
    "Failed reproduction",
    "Incorrect patch",
    "Weak test coverage",
    "Edge case",
    "Regression",
    "Tool failure",
    "Environment failure",
]


@dataclasses.dataclass
class FailureAutopsy:
    applicable: bool
    category: str
    earliest_detectable_point: str
    likely_cause: str
    recommended_action: str


def classify_failure(
    verdict: str,
    reason: str,
    evidence: list[dict],
    skeptic_failed: bool = False,
) -> FailureAutopsy | None:
    if verdict == "PASS":
        return None

    reason_l = reason.lower()
    evidence_text = " ".join(str(e.get("evidence", "")) for e in evidence).lower()
    claims = [str(e.get("claim", "")).lower() for e in evidence]

    def _autopsy(category: str, point: str, cause: str, action: str) -> FailureAutopsy:
        return FailureAutopsy(applicable=True, category=category, earliest_detectable_point=point, likely_cause=cause, recommended_action=action)

    if any("could not clone" in c for c in claims):
        return _autopsy(
            "Environment failure", "Repository clone",
            "The repository URL could not be reached or cloned (network issue, private repo without credentials, or a malformed URL).",
            "Verify the repo URL is a real clone URL (not an issue page), and that GITHUB_TOKEN is set if it's private.",
        )

    if "dependencies installed" in evidence_text and "one or more installs failed" in evidence_text:
        return _autopsy(
            "Environment failure", "Dependency installation",
            "The repo's package manager install (npm/pip) failed even after a cleanup-and-retry, likely a genuinely broken lockfile, an incompatible dependency, or a slow/unreachable package registry.",
            "Check the install command's raw output in the evidence timeline; consider a longer install timeout or a registry mirror if this is a network-speed issue.",
        )

    if "agent failed while inspecting the repository or reproducing the issue" in reason_l:
        return _autopsy(
            "Tool failure", "Repository inspection / reproduction",
            "The agent crashed mid-tool-call — a malformed tool argument, an unhandled API error, or (for local models) weaker instruction-following producing an invalid tool call.",
            "Check the agent trajectory for the specific exception; if using a local model, consider a larger/more capable one.",
        )

    if "could not reproduce" in reason_l:
        return _autopsy(
            "Failed reproduction", "Bug reproduction",
            "The agent could not make the reported bug actually happen — the issue may be underspecified, already fixed at this commit, environment-dependent, or the agent didn't explore enough of the repo before giving up.",
            "Provide more specific reproduction steps in the issue text, or verify the bug still exists at the commit under test.",
        )

    if "agent produced no file changes" in reason_l or "no file changes during propose_fix" in evidence_text:
        return _autopsy(
            "Incorrect patch", "Patch generation",
            "The agent claimed to have written a fix, but no actual file changes are visible in git diff — either it wrote to a nonexistent/wrong path, or the tool call's content didn't persist.",
            "Inspect the agent's write_file tool calls in the trajectory for the path it actually used.",
        )

    if "reproduction still fails after patch" in reason_l:
        return _autopsy(
            "Wrong hypothesis", "Patch verification",
            "The patch was applied but didn't actually fix the reported behavior — the agent's theory about the root cause was likely incorrect.",
            "Review the agent's stated hypothesis in its trajectory against the actual reproduction output.",
        )

    if "existing test" in reason_l and "failed" in reason_l:
        return _autopsy(
            "Regression", "Existing test suite",
            "The patch fixed the reported bug but broke something else that was already covered by tests.",
            "Review the failing existing tests to see what behavior the patch changed unintentionally.",
        )

    if skeptic_failed:
        return _autopsy(
            "Edge case", "Adversarial testing (Skeptic)",
            "The patch passed the original reproduction and existing tests, but failed at least one adversarial scenario the Skeptic Agent constructed — a case the original fix didn't account for.",
            "Add the failing adversarial scenario as a permanent regression test, and broaden the fix to handle it.",
        )

    if "stage stopped after reaching the" in evidence_text and "turn limit" in evidence_text:
        return _autopsy(
            "Missing context", "Repository inspection",
            "The agent ran out of its tool-call turn budget before reaching a conclusion — likely a large/unfamiliar repo that needed more exploration than the budget allowed.",
            "Raise the agent's per-stage turn budget (CODEPROOF_*_MAX_TURNS) for large repos, at the cost of more API calls.",
        )

    return _autopsy(
        "Weak test coverage", "Unclassified",
        "This failure didn't match a known pattern — read the evidence timeline and agent trajectory directly.",
        "No specific recommendation; treat as a new failure mode worth adding a rule for.",
    )
