# CodeProof

**An AI coding agent changed your code. Should you trust it?**

CodeProof is an independent evaluation and verification layer for AI coding
agents (Claude, Gemini, a local Ollama model, or a custom agent). It is not
another coding assistant, and it does not generate code for you to trust on
faith. Given a real GitHub issue and a patch an agent proposes, CodeProof:

1. Confirms the bug actually reproduces before trusting any "fix"
2. Runs the existing test suite against the patch in an isolated sandbox
3. Hands the patch to an independent Skeptic Agent whose only job is to try
   to break it with real adversarial scenarios
4. Classifies *why* anything failed, and can measure how reproducible a
   result actually is by re-running it
5. Builds an evidence timeline for every claim it makes
6. Lets a human make the final call — CodeProof provides evidence, not a
   verdict dressed up as one

> The agent makes the claim. CodeProof provides the evidence.

## Problem

Coding agents report success confidently and often wrongly. "Tests pass"
is not the same as "correct." Teams adopting autonomous coding agents have
no independent way to know whether a change is actually safe to merge
beyond re-reading the diff themselves — which defeats the point of
delegating the work.

## Who it's for

- Engineers using AI coding agents who want evidence before merging
- Teams evaluating which coding agent to trust for which kind of work
- Organizations building internal autonomous coding systems that need an
  independent verification layer, not a second opinion from the same kind
  of model that wrote the code

## Why existing coding agents are insufficient

A coding agent's self-report is correlated with its own blind spots — if it
missed an edge case while writing the fix, it will often miss the same edge
case while "verifying" it. Passing the existing test suite only proves the
patch didn't break what was already tested; it says nothing about whether
the patch is *robust* to inputs nobody wrote a test for yet. See
[docs/EVALUATION.md](docs/EVALUATION.md) for an actual, executed example of
this gap: a naive "trust the patch" baseline reports success on a case
where CodeProof's mandatory re-reproduction check catches a false fix.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full pipeline,
component responsibilities, and security model.

```
GitHub Issue -> Sandbox -> Dependencies -> CodingAgent -> Reproduction -> Patch
             -> Tests -> Skeptic -> Evidence -> Verdict -> Failure Autopsy
```

## Status

**Implemented**: Docker sandbox (with persistent shared dependency caches),
deterministic dependency installation, an agent-agnostic `CodingAgent`
interface with four adapters (mock/scripted, Claude, Gemini, and a fully
local zero-API-key Ollama adapter), the evaluator pipeline with an explicit
ABSTAIN path, an independent Skeptic Agent for adversarial testing, a
rule-based Failure Autopsy, Reproducibility Replay, a benchmark runner and
baseline-vs-CodeProof comparison, a FastAPI + SQLite backend with GitHub
OAuth login, and a React dashboard/evaluation-detail/replay UI with a human
review action bar.

**Real, honestly-scoped gaps**: the benchmark is a 3-case seed set (not the
20-30 real historical issues the spec asks for — see
[docs/EVALUATION.md](docs/EVALUATION.md) for why), and no live-agent
Robustly Correct Fix Rate is reported yet. A real infra bug that was
causing false ABSTAINs (a git "dubious ownership" failure inside the
sandbox silently misreported as "the agent made no changes") has since
been found and fixed; with it fixed, a live Ollama run produced an honest,
evidence-backed FAIL — the model skipped re-verifying its own fix and ran
the wrong test command, and CodeProof caught both — but no live run has
reached a confirmed PASS yet. See [CHANGELOG.md](CHANGELOG.md) for the
full account. Tracked honestly in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and
[CHANGELOG.md](CHANGELOG.md).

## Evaluation methodology

See [docs/EVALUATION.md](docs/EVALUATION.md) for the Robustly Correct Fix
Rate definition, secondary metrics, and the actual numbers from running the
seed benchmark — including a real, executed baseline-vs-CodeProof
comparison. No benchmark numbers are claimed anywhere in this repo until
they come from an actual run — see [CHANGELOG.md](CHANGELOG.md) for
exactly what has been executed so far.

## Quickstart

See [REPRODUCIBILITY.md](REPRODUCIBILITY.md) for full setup, or
[GUIDE.md](GUIDE.md) for a usage-focused walkthrough. Short version:

```bash
pip install -r requirements.txt
docker build -t codeproof-sandbox:latest sandbox
pytest tests/ -v                             # verify the pipeline works, no UI needed
python -m benchmark.baseline                  # real, executed baseline-vs-CodeProof comparison

uvicorn backend.app.main:app --reload --port 8000   # terminal 1
cd frontend && npm install && npm run dev            # terminal 2
```

Then open http://localhost:5173.

## Security model

Every repository and every line of agent-generated code is treated as
untrusted and executed only inside a locked-down Docker container (dropped
capabilities, non-root user, resource/time limits, no host credentials).
Details in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#security-model).

## Limitations

- The benchmark is a 3-case seed set of real, deliberate, verified bugs —
  not the full 20-30 real historical GitHub issues the spec calls for.
- No live-agent Robustly Correct Fix Rate reported yet — real-world runs
  this session hit genuine external constraints (slow installs, free-tier
  rate limits) plus a now-fixed infra bug (a git ownership check inside the
  sandbox was silently misreporting correct patches as "no changes") and,
  once that was fixed, a real model-capability limitation on a weak local
  model — all documented in [CHANGELOG.md](CHANGELOG.md); the mock-agent
  numbers in [docs/EVALUATION.md](docs/EVALUATION.md) validate the
  *pipeline*, not any one agent's real-world reasoning quality yet.
- The three live agent adapters (Claude/Gemini/Ollama) duplicate a fair
  amount of tool-use-loop code — noted as a refactor target, not done, to
  avoid regressing tested code late.

## Future work

Scaling the benchmark to real historical GitHub issues, a shared base (or
LangGraph-based) implementation for the live agent adapters to remove
duplication, and getting an actual live-agent Robustly Correct Fix Rate
once external rate-limit/billing constraints allow a full run — see
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
