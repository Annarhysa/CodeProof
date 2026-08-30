"""
End-to-end test of the vertical slice:
GitHub issue (mocked) -> sandbox -> mock agent -> reproduction -> patch -> tests -> evidence -> verdict.

Requires Docker. Skips automatically if the daemon or image build is unavailable
so this doesn't block environments without Docker (e.g. some CI runners).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from agents.mock import MockCodingAgent
from benchmark.playbooks import PLAYBOOKS
from evaluator.pipeline import run_evaluation
from sandbox.runner import build_image

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "benchmark" / "issues" / "sample-001-average-int-division" / "repo"


def _docker_available() -> bool:
    return shutil.which("docker") is not None


@pytest.fixture(scope="session")
def sandbox_image():
    if not _docker_available():
        pytest.skip("docker not available")
    result = build_image()
    if result.exit_code != 0:
        pytest.skip(f"could not build sandbox image: {result.stderr[-500:]}")
    return True


@pytest.fixture
def local_git_repo_url(tmp_path):
    """Turn the plain fixture files into a real local git repo to clone from,
    mirroring what a real GitHub repo clone would look like."""
    repo_dir = tmp_path / "fixture_repo"
    shutil.copytree(FIXTURE_DIR, repo_dir)
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "codeproof@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "CodeProof Fixture"], cwd=repo_dir, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo_dir, check=True)
    return str(repo_dir)


def test_full_pipeline_pass_verdict(sandbox_image, local_git_repo_url):
    playbook = PLAYBOOKS["sample-001-average-int-division"]

    def agent_factory(sandbox):
        return MockCodingAgent(sandbox, playbook)

    result = run_evaluation(
        evaluation_id="test-001",
        repo_url=local_git_repo_url,
        issue_title="average() returns wrong result for lists with a non-integer mean",
        issue_body="average([1, 2]) returns 1 but should return 1.5.",
        agent_factory=agent_factory,
    )

    assert result.verdict == "PASS", result.reason
    assert result.reproduction["reproduced"] is True
    assert result.test_results["failed"] == 0
    assert any(e["claim"].startswith("Bug reproduced") for e in result.evidence)
    assert len(result.trajectory) > 0
