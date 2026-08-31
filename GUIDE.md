# CodeProof — Setup & Usage Guide

## What this is for

You gave an AI coding agent a bug to fix. It says "done." Should you believe it?

CodeProof is an independent evaluation layer that sits between an AI coding
agent and your decision to merge its work. Point it at a real GitHub issue,
pick which agent should attempt it (Claude, Gemini, a fully local Ollama
model, or a scripted mock for testing), and CodeProof:

1. Clones the repo in an isolated Docker sandbox — never on your machine
2. Installs the repo's dependencies deterministically, before the agent
   touches anything (cached across runs)
3. Has the agent investigate the repo and try to **reproduce the bug for
   real** before trusting that it exists
4. Lets the agent propose and apply a fix, in that same sandbox
5. Re-runs the reproduction and the existing test suite to check the fix
   actually holds
6. Hands the patch to an independent **Skeptic Agent** whose only job is to
   try to break it with real adversarial scenarios
7. Classifies *why* anything failed (**Failure Autopsy**), and can re-run
   the same evaluation multiple times to check how **reproducible** the
   result actually is
8. Shows you the full evidence trail — every command run, every output,
   the agent's entire trajectory — so you can make the call yourself

The point isn't a second opinion from another AI. It's a system that
**refuses to say "it works" without evidence**, and says so honestly when it
can't establish that evidence — instead of a confident guess.

**Who this is for**: developers and teams using AI coding agents who want
proof before they merge, not just a agent's word for it.

---

## Setup

### Requirements

- Docker Desktop (or Docker Engine) running
- **Python 3.11** (not newer — see note below)
- Node.js 18+
- Git

> **Why Python 3.11 specifically**: at time of writing, Python 3.14 fails to
> install `pydantic` because `pydantic-core` has no prebuilt wheel for it
> yet and falls back to a Rust compile most machines can't do out of the
> box. If your system's default `python` is newer than 3.11, install 3.11
> alongside it and use that for this project's virtual environment.

### Install

```bash
git clone <this repo>
cd CodeProof

# Windows: py -3.11 -m venv .venv        macOS/Linux: python3.11 -m venv .venv
python -m venv .venv
.venv/Scripts/activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt

docker build -t codeproof-sandbox:latest sandbox

cd frontend && npm install && cd ..
```

### Configure credentials

```bash
cp .env.example .env
```

Then fill in whichever of these you need — **none are required to try the
tool** (the `mock` agent needs zero credentials), but you'll want at least
one live agent to evaluate a real issue:

| Variable | Needed for | Where to get it |
|---|---|---|
| `GEMINI_API_KEY` | live `gemini` agent | aistudio.google.com (free tier available) |
| `ANTHROPIC_API_KEY` | live `claude` agent | console.anthropic.com → Settings → API Keys |
| `ANTHROPIC_WORKSPACE_ID` | only if Claude gives a "workspace id required" error | console.anthropic.com → Settings → Workspaces |
| `GITHUB_TOKEN` | pasting a GitHub issue URL for a private repo, or to avoid rate limits on public repos | github.com/settings/tokens |
| `GITHUB_OAUTH_CLIENT_ID` / `_SECRET` | the "Connect GitHub → pick a repo → pick an issue" flow | register a free OAuth App at github.com/settings/developers, callback URL `http://localhost:8000/auth/github/callback` |
| `SESSION_SECRET_KEY` | required for GitHub OAuth login to work at all | any random string, e.g. `python -c "import secrets; print(secrets.token_hex(32))"` |

Full troubleshooting for each of these (rate limits, workspace IDs, OAuth
gotchas) is in [REPRODUCIBILITY.md](REPRODUCIBILITY.md).

### Run it

```bash
# terminal 1
uvicorn backend.app.main:app --port 8000

# terminal 2
cd frontend && npm run dev
```

Open **http://localhost:5173**.

### Or just verify it works, no UI

```bash
pytest tests/ -v
```

---

## How to use it

