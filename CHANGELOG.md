# Changelog

## 2026-08-29 — Repository reset + P0 vertical slice

**Context**: the repository previously contained an unrelated leftover
project ("EcoVision", a Flask + create-react-app boilerplate) already
deleted from disk but still tracked by git. There was nothing to reuse for
CodeProof; started from a clean slate.

**Built**:
- `sandbox/` — Docker-isolated command execution (`runner.py`): no host
  credentials, dropped capabilities, resource + time limits, full
  command/output capture. (Network started as `--network none`; changed same
  day — see next entry.)
- `agents/base.py` — `CodingAgent` interface (agent-agnostic by design).
- `agents/mock.py` — scripted mock adapter driven by a `Playbook`. Decision:
  the mock still executes every command for real inside the sandbox (only
  the choice of patch is scripted), per the "real execution over mocked
  success" principle — a stub that always reports success would defeat the
  point of an evaluation layer.
- `evaluator/pipeline.py` — orchestrates
  clone → inspect → reproduce → patch → re-reproduce → test → evidence → verdict,
  with an explicit ABSTAIN path when the bug can't be reproduced or the repo
  can't be cloned.
- `evaluator/evidence.py` — evidence timeline backing every claim with
  actual command output.
- `backend/` — FastAPI + SQLite, evaluations run in a background thread,
  polled by the frontend.
- `frontend/` — React/Vite dashboard, New Evaluation form, Evaluation Detail
  page (reproduction, diff, tests, evidence timeline, trajectory, human
  review actions).
- `benchmark/issues/sample-001-average-int-division/` — first benchmark
  case: a small Python repo with a real, deliberate bug (`average()` uses
  integer division) and a pytest suite, used to validate the pipeline
  end-to-end without needing a live LLM key.
- `tests/test_pipeline_mock.py` — end-to-end pipeline test against that
  fixture; skips gracefully if Docker is unavailable.

**Decision**: MVP ships with only the mock/local agent adapter (no live LLM
integration yet) — user confirmed this is acceptable for the first slice,
with a real GitHub issue to be supplied once the pipeline works end-to-end.
Credentials (ANTHROPIC_API_KEY, GITHUB_TOKEN) are read from `.env`
(gitignored) rather than hardcoded.

**Not yet built** (tracked, not silently skipped): Skeptic Agent /
adversarial testing, Reproducibility replay, Failure Autopsy, live agent
adapter, benchmark manifest beyond the one seed case, baseline-vs-CodeProof
comparison. See docs/ARCHITECTURE.md "Not yet implemented".

**No benchmark numbers have been reported anywhere in this repo** — the
only thing that has actually run is the single fixture case above.

## 2026-08-29 — Live agent adapters (Claude + Gemini) and what they broke

**Tried**: pointed the mock agent at a real user-supplied issue (a Next.js
resume-export repo). It failed immediately — the mock agent is a scripted
Python-only playbook, not a reasoning agent, so it ran `pip install -r
requirements.txt` against a repo with no such file and correctly ABSTAINed.
**Learning**: a scripted "mock" agent proves the *evaluation infrastructure*
works, but cannot itself evaluate a real, arbitrary issue — that requires an
agent that actually reasons about the specific repo in front of it.

**Built**: `agents/claude_agent.py` — a live adapter using the Anthropic API
with a manual tool-use loop (`list_files` / `read_file` / `write_file` /
`run_command` against the sandbox), producing the same `CodingAgent`
interface as the mock. Each pipeline stage ends in a forced structured-JSON
turn (e.g. `{"reproduced": true|false, ...}`); if the model's output doesn't
parse, the agent defaults to the *conservative* outcome (not reproduced /
tests failed) rather than a false positive.

**Broke #1 — sandbox network vs. dependency installs**: `--network none`
(the original design) makes `pip install` / `npm install` impossible, so no
repo with third-party dependencies could ever be evaluated — this includes
almost every real repo. **Decision**: default the sandbox to network-enabled,
add every other isolation layer instead (cap-drop ALL, no-new-privileges,
non-root user, memory/CPU/pids limits), and add `Sandbox.lock_down_network()`
as an opt-in for flows that want strict isolation after setup. Full
network isolation is the "safer" answer on paper but makes the tool useless
on real-world code — chose the practical tradeoff and documented it.

**Broke #2 — identity-linked API keys need a workspace ID**: some Anthropic
orgs issue "identity-linked" keys that return `400` on every request unless
an `anthropic-workspace-id` header is attached — and the SDK only
auto-attaches that header via its OAuth/profile credential chain, silently
*not* for a plain `ANTHROPIC_API_KEY` env var. Fixed by reading
`ANTHROPIC_WORKSPACE_ID` from `.env` and passing it as an explicit
`default_headers` entry on the client. Took several rounds of trial and
error to find the *correct* workspace ID specifically (the workspace list
page and the key's own workspace didn't obviously match at first).

