"""
Smoke test for the live Claude agent adapter against the cheap, known-good
Python fixture (not the real user-supplied repo — that's a separate, more
expensive/uncertain run). Requires ANTHROPIC_API_KEY and Docker; skips
gracefully if either is missing so this doesn't block CI/other contributors.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from dotenv import load_dotenv

from agents.claude_agent import ClaudeCodingAgent
from evaluator.pipeline import run_evaluation
from sandbox.runner import build_image

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "benchmark" / "issues" / "sample-001-average-int-division" / "repo"


@pytest.fixture(scope="session")
def sandbox_image():
    if not shutil.which("docker"):
        pytest.skip("docker not available")
    result = build_image()
    if result.exit_code != 0:
        pytest.skip(f"could not build sandbox image: {result.stderr[-500:]}")
    return True


@pytest.fixture
def local_git_repo_url(tmp_path):
    repo_dir = tmp_path / "fixture_repo"
    shutil.copytree(FIXTURE_DIR, repo_dir)
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "codeproof@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "CodeProof Fixture"], cwd=repo_dir, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo_dir, check=True)
    return str(repo_dir)


def test_claude_agent_end_to_end(sandbox_image, local_git_repo_url):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")

    def agent_factory(sandbox):
        return ClaudeCodingAgent(sandbox)

    result = run_evaluation(
        evaluation_id="claude-smoke-001",
        repo_url=local_git_repo_url,
        issue_title="average() returns wrong result for lists with a non-integer mean",
        issue_body=(
            "average([1, 2]) returns 1 but should return 1.5. Looks like integer "
            "division is being used instead of float division in calc.py."
        ),
        agent_factory=agent_factory,
    )

    print("\n=== VERDICT:", result.verdict, "===")
    print("REASON:", result.reason)
    if result.reproduction:
        print("REPRODUCED:", result.reproduction.get("reproduced"))
    if result.patch:
        print("DIFF:\n", result.patch.get("diff"))
    if result.test_results:
        print("TESTS:", result.test_results.get("passed"), "/", result.test_results.get("total"))

    assert result.verdict in ("PASS", "FAIL", "ABSTAIN")
    assert len(result.trajectory) > 0
