"""Scripted Playbooks for the mock agent, one per benchmark case in manifest.json.
This is the "known fix" data used to prove the pipeline works end-to-end
without an LLM in the loop. Every command here runs for real in the sandbox
— nothing about "mock" means results are faked, only that the choice of
patch is scripted rather than reasoned about live."""
from agents.mock import Playbook

PLAYBOOKS: dict[str, Playbook] = {
    "sample-001-average-int-division": Playbook(
        inspect_summary=(
            "Repository is a small Python module (calc.py) with a pytest suite (test_calc.py). "
            "average() uses `total // len(numbers)`, which performs integer (floor) division."
        ),
        reproduce_command="pip install -q -r requirements.txt && python reproduce.py",
        expected_failure_substring="BUG REPRODUCED",
        patch_diff=(
            "--- a/calc.py\n"
            "+++ b/calc.py\n"
            "@@ -4,5 +4,3 @@ def average(numbers):\n"
            "         raise ValueError(\"average() requires a non-empty list\")\n"
            "     total = sum(numbers)\n"
            "-    # BUG: integer division truncates the result instead of computing\n"
            "-    # a true float average (e.g. average([1, 2]) returns 1 instead of 1.5).\n"
            "-    return total // len(numbers)\n"
            "+    return total / len(numbers)\n"
        ),
        files_changed=["calc.py"],
        patch_explanation="Replace integer division (//) with float division (/) so average() returns the true mean.",
        test_command="pip install -q -r requirements.txt && python -m pytest -q",
    ),
    "sample-002-clamp-upper-bound": Playbook(
        inspect_summary=(
            "Repository is a small Python module (mathutils.py) with a pytest suite "
            "(test_mathutils.py). clamp() returns `low` instead of `high` when value exceeds high."
        ),
        reproduce_command="pip install -q -r requirements.txt && python -m pytest -q -k test_clamp_above_high",
        expected_failure_substring="failed",
        patch_diff=(
            "--- a/mathutils.py\n"
            "+++ b/mathutils.py\n"
            "@@ -3,5 +3,5 @@ def clamp(value, low, high):\n"
            "     if value < low:\n"
            "         return low\n"
            "     if value > high:\n"
            "-        return low\n"
            "+        return high\n"
            "     return value\n"
        ),
        files_changed=["mathutils.py"],
        patch_explanation="Fix clamp() to return `high` (not `low`) when value exceeds the upper bound.",
        test_command="pip install -q -r requirements.txt && python -m pytest -q",
        adversarial_scenarios=[
            ("value below low is unaffected", "python -c \"from mathutils import clamp; assert clamp(-20, -10, -1) == -10\""),
            ("degenerate range where low == high", "python -c \"from mathutils import clamp; assert clamp(5, 3, 3) == 3\""),
        ],
    ),
    "sample-003-baseline-gap": Playbook(
        inspect_summary=(
            "Repository is a small Python module (listmath.py) with a pytest suite "
            "(test_listmath.py). product() accumulates with `total = 0` and `+`, so it "
            "computes a sum instead of a product."
        ),
        reproduce_command="pip install -q -r requirements.txt && python -m pytest -q -k test_product_of_three",
        expected_failure_substring="failed",
        patch_diff=(
            "--- a/listmath.py\n"
            "+++ b/listmath.py\n"
            "@@ -1,6 +1,6 @@\n"
            " def product(numbers):\n"
            "     \"\"\"Return the product of a list of numbers.\"\"\"\n"
            "-    total = 0\n"
            "+    total = 1\n"
            "     for n in numbers:\n"
            "-        total = total + n  # BUG: should accumulate a product, not a sum\n"
            "+        total = total * n\n"
            "     return total\n"
        ),
        files_changed=["listmath.py"],
        patch_explanation="Initialize the accumulator to 1 and multiply instead of add, so product() actually computes a product.",
        test_command="pip install -q -r requirements.txt && python -m pytest -q",
    ),
}