**Broke #3 — agent claims success without evidence**: on a real run, the
Claude/Gemini adapters would sometimes write a plausible-sounding
`explanation` for `propose_fix()` ("changed `//` to `/`...") while never
actually calling `write_file` — so `git diff` came back empty. The original
`apply_patch()` raised an unhandled exception in this case, crashing the
whole evaluation. **Decision**: wrapped the entire patch-generation-through-
verification block in `evaluator/pipeline.py` in a try/except that converts
*any* agent failure into an honest `ABSTAIN` with the failure recorded as
evidence, instead of an unhandled crash. This is the core thesis of the
project working as intended — "the agent claimed X, CodeProof caught that X
wasn't backed by evidence" — it just needed to fail *gracefully* instead of
loudly.

**Built**: `agents/gemini_agent.py` — same design as the Claude adapter,
using `google-genai`'s manual function-calling loop (`FunctionDeclaration` /
`Tool` / `Part.from_function_response`), so CodeProof now has two live,
functionally-interchangeable agent adapters behind the same interface —
demonstrating the agent-agnostic design actually holds up, not just in
theory.

**Broke #4 — free-tier quotas are much tighter than expected**: Gemini's
free tier enforces both a per-minute AND a *daily* request cap (as low as
20 requests/day on some models during testing) — an agentic tool-use loop
can burn through several requests per pipeline stage, so a handful of
smoke-test runs exhausted the day's quota. Added retry-with-backoff for
per-minute `429`s (reading the server's suggested `retryDelay`), but made it
fail fast (no pointless retry loop) when the `429` is specifically a
`PerDay` quota violation, since waiting the suggested delay does nothing for
a daily cap.

**Status**: both live adapters are wired end-to-end and mechanically
correct (verified via `tests/test_claude_agent_smoke.py` and
`tests/test_gemini_agent_smoke.py`, which hit real APIs against the known
fixture case). A full PASS/FAIL run against the fixture with either live
adapter is still pending — Claude was blocked by account billing, Gemini by
the daily free-tier quota — but the pipeline's *handling* of both real
successes and real agent failures (via the ABSTAIN path) is confirmed
working.

## 2026-08-29 — GitHub Issue Input (spec Phase 2)

**Built**: `backend/app/github.py` — read-only GitHub REST API client
(`GET /github/issue?url=...`) that parses a GitHub issue URL, fetches the
issue's title/body/state and the repo's clone URL/default branch, and
rejects PR URLs (GitHub's API represents PRs as issues with an extra
`pull_request` key — worth checking explicitly, confirmed against a real PR
URL during testing). Uses `GITHUB_TOKEN` from `.env` if present (raises the
otherwise-low unauthenticated rate limit); works without one for public
repos. Frontend: `NewEvaluation.jsx` now has a "paste a GitHub issue URL →
Load Issue" step that previews the issue (repo, number, status,
description) per the original spec mockup, then auto-fills the repo
URL/title/body fields that drive the evaluation — the manual text-entry
fields are kept as a fallback for local/non-GitHub repos.

**Operational note (not a code bug)**: while testing this, `uvicorn --reload`
left an orphaned worker subprocess running after its parent (reloader)
process was killed — `taskkill` on the reloader's PID doesn't kill its
child, so the old server (and its stale `.env` snapshot) kept serving
requests on the same port. Diagnosed via `Get-CimInstance Win32_Process`
listing full command lines; fixed by killing the actual worker PID too.
Worth remembering for any future "I changed `.env` but nothing changed"
report against a `--reload` dev server.

## 2026-08-29 — GitHub OAuth login + first real-repo run, and what it revealed

**Built**: `backend/app/auth.py` — GitHub OAuth ("Connect GitHub" → pick a
repo you own/collaborate on → pick an open issue), on top of the existing
paste-a-URL flow. Session held in a signed cookie (Starlette
`SessionMiddleware`) — a deliberate hackathon-scope simplification, not
encrypted, fine for local single-user use, called out as a limitation.
**Broke while wiring it up**: the OAuth callback must use the same hostname
(`localhost`, not `127.0.0.1`) as the page that started the login — the
pre-redirect session cookie (holding the CSRF `state` value) is scoped to
whatever host the browser saw first, and `localhost`/`127.0.0.1` are
different hosts for cookie purposes even on the same machine. Cost a round
of "invalid OAuth state" errors before catching it.

**First real-repo run**: pointed the Gemini agent at a real issue on a real
user's Next.js/TypeScript project ("Attuned" — fix resume/cover-letter PDF
export formatting). Result: `ABSTAIN`. Trajectory shows the agent actually
did the right investigative work — found `documentExporter.tsx`, the
`@react-pdf/renderer`/`docx` rendering logic, `DesignSelector.tsx`, the
`DesignTemplate` model — but ran out of its 8-turn stage budget mid-
exploration before producing a summary, and separately failed to execute
its reproduction script because it never ran `npm install` (no
`node_modules`, `Cannot find module 'react'`).

