"""
Smoke test for the local Ollama agent adapter against the cheap, known-good
Python fixture. Requires Ollama running locally with a tool-calling model
pulled; skips gracefully if Ollama isn't reachable.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import requests

from agents.ollama_agent import DEFAULT_MODEL, OLLAMA_HOST, OllamaCodingAgent
from evaluator.pipeline import run_evaluation
from sandbox.runner import build_image

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "benchmark" / "issues" / "sample-001-average-int-division" / "repo"


def _ollama_available() -> bool:
    try:
        requests.get(f"{OLLAMA_HOST}/api/version", timeout=3)
        return True
    except requests.exceptions.ConnectionError:
        return False


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


def test_ollama_agent_end_to_end(sandbox_image, local_git_repo_url):
    if not _ollama_available():
        pytest.skip(f"Ollama not reachable at {OLLAMA_HOST} (model would be {DEFAULT_MODEL})")

    def agent_factory(sandbox):
        return OllamaCodingAgent(sandbox)

    result = run_evaluation(
        evaluation_id="ollama-smoke-001",
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

    assert result.verdict in ("PASS", "FAIL", "ABSTAIN")
    assert len(result.trajectory) > 0
