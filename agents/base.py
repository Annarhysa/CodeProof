"""
CodingAgent abstraction. CodeProof is agent-agnostic: the pipeline in
evaluator/ only ever talks to this interface, never to a specific provider.

Every method call is expected to append to the agent's trajectory (see
TrajectoryStep) so the full reasoning/tool-call history can be replayed and
shown to a human reviewer later.
"""
from __future__ import annotations

import abc
import dataclasses
import time
from pathlib import Path
from typing import Any, Literal


@dataclasses.dataclass
class TrajectoryStep:
    step_type: Literal[
        "system", "instruction", "response", "tool_call", "tool_result", "command", "note",
    ]
    content: str
    timestamp: float = dataclasses.field(default_factory=time.time)
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class ReproductionResult:
    reproduced: bool
    command: str
    expected: str
    observed: str
    explanation: str


@dataclasses.dataclass
class Patch:
    diff: str
    files_changed: list[str]
    lines_added: int
    lines_removed: int
    explanation: str


class CodingAgent(abc.ABC):
    """Interface every agent adapter (Claude, mock, etc.) must implement."""

    def __init__(self, name: str):
        self.name = name
        self.trajectory: list[TrajectoryStep] = []

    def _log(self, step_type: str, content: str, **metadata: Any) -> None:
        self.trajectory.append(TrajectoryStep(step_type=step_type, content=content, metadata=metadata))

    @abc.abstractmethod
    def initialize(self, issue_title: str, issue_body: str, repo_path: Path) -> None:
        """Give the agent the task and a handle to the cloned repo working copy."""

    @abc.abstractmethod
    def inspect_repository(self) -> str:
        """Return a summary of what the agent found relevant in the repo."""

    @abc.abstractmethod
    def reproduce_issue(self) -> ReproductionResult:
        """Attempt to write and run a reproduction of the reported bug."""

    @abc.abstractmethod
    def propose_fix(self) -> Patch:
        """Generate a patch. Must not be applied to the repo yet."""

    @abc.abstractmethod
    def apply_patch(self, patch: Patch) -> None:
        """Apply the patch to the (isolated) working copy."""

    @abc.abstractmethod
    def run_tests(self) -> "TestRunResult":
        """Run the repo's existing test suite after the patch is applied."""

    @abc.abstractmethod
    def run_custom_stage(self, prompt: str, allow_write: bool = True) -> str:
        """Run one open-ended stage with a caller-supplied prompt, using the
        same tool-use loop as the built-in stages, and return the model's
        final text response. Used by evaluator/skeptic.py to drive an
        independent adversarial-testing pass without hardcoding that logic
        into every provider adapter. `allow_write` controls whether the
        write_file tool is offered — the skeptic needs it to author
        adversarial test scripts."""


@dataclasses.dataclass
class TestRunResult:
    passed: int
    failed: int
    total: int
    raw_output: str