**Decision**: raised `MAX_TURNS_PER_STAGE` 8 → 20 (configurable per agent
via `CODEPROOF_CLAUDE_MAX_TURNS` / `CODEPROOF_GEMINI_MAX_TURNS`) — 8 was
tuned against the tiny single-file fixture repo and never validated against
a real multi-file codebase. Also added an explicit "install dependencies
first if this repo needs them" instruction to the reproduction-stage prompt
in both agents — the agent could infer this itself in principle, but didn't,
so making it explicit is cheaper than hoping. **Tradeoff flagged, not yet
resolved**: on Gemini's free tier (as low as 20 requests/day), a single
stage can now consume the *entire* day's quota — there's a real tension
between "enough turns to actually explore a real repo" and "stay within a
free-tier budget" that a paid tier or a smarter turn-budget (e.g. shrinking
per-stage limits, or summarizing/compacting mid-stage) would resolve.

**This is good "Hot Take" material for the final submission**: an agent can
do genuinely correct repo investigation and still produce zero usable
output if it runs out of budget before reaching a conclusion — and
"ABSTAIN" is the *correct* response to that, not a bug to hide. A shallow
eval would have no way to distinguish "the agent failed to understand the
code" from "the agent understood fine but ran out of turns/tokens" — this
trajectory-level evidence is exactly what makes that distinction visible.

## 2026-08-31 — Remaining phases: Skeptic, Failure Autopsy, Replay,
## Benchmark, Baseline comparison, Ollama adapter, dependency caching

**Built, in order of what unblocked what:**