1. Click **+ New Evaluation** on the dashboard.
2. Choose **Connect GitHub** (log in, pick a repo you have access to, pick
   an open issue from a dropdown — or paste an issue URL directly) or
   **Enter Manually** (type in a repo URL and describe the issue yourself,
   useful for local repos or anything not on GitHub).
3. Pick an agent:
   - **gemini** / **claude** — a live agent that actually reads the repo and
     reasons about the issue. Needs the matching API key.
   - **ollama** — a live agent running fully locally, zero API key. Weaker
     than Claude/Gemini at reliable tool use — expect more ABSTAINs.
   - **mock** — a scripted agent that only understands the seeded benchmark
     fixtures, no API key needed. Good for confirming the pipeline itself
     works, not for evaluating a real issue.
4. Leave **Run Skeptic adversarial testing** checked if you want an
   independent pass trying to break an otherwise-passing patch (costs extra
   agent turns/API calls — uncheck to save quota).
5. Click **Start Evaluation** and watch it move through PENDING → RUNNING →
   a final verdict. A live agent run can take several minutes — it's
   genuinely working through install → investigate → reproduce → fix →
   verify → (optionally) adversarial testing, not stuck.
6. On the result page, review the reproduction, the diff, the test results,
   Skeptic's adversarial scenarios, the Failure Autopsy (if it didn't
   PASS), the full evidence timeline, and the agent's raw trajectory. Then
   record your own call: Approve / Request Revision / Reject / Abstain.
7. From a finished evaluation, **Edit & Re-run** takes you back to the form
   pre-filled with its inputs; **Replay** re-runs the same inputs 3 times
   to check how reproducible the verdict actually is.

---

## What each verdict means

| Verdict | Meaning |
|---|---|
| **PASS** | The agent reproduced the bug, its patch made the reproduction pass, the existing test suite still passes, and — if Skeptic ran — every adversarial scenario it constructed also passed. |
| **FAIL** | The agent proposed a patch, but either the bug still reproduces after it, existing tests broke, or the Skeptic Agent found an adversarial case that breaks the fix ("not fully verified"). |
| **ABSTAIN** | CodeProof could not gather enough evidence to judge either way. This happens when: the repo couldn't be cloned, the agent couldn't reproduce the bug in the first place (so there's nothing to verify a fix against), or the agent failed partway through (crashed, claimed a fix it never actually wrote, ran out of its turn budget mid-investigation, etc.). **ABSTAIN is not a bug** — it's CodeProof refusing to fabricate a verdict it can't back with evidence. Read the reason and the evidence timeline to see exactly where it stopped. |

Evaluation **status** (separate from verdict) — `PENDING` → `RUNNING` →
`DONE` (verdict is now set) or `ERROR` (something in the pipeline itself
crashed unexpectedly — check the error field; this is different from an
agent failure, which shows up as ABSTAIN, not ERROR).

---

## Limitations (be honest with yourself about what a verdict covers)

- **The mock agent only understands the seeded benchmark fixtures.** Don't
  expect it to evaluate a real, arbitrary issue — use a live agent for that.
- **Live agent behavior is non-deterministic.** The same issue can get a
  different verdict on different runs — use **Replay** to actually measure
  that instead of assuming.
- **Free-tier LLM quotas are tight.** Gemini's free tier caps out at a
  small number of requests per day; a single evaluation stage can use a
  meaningful chunk of that on a real multi-file repo, and Skeptic adds more
  on top (uncheck it to conserve quota).
- **The benchmark is a 3-case seed set**, not the 20-30 real historical
  GitHub issues the project's spec calls for — see docs/EVALUATION.md for
  exactly what has and hasn't been run, and why.
- **A weaker local model (Ollama) will cut corners under verification.**
  We've observed it skip re-running its own reproduction check after
  applying a patch — reporting the exact same result as before, without
  calling a single tool — and separately run the wrong test command
  (`npm test` on a repo with no `package.json`). CodeProof doesn't trust
  either claim at face value, which is exactly why both showed up as an
  honest FAIL with full evidence instead of a false PASS.
