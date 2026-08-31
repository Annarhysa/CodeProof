# listmath

## Known issue

`product(numbers)` should return the product of the list but instead
returns the sum — it initializes `total = 0` and uses `+` instead of
initializing `total = 1` and using `*`. Run `pytest` to see the failing
tests.

This fixture exists specifically to demonstrate the gap between a naive
"trust the patch" baseline and CodeProof: the benchmark's baseline
Playbook applies a plausible-looking but *incomplete* first fix (renames
the accumulator variable, still uses `+`) that a baseline agent might
submit and consider done. CodeProof's mandatory re-reproduction step
catches that the bug is still present and returns FAIL instead of a false
PASS.
