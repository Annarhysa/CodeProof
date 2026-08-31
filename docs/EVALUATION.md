# Evaluation Methodology

## Primary metric: Robustly Correct Fix Rate

Percentage of benchmark issues where the proposed solution:

1. Reproduces the original issue before the fix
2. Fixes the reproduction
3. Passes existing tests
4. Passes generated regression tests
5. Passes independent adversarial tests (Skeptic Agent)

`evaluator/pipeline.py` computes all five for real, from actual sandboxed
command execution — including the Skeptic Agent (`evaluator/skeptic.py`),
which is optional per evaluation (`run_skeptic`) since it costs extra
agent turns.

## Actual results (mock agent, seed benchmark, run via `benchmark/baseline.py`)

The mock agent is scripted (no live LLM), which is exactly why it's the
right tool for validating that the *pipeline* — not any one agent's
reasoning quality — behaves correctly. This is a real run, not a
projection; see `benchmark/results/` for the raw JSON.

| Metric | Value |
|---|---|
| Cases | 3 (seed set — see Limitations) |
| CodeProof Robustly Correct Fix Rate | 3/3 = 100% |
| Baseline (no verification) claims success | 3/3 = 100% |
| Baseline actually correct | 2/3 = 67% |
| Baseline false positives | 1 |

The one baseline false positive (`sample-003-baseline-gap`) is deliberate:
that case's Playbook seeds a baseline patch that looks plausible (renames
a variable) but doesn't actually fix the bug (still adds instead of
multiplying). A baseline that trusts a patch once it applies cleanly — no
re-reproduction check, no test run — reports success. CodeProof's mandatory
re-reproduction step catches it and reports FAIL. This is the concrete,
executed version of the project's core claim, not a hypothetical.

Reproduce this yourself: `python -m benchmark.baseline` (needs Docker; no
API key required for the mock agent).

## Verdicts

- **PASS** — bug reproduced pre-patch, reproduction clears post-patch,
  existing tests pass, and (if enabled) every Skeptic adversarial scenario
  passes.
- **FAIL** — reproduction still fails after the patch, existing tests
  fail, and/or a Skeptic adversarial scenario fails ("not fully verified").
- **ABSTAIN** — CodeProof could not establish enough evidence to judge (the
  repo couldn't be cloned, the bug couldn't be reproduced, or the agent
  crashed mid-stage). CodeProof never reports PASS/FAIL without evidence.

Every non-PASS verdict also gets a **Failure Autopsy**
(`evaluator/failure_autopsy.py`) — a category (one of the spec's nine),
the earliest pipeline stage where the failure was detectable, a likely
cause, and a recommended action, all derived deterministically from the
evidence CodeProof already collected.

## Secondary metrics

- **Reproducibility rate** — `POST /evaluations/{id}/replay` (n=2-10) reruns
  the same inputs with a fresh clone/sandbox/agent each time and reports
  what fraction of runs agreed on the verdict. Genuine run-to-run variance
  (model non-determinism, transient infra) is what this measures — nothing
  is shared between replay runs to artificially stabilize it.
- Regression failure rate, adversarial failure rate, false acceptance
  rate, correct abstention rate — all computable from `benchmark/results/*.json`
  once run against a larger case set; not separately reported yet since
  the seed set (3 cases) is too small for these to be meaningful on their
  own.
- Unnecessary code changes (diff size vs. minimal fix), human review time,
  cost per evaluation — not yet instrumented.

## Human review

The pipeline's verdict is a recommendation backed by evidence, not a final
decision. A human reviewer sees the reproduction, the diff, test results,
Skeptic results, the Failure Autopsy, the full evidence timeline, and the
agent's trajectory, and records one of: APPROVE / REQUEST REVISION /
REJECT / ABSTAIN. This decision is stored alongside the automated verdict
— the two are not required to match, and a mismatch is itself useful
signal about the automated pipeline's reliability.

## Limitations (be honest about what's actually been run)

- **The benchmark is a 3-case seed set**, not the 20-30 real historical
  GitHub issues the spec asks for. Each case is a real, deliberate,
  verified bug with a real test suite — but they were authored for this
  project, not sourced from actual issue trackers. Scaling to a larger,
  historically-sourced set requires either significant live-agent API
  budget (each case is several agent turns × however many live-agent
  cases you want) or many more hours authoring/verifying fixtures.
- **The numbers above are from the mock agent.** Live-agent (Claude/
  Gemini/Ollama) runs against real-world repos this session hit a mix of
  infrastructure issues (now fixed — see CHANGELOG.md, 2026-08-31, on a
  git "dubious ownership" bug that was silently misreporting correct
  patches as "no file changes") and genuine external/model-capability
  constraints: free-tier rate limits, and — once the infra bug was fixed
  and a real verification could actually run — a small local model
  (`llama3.2` via Ollama) that skipped re-verifying its own fix (its
  post-patch reproduction check returned the *identical* JSON as its
  pre-patch check, without calling any tool in between) and separately ran
  the wrong test command (`npm test` on a pure-Python repo). Both were
  caught and correctly reported as FAIL with full evidence, not silently
  passed — a real, executed example of the pipeline doing its job, not
  just a mock-agent projection. These are documented in CHANGELOG.md.
  No live-agent **PASS** has been confirmed end-to-end yet, so no
  live-agent Robustly Correct Fix Rate is reported here.
