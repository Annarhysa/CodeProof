# CodeProof Architecture

## Principle

CodeProof is not a coding agent. It is an independent evaluation and
verification layer that sits *after* a coding agent (Claude, Gemini, a
local Ollama model, or a custom agent) has proposed a fix, and produces
evidence a human can actually trust: "here is what was tested, here is what
was attacked, here is what failed, here is how reproducible the result is."

## Pipeline (all phases implemented)

```
GitHub Issue -> Sandbox -> Dependencies -> CodingAgent -> Reproduction -> Patch
             -> Tests -> Skeptic (adversarial) -> Evidence -> Verdict -> Autopsy
```

Plus, orthogonal to a single run: **Replay** (run the same evaluation N
times, measure verdict consistency) and the **Benchmark** suite (run every
seeded case through the real pipeline and report the Robustly Correct Fix
Rate, with a baseline comparison).

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
   want to run untrusted reproduction/test code with no network at all.
   Also mounts two **persistent, shared caches** (`~/.codeproof_cache/npm`,
   `/pip`) into every container, reused across every evaluation regardless
   of repo — a second run of any repo sharing a dependency doesn't
   re-download it. The image also runs
   `git config --global --add safe.directory '*'` as the non-root sandbox
   user — on some hosts (observed on Windows/Docker Desktop) a bind-mounted
   repo ends up owned by `root` inside the container regardless of the
   working directory's own ownership, and git 2.35.2+'s "dubious ownership"
   protection (CVE-2022-24765) then refuses `git diff`/`git status`
   entirely. Left unset, this silently presented as "the agent's patch made
   no changes" even when the agent had written a correct fix — see
   CHANGELOG.md, 2026-08-31.

2. **Dependencies** (`evaluator/dependencies.py`) — a deterministic step run
   once, before the agent gets control: detects `package.json` /
   `requirements.txt` / `pyproject.toml`, runs the right install command,
   and — this was a real, repeatedly-observed failure mode — cleans up and
   retries once if the first attempt fails, since a killed/partial install
   reliably corrupts the next attempt with permission/conflict errors. Not
   left to the agent: an agent forgetting to install, picking the wrong
   command, or retrying on top of corruption was the single biggest source
   of real-repo failures before this existed.

3. **CodingAgent** (`agents/base.py`) — an interface (`initialize /
   inspect_repository / reproduce_issue / propose_fix / apply_patch /
   run_tests / run_custom_stage`) every agent adapter implements.
   Implementations: `agents/mock.py` (scripted via a `Playbook`, still
   executes every command for real — only the choice of patch is
   scripted), `agents/claude_agent.py`, `agents/gemini_agent.py`,
   `agents/ollama_agent.py` (fully local, zero API key). All three live
   adapters share the same design — a manual tool-use loop
   (`list_files`/`read_file`/`write_file`/`run_command`), a forced
   structured-JSON final answer per stage, and a conservative default
   (not-reproduced / tests-failed) when that JSON doesn't parse, so an
   agent's unparseable output can never be silently read as success.
   `run_custom_stage(prompt, allow_write)` exposes the same tool-use loop
   for one-off stages — used by the Skeptic Agent.

4. **Evaluator** (`evaluator/pipeline.py`) — orchestrates the above and is
   the only place that decides PASS / FAIL / ABSTAIN. It never trusts the
   agent's self-report:
   - If the bug can't be reproduced, or the agent crashes during inspection
     or patch generation, the pipeline **ABSTAINS** with the failure as
     evidence rather than showing an unhandled crash or pretending a fix
     was verified.
   - PASS requires: reproduction reproduced pre-patch, reproduction clears
     post-patch, existing tests pass, **and** — if enabled — the Skeptic
     Agent's adversarial scenarios all pass too.
   - Every claim is written to an `EvidenceTimeline` (`evaluator/evidence.py`)
     with the actual command output attached — the evidence *is* the record,
     not an LLM's description of the record.

5. **Skeptic Agent** (`evaluator/skeptic.py`) — independent from the
   fixing agent: a fresh `CodingAgent` instance (from the same
   `agent_factory`, sharing the sandbox/patched repo state) with one
   instruction — assume the patch is wrong, find a counterexample. It
   writes and runs real adversarial scripts via `run_custom_stage`; nothing
   here is scored on the model's say-so, only on real command exit codes.
   Runs only after an otherwise-PASS result (no point attacking a fix that
   already failed). Optional per evaluation (`run_skeptic`) since it costs
   extra agent turns/API calls.

