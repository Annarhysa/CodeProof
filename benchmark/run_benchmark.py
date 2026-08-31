"""
Phase 14 — Benchmark runner (spec section 19).

Runs every case in manifest.json through the real CodeProof pipeline (mock
agent by default — deterministic and free; pass --agent to use a live one)
and reports the Robustly Correct Fix Rate and per-case results. Every
number printed here comes from an actual pipeline execution in this run —
nothing is precomputed or hardcoded.

Usage:
    python -m benchmark.run_benchmark
    python -m benchmark.run_benchmark --agent claude
    python -m benchmark.run_benchmark --no-skeptic
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.claude_agent import ClaudeCodingAgent
from agents.gemini_agent import GeminiCodingAgent
from agents.mock import MockCodingAgent
from agents.ollama_agent import OllamaCodingAgent
from benchmark.playbooks import PLAYBOOKS
from evaluator.pipeline import run_evaluation
from sandbox.runner import build_image

MANIFEST_PATH = Path(__file__).parent / "manifest.json"
RESULTS_DIR = Path(__file__).parent / "results"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_temp_git_repo(source_dir: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="codeproof-benchmark-"))
    dest = tmp / "repo"
    shutil.copytree(source_dir, dest)
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
    subprocess.run(["git", "config", "user.email", "codeproof@example.com"], cwd=dest, check=True)
    subprocess.run(["git", "config", "user.name", "CodeProof Benchmark"], cwd=dest, check=True)
    subprocess.run(["git", "add", "-A"], cwd=dest, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=dest, check=True)
    return dest


def _agent_factory(agent_name: str, case_id: str):
    if agent_name == "claude":
        return lambda sandbox: ClaudeCodingAgent(sandbox)
    if agent_name == "gemini":
        return lambda sandbox: GeminiCodingAgent(sandbox)
    if agent_name == "ollama":
        return lambda sandbox: OllamaCodingAgent(sandbox)
    playbook = PLAYBOOKS[case_id]
    return lambda sandbox: MockCodingAgent(sandbox, playbook)


def run_benchmark(agent_name: str = "mock", run_skeptic: bool = True) -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())
    cases = manifest["cases"]

    build_result = build_image()
    if build_result.exit_code != 0:
        raise RuntimeError(f"could not build sandbox image: {build_result.stderr[-1000:]}")

    results = []
    for case in cases:
        case_id = case["id"]
        repo_dir = REPO_ROOT / case["repo_dir"]
        print(f"\n=== {case_id} ({agent_name}) ===")

        temp_repo = _make_temp_git_repo(repo_dir)
        start = time.monotonic()
        result = run_evaluation(
            evaluation_id=f"benchmark-{case_id}",
            repo_url=str(temp_repo),
            issue_title=case["issue_title"],
            issue_body=case["issue_body"],
            agent_factory=_agent_factory(agent_name, case_id),
            run_skeptic=run_skeptic,
        )
        elapsed = round(time.monotonic() - start, 2)
        shutil.rmtree(temp_repo.parent, ignore_errors=True)

        robustly_correct = (
            result.verdict == "PASS"
            and result.reproduction is not None and result.reproduction.get("reproduced") is True
            and result.test_results is not None and result.test_results.get("failed") == 0
            and (result.skeptic is None or not result.skeptic.get("ran") or result.skeptic.get("failed", 0) == 0)
        )

        print(f"verdict={result.verdict} expected={case['expected_verdict']} elapsed={elapsed}s robustly_correct={robustly_correct}")
        results.append({
            "case_id": case_id,
            "difficulty": case.get("difficulty"),
            "bug_type": case.get("bug_type"),
            "expected_verdict": case["expected_verdict"],
            "actual_verdict": result.verdict,
            "matched_expected": result.verdict == case["expected_verdict"],
            "robustly_correct_fix": robustly_correct,
            "elapsed_seconds": elapsed,
            "reason": result.reason,
        })

    n = len(results)
    robustly_correct_count = sum(1 for r in results if r["robustly_correct_fix"])
    summary = {
        "agent": agent_name,
        "run_skeptic": run_skeptic,
        "n_cases": n,
        "robustly_correct_fix_count": robustly_correct_count,
        "robustly_correct_fix_rate": round(robustly_correct_count / n, 3) if n else 0.0,
        "results": results,
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"benchmark_{agent_name}_{int(time.time())}.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\nRobustly Correct Fix Rate ({agent_name}): {robustly_correct_count}/{n} = {summary['robustly_correct_fix_rate']:.0%}")
    print(f"Results saved to {out_path}")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", default="mock", choices=["mock", "claude", "gemini", "ollama"])
    parser.add_argument("--no-skeptic", action="store_true")
    args = parser.parse_args()
    run_benchmark(agent_name=args.agent, run_skeptic=not args.no_skeptic)
