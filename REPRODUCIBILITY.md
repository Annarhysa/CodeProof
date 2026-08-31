# Reproducing a CodeProof Evaluation

## Requirements

- Windows/macOS/Linux with Docker Desktop (or Docker Engine) running
- **Python 3.11** for the venv running the backend/CLI (see note below —
  Python 3.14 currently fails to install `pydantic` because `pydantic-core`
  has no prebuilt wheel for it yet and falls back to a Rust build that needs
  MSVC/Rust toolchains most machines don't have). 3.11 is also what the
  sandbox Docker image uses internally.
- Node.js 18+ (for the frontend)
- Git

## Setup

```bash
git clone <this repo>
cd CodeProof

# Use Python 3.11 specifically if your default `python` is newer (see note above).
# Windows: py -3.11 -m venv .venv    macOS/Linux: python3.11 -m venv .venv
python -m venv .venv
.venv/Scripts/activate       # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt

cp .env.example .env         # fill in credentials — see "Live agent credentials" below

docker build -t codeproof-sandbox:latest sandbox
```

## Live agent credentials

The `mock` agent needs no credentials at all — it's fully scripted. To use
a live agent that actually reasons about a real repo/issue:

**Claude** (`ANTHROPIC_API_KEY` in `.env`):
- Some Anthropic orgs issue "identity-linked" API keys that require an
  additional `ANTHROPIC_WORKSPACE_ID` in `.env`. You'll know you need this
  if a request fails with `anthropic-workspace-id is required...`. Find it
  at console.anthropic.com → Settings → Workspaces → (your workspace) → copy
  its ID (starts with `wrkspc_`) — specifically the workspace the *key
  itself* belongs to, which isn't always the first one you'd guess if your
  account has several.
- Needs a positive credit balance (Settings → Plans & Billing). A `400`
  error mentioning "credit balance is too low" means this, not a code bug.

**Gemini** (`GEMINI_API_KEY` in `.env`, free tier available at
aistudio.google.com):
- The free tier enforces both a per-minute limit and a **daily** cap (as low
  as 20 requests/day on some models) — an agentic tool-use loop can burn
  several requests per pipeline stage, so a handful of runs can exhaust a
  day's quota. `agents/gemini_agent.py` retries per-minute `429`s
  automatically but fails fast (no point retrying) on a daily-quota `429` —
  if you see that, wait for the ~24h reset or use a paid tier.
- Model names on this API move fast; if you get a `404 ... no longer
  available`, the error message itself names the replacement — update
  `CODEPROOF_AGENT_MODEL_GEMINI` in `.env` or the `DEFAULT_MODEL` in
  `agents/gemini_agent.py`.

**Ollama** — zero API key, runs entirely on your machine:
- Install from ollama.com, then `ollama pull llama3.2` (or another
  tool-calling-capable model — `qwen2.5`, `mistral-nemo`) and make sure the
  server is reachable at `http://localhost:11434` (`curl
  http://localhost:11434/api/version`).
- Set `CODEPROOF_OLLAMA_MODEL` in `.env` if you pull a different model than
  the default (`llama3.2`).
- Honest expectation: a small local model is noticeably weaker at reliable
  structured tool-calling than Claude/Gemini — expect more `ABSTAIN`s from
  the model itself producing malformed output or losing track of the real
  repo, on top of the same real-world friction (slow installs) every agent
  hits. Concretely observed with `llama3.2`: it will sometimes skip
  actually re-running a verification command and just repeat its previous
  answer, and will guess a test-runner command (e.g. `npm test`) instead
  of checking which manifest is actually present. CodeProof's pipeline
  doesn't trust either without evidence, so these surface as an honest
  FAIL, not a silently-wrong PASS — see CHANGELOG.md, 2026-08-31.

## Run the backend

```bash
uvicorn backend.app.main:app --reload --port 8000
```

## Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

## Run the vertical-slice tests (no UI needed)

```bash
pytest tests/ -v
```

- `test_pipeline_mock.py` — mock agent against the known fixture. No
  credentials needed; asserts a PASS verdict backed by real sandboxed
  command output. Skips (not fails) if Docker isn't available.
- `test_claude_agent_smoke.py` / `test_gemini_agent_smoke.py` /
  `test_ollama_agent_smoke.py` — same fixture, driven by a real live agent.
  Skip if the relevant API key/Ollama instance isn't available. These
  assert only that the pipeline reaches a real verdict (PASS/FAIL/ABSTAIN)
  with a non-empty trajectory — a live agent's exact behavior isn't
  asserted turn-by-turn, since it's non-deterministic.

## Run the benchmark suite

```bash
python -m benchmark.run_benchmark              # mock agent, free, deterministic
python -m benchmark.run_benchmark --agent claude
python -m benchmark.baseline                    # baseline vs. CodeProof comparison
```

Results are saved to `benchmark/results/*.json`. See `docs/EVALUATION.md`
for what the seed set's actual numbers are and what they show.

## Try Reproducibility Replay

From the UI: open any finished evaluation, click **↻ Replay**. From the
API: `POST /evaluations/{id}/replay` with `{"n": 3}`, then poll
`GET /replay/{id}` for the consistency summary.

## Cost/time

- Mock-agent pipeline run: ~10-30s end-to-end on a warm Docker image
  (dominated by `pip install` inside the sandbox); no API calls, no LLM
  cost.
- Live-agent run (Claude or Gemini): typically a few dozen API turns across
  the 4 pipeline stages (inspect/reproduce/patch/test) on a small repo,
  each turn capped at 4096 output tokens; several minutes wall-clock,
  small-repo runs typically well under $0.10 on Claude at current pricing
  (see `.env.example` for how to point at a specific model).