6. **Failure Autopsy** (`evaluator/failure_autopsy.py`) — rule-based (no
   extra LLM call), classifies any non-PASS verdict into one of the spec's
   nine categories (Environment failure, Failed reproduction, Incorrect
   patch, Wrong hypothesis, Regression, Edge case, Tool failure, Missing
   context, Weak test coverage) by pattern-matching the evidence/reason
   text CodeProof already produced, with an "earliest detectable point,"
   likely cause, and recommended action. Every rule here was derived from
   an actual failure observed running this pipeline against real repos.

7. **Replay** (`evaluator/replay.py`, `POST /evaluations/{id}/replay`) —
   re-runs the same inputs N times (fresh clone/sandbox/agent each time,
   nothing shared) and reports what fraction of runs agreed on the verdict.

8. **Backend** (`backend/app/`) — FastAPI, SQLite (`backend/app/db.py`).
   Evaluations (and each Replay run) execute in a background thread;
   `GET /evaluations/{id}` / `GET /replay/{id}` are polled by the frontend.
   `backend/app/auth.py` adds GitHub OAuth login (session via a signed
   cookie) so a user can pick a repo/issue from their own account instead
   of pasting a URL; `backend/app/github.py` handles the paste-a-URL path
   for any public (or token-accessible) issue.

9. **Frontend** (`frontend/`) — React + Vite, light theme. Dashboard, New
   Evaluation (Connect GitHub or manual entry), Evaluation Detail
   (reproduction, diff, tests, Skeptic results, Failure Autopsy, evidence
   timeline, agent trajectory, human review, Edit & Re-run, Replay), Replay
   Detail (consistency summary + constituent runs).

10. **Benchmark** (`benchmark/`) — `manifest.json` lists cases, each a real
    deliberate bug with a real test suite under `benchmark/issues/<id>/repo/`
    (a plain file tree, not a nested git repo, to avoid submodule
    confusion — `run_benchmark.py` turns it into a real git repo per run).
    `run_benchmark.py` runs every case through the real pipeline and
    reports the Robustly Correct Fix Rate. `baseline.py` additionally
    simulates a naive "one direct prompt, no verification" baseline per
    case and compares it against CodeProof, including a case
    (`sample-003-baseline-gap`) specifically seeded so the naive baseline
    produces a **false positive** that CodeProof catches — see
    `docs/EVALUATION.md` for the actual numbers from running this.

## Security model

- Repository code and agent-generated code are always treated as untrusted.
- All execution of that code happens inside Docker with capabilities
  dropped, privilege escalation disabled, a non-root user, and resource/time
  limits enforced. Network is enabled by default (see the Sandbox section
  above for why, and `lock_down_network()` for disabling it after setup).
- No API keys or host credentials are mounted into the sandbox container.
- Patches are applied only to an isolated temp working copy, never to the
  user's original repository.

## What's still genuinely missing

- The benchmark is a seed set of 3 real, verified, deliberately-authored
  cases — not the 20-30 real historical GitHub issues the spec asks for.
  Scaling that up is mechanical (add a case + a Playbook) but requires
  either much more live-agent API budget than this session had, or many
  more hours of building/verifying fixtures like the existing three.
- The three live agent adapters duplicate a large fraction of their
  tool-use-loop code; a shared base (or a LangGraph-based rewrite) would
  remove that duplication — noted, not done, since the current code is
  tested and working and a refactor risks regressing it late.
- `run_tests` and the post-patch `reproduce_issue` call currently make the
  agent re-detect the test framework / re-derive the repro command from
  scratch, from nothing but repo inspection, every single stage —
  `install_dependencies()` already knows the manifest type (pip vs. npm)
  before the agent ever runs, and isn't threaded through. Observed
  concretely on a weak local model (`llama3.2` via Ollama): it ran
  `npm test` against a pure-Python repo with no `package.json`, getting an
  `ENOENT`, which correctly counted as a test failure — but a repo with a
  manifest CodeProof already identified shouldn't need the agent to guess
  again. Proposed, not yet applied.
