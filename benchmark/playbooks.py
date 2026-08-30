"""Scripted Playbooks for the mock agent, one per benchmark case in manifest.json.
This is the "known fix" data used to prove the pipeline works end-to-end
without an LLM in the loop."""
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
}
