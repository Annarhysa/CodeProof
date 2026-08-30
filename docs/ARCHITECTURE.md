# CodeProof Architecture

## Principle

CodeProof is not a coding agent. It is an independent evaluation and
verification layer that sits *after* a coding agent (Claude, Codex, Gemini,
Cursor, or a custom agent) has proposed a fix, and produces evidence a human
can actually trust: "here is what was tested, here is what was attacked,
here is what failed, here is how reproducible the result is."

## Pipeline (P0 vertical slice, implemented)

```
GitHub Issue -> Sandbox -> CodingAgent -> Reproduction -> Patch -> Tests -> Evidence -> Verdict
```

1. **Sandbox** (`sandbox/runner.py`) — clones the target repo on the host
   (network required for clone only), then runs everything else inside a
   Docker container: `--cap-drop ALL`, `--security-opt no-new-privileges`,
   `--pids-limit`, memory/CPU limits, a non-root user, and a hard timeout on
   every command. No host credentials are ever passed into the container.
   Network is enabled by default so dependency installs (`pip install`,
   `npm ci`, ...) can actually reach a package registry — a `--network none`
   container can't evaluate any repo with third-party dependencies, which
   would make most real-world issues untestable. `Sandbox.lock_down_network()`
   disconnects the container from the network after setup, for flows that
   want to run untrusted reproduction/test code with no network at all; the
   pipeline doesn't call it yet (P1: wire it in once dependency-install is a
   distinct pipeline step from reproduction, instead of both being bundled
   into one shell command by the agent).

2. **CodingAgent** (`agents/base.py`) — a small interface
   (`initialize / inspect_repository / reproduce_issue / propose_fix /
   apply_patch / run_tests`) that any agent adapter implements. The MVP ships
   `agents/mock.py`, a scripted adapter driven by a `Playbook`
   (`benchmark/playbooks.py`) that still executes every command for real
   inside the sandbox — only the "intelligence" (what patch to try) is
   scripted, not the execution. A live LLM adapter (e.g. Claude via the
   Messages API) can be dropped in behind the same interface without
   touching the pipeline.

3. **Evaluator** (`evaluator/pipeline.py`) — orchestrates the above and is
   the only place that decides PASS / FAIL / ABSTAIN. It never trusts the
   agent's self-report:
   - If the bug can't be reproduced, the pipeline **ABSTAINS** rather than
     evaluating a fix for a bug it never confirmed existed.
   - PASS requires: reproduction reproduced pre-patch, reproduction clears
     post-patch, and existing tests pass.
   - Every claim is written to an `EvidenceTimeline` (`evaluator/evidence.py`)
     with the actual command output attached — the evidence *is* the record,
     not an LLM's description of the record.

4. **Backend** (`backend/app/`) — FastAPI, SQLite (`backend/app/db.py`).
   Evaluations run in a background thread per request (`threading.Thread`);
   `GET /evaluations/{id}` is polled by the frontend for live status. Good
   enough for hackathon scale; the natural next step is a real task queue
   (RQ/Celery) if evaluations need to run concurrently at volume.

5. **Frontend** (`frontend/`) — React + Vite. Dashboard, New Evaluation form,
   and an Evaluation Detail page showing reproduction, patch/diff, tests,
   the full evidence timeline, agent trajectory, and a human review action
   bar (Approve / Request Revision / Reject / Abstain).

## Not yet implemented (see README.md priority list)

- Skeptic Agent + adversarial testing (`evaluator/skeptic.py` — planned)
- Reproducibility replay (`evaluator/replay.py` — planned)
- Failure Autopsy classification
- Benchmark runner + baseline-vs-CodeProof comparison
- Live LLM agent adapter (only the mock/scripted adapter exists today)

## Security model

- Repository code and agent-generated code are always treated as untrusted.
- All execution of that code happens inside Docker with capabilities
  dropped, privilege escalation disabled, a non-root user, and resource/time
  limits enforced. Network is enabled by default (see the Sandbox section
  above for why, and `lock_down_network()` for disabling it after setup).
- No API keys or host credentials are mounted into the sandbox container.
- Patches are applied only to an isolated temp working copy, never to the
  user's original repository.
