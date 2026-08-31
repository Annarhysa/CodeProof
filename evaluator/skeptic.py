"""
Phase 8 — Skeptic Agent (spec section 13).

Independent from the agent that wrote the patch: it gets a fresh
conversation (a new CodingAgent instance from the same agent_factory the
pipeline used, sharing the same sandbox/repo state) and one instruction —
assume the patch is wrong, find a counterexample. It writes and runs real
adversarial scripts in the sandbox; nothing here is scored on the model's
say-so, only on real command exit codes, same as every other claim in
CodeProof.
"""
from __future__ import annotations

import dataclasses
import json

from agents.base import CodingAgent

MAX_SCENARIOS_HINT = 6


@dataclasses.dataclass
class AdversarialScenario:
    name: str
    passed: bool
    notes: str


@dataclasses.dataclass
class SkepticResult:
    ran: bool
    scenarios: list[AdversarialScenario]
    generated: int
    passed: int
    failed: int
    summary: str


def run_skeptic_review(
    skeptic_agent: CodingAgent,
    issue_title: str,
    issue_body: str,
    patch_diff: str,
    patch_explanation: str,
) -> SkepticResult:
    prompt = (
        "You are an independent skeptic reviewing a patch someone else wrote for the "
        "issue below. Your only job: assume the patch is wrong and try to prove it. "
        "Generate a small number (up to "
        f"{MAX_SCENARIOS_HINT}) of adversarial test scenarios *specifically relevant to "
        "this issue and this patch* — think boundary values, empty/null inputs, "
        "concurrent or duplicate requests, retries, timeouts, invalid inputs, unexpected "
        "ordering, error handling — whichever of these actually apply here. Do not "
        "generate generic or unrelated tests. For each scenario, write a small script "
        "with write_file and run it with run_command against the CURRENT (already "
        "patched) code — you don't need to inspect the repo again, the patch below "
        "already tells you what changed. When done, reply with ONLY a JSON object, no "
        "prose, of exactly this form:\n"
        '{"scenarios": [{"name": "<short name>", "passed": true|false, '
        '"notes": "<one sentence: what you tested and what happened>"}]}\n'
        "Only set passed=true if you actually ran the scenario and it behaved "
        "correctly — never guess.\n\n"
        f"Issue: {issue_title}\n{issue_body}\n\n"
        f"Patch explanation: {patch_explanation}\n\n"
        f"Patch diff:\n{patch_diff}"
    )

    try:
        text = skeptic_agent.run_custom_stage(prompt, allow_write=True)
    except Exception as exc:  # noqa: BLE001 - skeptic failure shouldn't crash the pipeline
        return SkepticResult(
            ran=False, scenarios=[], generated=0, passed=0, failed=0,
            summary=f"Skeptic agent failed to run: {exc}",
        )

    data = _parse_json_object(text)
    if data is None or "scenarios" not in data:
        return SkepticResult(
            ran=False, scenarios=[], generated=0, passed=0, failed=0,
            summary="Skeptic agent did not return parseable adversarial-test results; skipping adversarial check.",
        )

    scenarios = [
        AdversarialScenario(
            name=str(s.get("name", "unnamed")),
            passed=bool(s.get("passed", False)),
            notes=str(s.get("notes", "")),
        )
        for s in data["scenarios"]
        if isinstance(s, dict)
    ]
    passed = sum(1 for s in scenarios if s.passed)
    failed = len(scenarios) - passed

    if not scenarios:
        summary = "Skeptic generated no adversarial scenarios (none judged relevant to this issue)."
    elif failed == 0:
        summary = f"Skeptic generated {len(scenarios)} adversarial scenario(s); all passed."
    else:
        summary = f"Skeptic generated {len(scenarios)} adversarial scenario(s); {failed} failed — patch not fully verified."

    return SkepticResult(ran=True, scenarios=scenarios, generated=len(scenarios), passed=passed, failed=failed, summary=summary)


def _parse_json_object(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None