- **Deterministic dependency installation** (`evaluator/dependencies.py`) —
  moved dependency install out of the agent's hands entirely: detects
  `package.json`/`requirements.txt`/`pyproject.toml`, installs once before
  the agent gets control, cleans up and retries once on failure (the exact
  corruption pattern hit on `Attuned`). Backed by persistent, shared
  npm/pip caches mounted into every sandbox (`~/.codeproof_cache/`) so
  repeat runs — even of different repos sharing a dependency — don't
  re-download it. This was the single most-requested fix ("how do we make
  this work on bigger repos") and traces directly back to every real
  `Attuned` failure this session.

- **Ollama adapter** (`agents/ollama_agent.py`) — a fourth `CodingAgent`
  implementation, zero API key, runs fully locally via Ollama's REST API.
  Confirmed working mechanically end-to-end, but a 3B model
  (`llama3.2`) genuinely hallucinated file paths that don't exist in the
  real repo rather than using its own `list_files` tool to check — a real,
  observed, worth-reporting failure mode distinguishing "the harness works"
  from "the model is capable enough," not a hypothetical caveat.

- **`run_custom_stage` on `CodingAgent`** (`agents/base.py`) — a small
  interface addition so the Skeptic Agent can drive the exact same
  tool-use loop every adapter already has, with a caller-supplied prompt,
  instead of duplicating agentic-loop logic a fourth time.

- **Skeptic Agent** (`evaluator/skeptic.py`) — a fresh, independent
  `CodingAgent` instance (same provider, new conversation, sharing the
  patched sandbox) instructed to assume the patch is wrong and find a
  counterexample. Writes and runs real adversarial scripts; only runs
  after an otherwise-PASS result; optional per evaluation
  (`run_skeptic`) since it costs extra agent turns. Verified for real via
  `benchmark/run_benchmark.py`: the `clamp` fixture's skeptic generated 2
  genuinely relevant boundary-value scenarios and ran them for real in the
  sandbox.

- **Failure Autopsy** (`evaluator/failure_autopsy.py`) — deliberately
  rule-based, not LLM-based: every one of the nine categories is pattern-
  matched against evidence CodeProof already produced. Every rule traces to
  an actual failure observed this session (the `write_file`-claimed-but-
  nothing-changed anomaly → "Incorrect patch"; the turn-budget exhaustion
  on `Attuned` → "Missing context"; etc.) rather than being speculative.

- **Reproducibility Replay** (`evaluator/replay.py`,
  `POST /evaluations/{id}/replay`) — re-runs the same inputs N times with
  a fresh clone/sandbox/agent each time (nothing shared) and reports
  verdict consistency. Verified via the real API: 3/3 consistent on the
  deterministic mock agent, exactly as expected.

- **Benchmark suite + baseline comparison**
  (`benchmark/run_benchmark.py`, `benchmark/baseline.py`) — expanded the
  benchmark from 1 to 3 real, deliberate, verified-bug fixture cases and
  built a runner that executes every case through the real pipeline
  (Robustly Correct Fix Rate: 3/3 = 100% on the mock agent, actually run,
  not asserted). The baseline comparison simulates a naive "one direct
  prompt, no verification" agent per the spec's own example, and one case
  (`sample-003-baseline-gap`) is deliberately seeded with a plausible-but-
  incomplete baseline patch. Result, from an actual run: **baseline claimed
  success on 3/3 cases but was only actually correct on 2/3 — 1 false
  positive, which CodeProof caught and correctly reported as FAIL.** This
  is the project's core thesis, executed and measured, not asserted.

**Broke while building this — a real, non-obvious cross-platform bug**:
`benchmark/baseline.py`'s patch application failed with "patch does not
apply" even for a patch identical to one that worked fine through the main
pipeline. Root cause: Python's text-mode file write silently turns `\n`
into `\r\n` on Windows, and whether a checked-out file's line endings match
depends on git's `autocrlf` behavior *and* on whether the repo was reached
via an actual `git clone` (checkout, subject to autocrlf) or a plain
`git init`+`add`+`commit` (no checkout, working-tree files untouched) — two
code paths that had been landing on the same result "by accident" until a
third path (baseline.py) didn't. Fixed at the root, not patched around:
`Sandbox.write_file()` now writes with `newline=""` (exact bytes, no
translation) and `clone_repo()` clones with `-c core.autocrlf=false`
(checked-out files stay byte-identical to what's stored) — both `agents/
mock.py` and `benchmark/baseline.py` were updated to route through the
fixed `sandbox.write_file()` instead of writing patches manually. Confirmed
the fix didn't regress the already-working main pipeline (26/26 tests,
including the full mock end-to-end PASS, still green after the change) —
worth remembering that "it worked before" doesn't mean the *right* thing
happened, just that two bugs happened to cancel out.

**Not done, and why**: scaling the benchmark to the spec's 20-30 real
historical GitHub issues — genuinely requires either far more live-agent
API budget than this session had (every case is several agent turns ×
however many live cases you want) or many more hours authoring/verifying
fixtures by hand like the existing three. Documented as an honest gap in
README.md/EVALUATION.md rather than papered over with invented cases.

## 2026-08-31 — Root-caused the recurring "agent produced no file changes"
## false negative

Every live-agent run (Ollama, then Gemini) kept ABSTAINing with "agent
produced no file changes during propose_fix", even on a case where the
trajectory showed the model reading the right file, writing the right fix,
and re-verifying it worked. That last data point ruled out a model
capability problem — CodeProof's own verification step was lying about
what happened.

**Root cause**: `apply_patch` decides whether anything changed by running
`git diff` / `git diff --name-only` inside the sandbox container after the
agent's tool calls. On this host, the repo directory bind-mounted into the
container (`host_repo_path -> /workspace`) ends up owned by `root` even
though the container's non-root `sandbox` user (added earlier for
isolation) created the `WORKDIR` and was `chown`'d into it — a Windows /
Docker Desktop bind-mount quirk. Git 2.35.2+ refuses to run `git diff` or
`git status` on a repo it doesn't own (the CVE-2022-24765 "dubious
ownership" mitigation) and fails with `fatal: detected dubious ownership in
repository at '/workspace'` — not a "no changes" result, a hard failure
that the diff-parsing code was silently treating as "0 files changed"
because it only looked at stdout, not the exit code. The agent's edit was
real; CodeProof just couldn't see it.

**Fix**: `sandbox/Dockerfile` now runs
`git config --global --add safe.directory '*'` as the `sandbox` user,
after `USER sandbox`. `*` rather than a specific path because the ownership
mismatch is a mount artifact, not something we control per-repo, and the
threat this git protection exists for (an attacker planting a hostile repo
elsewhere on a shared host for another user to `cd` into) doesn't apply
inside an already-isolated, single-purpose, single-tenant container.
Rebuilt `codeproof-sandbox:latest`; directly verified with a throwaway
script that `git status`/`git diff` against the same fixture that had been
failing now return exit `0` instead of exit `128`. Full suite still 26/26
green after the change — confirms it doesn't regress anything the
existing tests already covered.

**Likely retroactive impact**: this almost certainly explains most, maybe
all, of the "0 files changed" ABSTAINs seen across the whole session with
every live adapter (Ollama, Gemini, and possibly the earlier Claude runs)
— previously guessed at as model reliability limits. No backend restart is
required for the fix to take effect: the sandbox container is created
fresh per evaluation from whatever image is currently tagged
`codeproof-sandbox:latest`, so the next evaluation run automatically picks
up the rebuilt image.

**Not yet done**: a live end-to-end confirmation that this now produces an
actual PASS verdict — blocked in this session on `GEMINI_API_KEY` not
being present in the shell environment used to run a verification script
directly, so the retest needs to happen through the running backend
(which has its own working credentials) rather than standalone.
