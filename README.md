# CodeProof

**An AI coding agent changed your code. Should you trust it?**

CodeProof is an independent evaluation and verification layer for AI coding
agents (Claude, Codex, Gemini, Cursor, or a custom agent). It is not another
coding assistant, and it does not generate code for you to trust on faith.
Given a real GitHub issue and a patch an agent proposes, CodeProof:

1. Confirms the bug actually reproduces before trusting any "fix"
2. Runs the existing test suite against the patch in an isolated sandbox
3. Hands the patch to an independent Skeptic Agent whose only job is to try
   to break it (planned — see Status below)
4. Builds an evidence timeline for every claim it makes
5. Lets a human make the final call — CodeProof provides evidence, not a verdict dressed up as one

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
the patch is *robust* to inputs nobody wrote a test for yet.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full pipeline,
component responsibilities, and security model.

```
GitHub Issue -> Sandbox -> CodingAgent -> Reproduction -> Patch -> Tests -> Evidence -> Verdict
```

## Status

**Implemented (P0 vertical slice)**: Docker sandbox execution, agent-agnostic
`CodingAgent` interface + a mock/scripted adapter (real sandboxed execution,
scripted patch selection — no LLM key required), the evaluator pipeline with
an explicit ABSTAIN path, an evidence timeline, a FastAPI + SQLite backend,
and a React dashboard/evaluation-detail UI with a human review action bar.

**Not yet implemented**: Skeptic Agent + adversarial testing, reproducibility
replay, failure autopsy, live LLM agent adapter, full benchmark suite,
baseline-vs-CodeProof comparison. Tracked in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [CHANGELOG.md](CHANGELOG.md).

## Evaluation methodology

See [docs/EVALUATION.md](docs/EVALUATION.md) for the Robustly Correct Fix
Rate definition and secondary metrics. No benchmark numbers are claimed
anywhere in this repo until they come from an actual run — see
[CHANGELOG.md](CHANGELOG.md) for exactly what has been executed so far.

## Quickstart

See [REPRODUCIBILITY.md](REPRODUCIBILITY.md) for full setup. Short version:

```bash
pip install -r requirements.txt
docker build -t codeproof-sandbox:latest sandbox
pytest tests/test_pipeline_mock.py -v      # verify the pipeline works, no UI needed

uvicorn backend.app.main:app --reload --port 8000   # terminal 1
cd frontend && npm install && npm run dev            # terminal 2
```

Then open http://localhost:5173.

## Security model

Every repository and every line of agent-generated code is treated as
untrusted and executed only inside a locked-down Docker container (no
network, dropped capabilities, resource/time limits, no host credentials).
Details in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#security-model).

## Limitations

- No live LLM coding-agent adapter yet — only a scripted mock adapter, so
  today's pipeline proves the *evaluation infrastructure* works, not that it
  has evaluated a real agent's real reasoning yet.
- No Skeptic/adversarial layer yet, so "PASS" today means "reproduced +
  fixed + existing tests pass," not the full Robustly Correct Fix Rate
  definition.
- Single benchmark fixture case so far, not the full 20-30 case suite.

## Future work

Skeptic Agent, reproducibility replay, failure autopsy, a real benchmark of
20-30 historical public-repo issues, baseline-vs-CodeProof comparison, and a
live Claude-based agent adapter — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
