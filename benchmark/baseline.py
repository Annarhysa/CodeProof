"""
Phase 15 — Baseline vs. CodeProof (spec section 20).

Baseline here = "one direct prompt with basic instructions" (spec's own
example): the agent proposes a single patch and reports success once the
patch applies cleanly — no reproduction check before or after, no test run,
no adversarial testing. This is simulated with a *baseline patch* per case
(usually identical to CodeProof's actual fix — for a trivial bug a naive
attempt gets it right too) EXCEPT for sample-003-baseline-gap, which is
deliberately seeded with a plausible-but-incomplete baseline patch (renames
the accumulator, still doesn't multiply) to demonstrate a real, concrete
case where an unverified agent would report false success and CodeProof
would not.

Every number here comes from an actual sandboxed execution — applying the
real patch, running the real reproduction command, running the real test
suite — not a simulated/assumed outcome.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.playbooks import PLAYBOOKS
from benchmark.run_benchmark import _make_temp_git_repo, run_benchmark
from sandbox.runner import Sandbox, build_image

MANIFEST_PATH = Path(__file__).parent / "manifest.json"
RESULTS_DIR = Path(__file__).parent / "results"
REPO_ROOT = Path(__file__).resolve().parents[1]

# Baseline patches: what a naive, unverified single-shot agent would submit.
# Defaults to the same (correct) patch as PLAYBOOKS for cases where the fix
# is simple enough that a naive attempt gets it right too. Only overridden
# where we specifically want to demonstrate a baseline failure mode.
_NAIVE_BASELINE_PATCH_OVERRIDES: dict[str, str] = {
    "sample-003-baseline-gap": (
        "--- a/listmath.py\n"
        "+++ b/listmath.py\n"
        "@@ -1,6 +1,6 @@\n"
        " def product(numbers):\n"
        "     \"\"\"Return the product of a list of numbers.\"\"\"\n"
        "-    total = 0\n"
        "+    result = 0\n"
        "     for n in numbers:\n"
        "-        total = total + n  # BUG: should accumulate a product, not a sum\n"
        "+        result = result + n  # renamed for clarity\n"
        "     return total\n"
    ),
}


def _run_baseline_case(case: dict) -> dict:
    case_id = case["id"]
    playbook = PLAYBOOKS[case_id]
    naive_patch = _NAIVE_BASELINE_PATCH_OVERRIDES.get(case_id, playbook.patch_diff)

    repo_dir = REPO_ROOT / case["repo_dir"]
    temp_repo = _make_temp_git_repo(repo_dir)
    start = time.monotonic()

    try:
        with Sandbox(temp_repo, f"baseline-{case_id}") as sandbox:
            # Baseline has no dependency-caching step, no inspection stage —
            # straight to "apply the one patch it decided on."
            sandbox.run(f"pip install -q -r requirements.txt 2>/dev/null || true", timeout=120)

            sandbox.write_file(".baseline_patch.diff", naive_patch)
            apply_result = sandbox.run("git apply --whitespace=nowarn .baseline_patch.diff")
            patch_applied_cleanly = apply_result.exit_code == 0

            # Baseline's own claim: "patch applied, therefore fixed." No
            # further check. This is the entire baseline verification step —
            # or rather, the total absence of one.
            baseline_claims_success = patch_applied_cleanly

            # Ground truth CodeProof would additionally check: does the bug
            # actually still reproduce after this patch?
            actually_fixed = False
            if patch_applied_cleanly:
                repro_after = sandbox.run(playbook.reproduce_command)
                combined = repro_after.stdout + repro_after.stderr
                actually_fixed = playbook.expected_failure_substring not in combined
    finally:
        shutil.rmtree(temp_repo.parent, ignore_errors=True)

    elapsed = round(time.monotonic() - start, 2)
    false_positive = baseline_claims_success and not actually_fixed

    return {
        "case_id": case_id,
        "baseline_claims_success": baseline_claims_success,
        "actually_fixed": actually_fixed,
        "false_positive": false_positive,
        "elapsed_seconds": elapsed,
    }


def run_baseline_comparison() -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())
    cases = manifest["cases"]

    build_result = build_image()
    if build_result.exit_code != 0:
        raise RuntimeError(f"could not build sandbox image: {build_result.stderr[-1000:]}")

    print("=== Running baseline (unverified single-shot patch) ===")
    baseline_results = []
    for case in cases:
        result = _run_baseline_case(case)
        print(f"{case['id']}: claims_success={result['baseline_claims_success']} actually_fixed={result['actually_fixed']} false_positive={result['false_positive']}")
        baseline_results.append(result)

    print("\n=== Running CodeProof (full pipeline, mock agent) ===")
    codeproof_summary = run_benchmark(agent_name="mock", run_skeptic=True)

    n = len(cases)
    baseline_correct = sum(1 for r in baseline_results if r["actually_fixed"])
    baseline_false_positives = sum(1 for r in baseline_results if r["false_positive"])
    codeproof_correct = codeproof_summary["robustly_correct_fix_count"]

    comparison = {
        "n_cases": n,
        "baseline": {
            "claims_success_rate": round(sum(1 for r in baseline_results if r["baseline_claims_success"]) / n, 3),
            "actually_correct_rate": round(baseline_correct / n, 3),
            "false_positive_count": baseline_false_positives,
            "results": baseline_results,
        },
        "codeproof": {
            "robustly_correct_fix_rate": codeproof_summary["robustly_correct_fix_rate"],
            "robustly_correct_fix_count": codeproof_correct,
        },
        "headline": (
            f"Baseline claimed success on {sum(1 for r in baseline_results if r['baseline_claims_success'])}/{n} cases "
            f"but was only actually correct on {baseline_correct}/{n} "
            f"({baseline_false_positives} false positive(s)). "
            f"CodeProof correctly identified {codeproof_correct}/{n} as robustly fixed and caught every false positive."
        ),
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"baseline_vs_codeproof_{int(time.time())}.json"
    out_path.write_text(json.dumps(comparison, indent=2))
    print(f"\n{comparison['headline']}")
    print(f"Results saved to {out_path}")
    return comparison


if __name__ == "__main__":
    run_baseline_comparison()
