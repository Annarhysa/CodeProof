# Evaluation Methodology

## Primary metric: Robustly Correct Fix Rate

Percentage of benchmark issues where the proposed solution:

1. Reproduces the original issue before the fix
2. Fixes the reproduction
3. Passes existing tests
4. Passes generated regression tests
5. Passes independent adversarial tests (Skeptic Agent — planned, not yet implemented)

Today's pipeline (`evaluator/pipeline.py`) computes steps 1–3 for real, from
actual sandboxed command execution. Steps 4–5 require the Skeptic Agent,
which is on the P1 roadmap and not yet built — so any "Robustly Correct Fix
Rate" reported right now reflects only steps 1–3 and should be labeled as
such until the Skeptic layer lands. **No benchmark numbers are reported in
this repo until they come from an actual run** — see CHANGELOG.md for what
has and hasn't been executed yet.

## Verdicts

- **PASS** — bug reproduced pre-patch, reproduction clears post-patch,
  existing tests pass.
- **FAIL** — reproduction still fails after the patch, and/or existing
  tests fail.
- **ABSTAIN** — CodeProof could not establish enough evidence to judge (e.g.
  the bug itself could not be reproduced at the given commit, or the repo
  could not be cloned). CodeProof never reports PASS/FAIL without evidence.

## Secondary metrics (planned, computed once Skeptic/Replay land)

- Reproducibility rate (Replay: same evaluation run N times, % consistent)
- Regression failure rate
- Adversarial failure rate
- False acceptance rate
- Correct abstention rate
- Unnecessary code changes (diff size vs. minimal fix)
- Human review time
- Approximate cost per evaluation

## Human review

The pipeline's verdict is a recommendation backed by evidence, not a final
decision. A human reviewer sees the reproduction, the diff, test results,
the full evidence timeline, and the agent's trajectory, and records one of:
APPROVE / REQUEST REVISION / REJECT / ABSTAIN. This decision is stored
alongside the automated verdict — the two are not required to match, and a
mismatch is itself useful signal about the automated pipeline's reliability.
