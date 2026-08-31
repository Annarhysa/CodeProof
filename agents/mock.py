"""
Mock/local CodingAgent adapter for development and CI without an LLM API key.

Important: "mock" only means there is no LLM call generating the patch. All
command execution (reproduction, patch application, test runs) still happens
for real inside the Docker sandbox, per the "real execution over mocked
success" principle. The patch content itself is supplied by a benchmark
"playbook" (see benchmark/manifest.json) describing a known bug + known fix,
so the mock agent behaves like a scripted, honest participant rather than a
stub that always claims success.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

from agents.base import CodingAgent, Patch, ReproductionResult, TestRunResult
from sandbox.runner import Sandbox


@dataclasses.dataclass
class Playbook:
    """Scripted behavior for a single benchmark case, used by MockCodingAgent."""
    inspect_summary: str
    reproduce_command: str
    expected_failure_substring: str
    patch_diff: str
    files_changed: list[str]
    patch_explanation: str
    test_command: str
    # Optional: (name, command) pairs the mock skeptic runs for real via the
    # sandbox — a scripted stand-in for what a live skeptic agent would come
    # up with itself. Empty by default (most benchmark cases don't need one).
    adversarial_scenarios: list[tuple[str, str]] = dataclasses.field(default_factory=list)


class MockCodingAgent(CodingAgent):
    def __init__(self, sandbox: Sandbox, playbook: Playbook):
        super().__init__(name="mock-agent")
        self.sandbox = sandbox
        self.playbook = playbook

    def initialize(self, issue_title: str, issue_body: str, repo_path: Path) -> None:
        self._log("system", "You are a coding agent. Reproduce the issue, then propose a minimal fix.")
        self._log("instruction", f"Issue: {issue_title}\n\n{issue_body}")

    def inspect_repository(self) -> str:
        result = self.sandbox.run("find . -maxdepth 2 -type f -not -path './.git/*'")
        self._log("tool_call", "list_repository_files")
        self._log("tool_result", result.stdout, exit_code=result.exit_code)
        self._log("response", self.playbook.inspect_summary)
        return self.playbook.inspect_summary

    def reproduce_issue(self) -> ReproductionResult:
        self._log("tool_call", f"run: {self.playbook.reproduce_command}")
        result = self.sandbox.run(self.playbook.reproduce_command)
        self._log("tool_result", result.stdout + result.stderr, exit_code=result.exit_code)

        combined_output = result.stdout + result.stderr
        reproduced = self.playbook.expected_failure_substring in combined_output
        repro = ReproductionResult(
            reproduced=reproduced,
            command=self.playbook.reproduce_command,
            expected=self.playbook.expected_failure_substring,
            observed=combined_output.strip()[:2000],
            explanation=(
                "Reproduction command output contained the expected failure signature."
                if reproduced else
                "Reproduction command did not produce the expected failure signature; "
                "cannot confirm the bug is present at this commit."
            ),
        )
        self._log("note", repro.explanation, reproduced=reproduced)
        return repro

    def propose_fix(self) -> Patch:
        diff = self.playbook.patch_diff
        added = sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))
        patch = Patch(
            diff=diff,
            files_changed=self.playbook.files_changed,
            lines_added=added,
            lines_removed=removed,
            explanation=self.playbook.patch_explanation,
        )
        self._log("response", f"Proposed patch touching {len(patch.files_changed)} file(s): {patch.explanation}")
        return patch

    def apply_patch(self, patch: Patch) -> None:
        patch_filename = ".codeproof_patch.diff"
        # Sandbox.write_file writes with newline="" — matters here: a plain
        # write_text on Windows silently turns \n into \r\n, which can make
        # a byte-perfect patch fail to apply against a Linux checkout.
        self.sandbox.write_file(patch_filename, patch.diff)
        self._log("command", f"git apply {patch_filename}")
        result = self.sandbox.run(f"git apply --whitespace=nowarn {patch_filename}")
        self._log("tool_result", result.stdout + result.stderr, exit_code=result.exit_code)
        if result.exit_code != 0:
            raise RuntimeError(f"failed to apply patch: {result.stderr}")

    def run_tests(self) -> TestRunResult:
        self._log("command", self.playbook.test_command)
        result = self.sandbox.run(self.playbook.test_command)
        self._log("tool_result", result.stdout + result.stderr, exit_code=result.exit_code)
        passed, failed, total = _parse_pytest_summary(result.stdout + result.stderr)
        return TestRunResult(passed=passed, failed=failed, total=total, raw_output=result.stdout + result.stderr)

    def run_custom_stage(self, prompt: str, allow_write: bool = True) -> str:
        # The mock agent can't reason about an arbitrary prompt — it runs
        # whatever adversarial scenarios the benchmark case scripted (still
        # real command execution, real pass/fail), a scripted stand-in for
        # what a live skeptic agent would come up with on its own.
        scenarios = []
        for name, command in self.playbook.adversarial_scenarios:
            self._log("tool_call", f"skeptic scenario: {name} -> {command}")
            result = self.sandbox.run(command)
            self._log("tool_result", result.stdout + result.stderr, exit_code=result.exit_code)
            scenarios.append({"name": name, "passed": result.exit_code == 0, "notes": (result.stdout + result.stderr)[:500]})
        return json.dumps({"scenarios": scenarios})


def _parse_pytest_summary(output: str) -> tuple[int, int, int]:
    """Best-effort parse of `N passed` / `N failed` from pytest's summary line."""
    import re
    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", output)) else 0
    failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", output)) else 0
    return passed, failed, passed + failed
