"""
Live CodingAgent adapter backed by the Google Gemini API, mirroring
agents/claude_agent.py's design (manual tool-use loop against the sandbox,
structured-JSON final answers, conservative defaults on unparseable output).
CodeProof is agent-agnostic — this and ClaudeCodingAgent implement the same
CodingAgent interface, so evaluator/pipeline.py doesn't care which one runs.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from agents.base import CodingAgent, Patch, ReproductionResult, TestRunResult
from sandbox.runner import Sandbox, SandboxError

load_dotenv()

DEFAULT_MODEL = os.environ.get("CODEPROOF_AGENT_MODEL_GEMINI", "gemini-3.6-flash")
# 8 was enough for small fixture repos but left a real Next.js/TypeScript
# codebase (dozens of files) stuck mid-exploration with no summary/answer
# produced yet. Raised after observing that on a real evaluation — note this
# means up to 20 API calls per stage, which can burn through Gemini's free
# tier daily quota fast; lower it via env if that's a problem for you.
MAX_TURNS_PER_STAGE = int(os.environ.get("CODEPROOF_GEMINI_MAX_TURNS", "20"))
MAX_TOOL_OUTPUT_CHARS = 8000
MAX_RATE_LIMIT_RETRIES = 5
DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = 20

_READ_ONLY_TOOLS = [
    types.FunctionDeclaration(
        name="list_files",
        description="List files in the repository under a given directory (recursive, excludes .git and node_modules).",
        parameters_json_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory, relative to repo root. Default '.'."}},
        },
    ),
    types.FunctionDeclaration(
        name="read_file",
        description="Read a text file from the repository, relative to its root.",
        parameters_json_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    ),
    types.FunctionDeclaration(
        name="run_command",
        description="Run a shell command inside the isolated sandbox container, with the repository root as the working directory.",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout_seconds": {"type": "integer", "description": "Default 120."},
            },
            "required": ["command"],
        },
    ),
]

_WRITE_TOOL = types.FunctionDeclaration(
    name="write_file",
    description="Create or overwrite a text file in the repository, relative to its root. Creates parent directories as needed.",
    parameters_json_schema={
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
)


class GeminiCodingAgent(CodingAgent):
    def __init__(self, sandbox: Sandbox, model: str = DEFAULT_MODEL):
        super().__init__(name=f"gemini:{model}")
        self.sandbox = sandbox
        self.model = model
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.client = genai.Client(api_key=api_key)
        self.contents: list[types.Content] = []
        self.system_prompt = ""
        self._stage_log: list[str] = []

    # ---- CodingAgent interface -------------------------------------------------

    def initialize(self, issue_title: str, issue_body: str, repo_path: Path) -> None:
        self.system_prompt = (
            "You are a coding agent participating in CodeProof, an independent evaluation "
            "pipeline. You work in stages: inspect the repo, reproduce a reported bug, "
            "propose a minimal fix, then verify it. Only claim something is true if you "
            "actually observed it in a tool result — never guess or assume success."
        )
        self._log("system", self.system_prompt)
        self._log("instruction", f"Issue: {issue_title}\n\n{issue_body}")
        self.contents = [
            types.Content(role="user", parts=[types.Part.from_text(
                text=f"Issue title: {issue_title}\n\nIssue description:\n{issue_body}",
            )]),
            types.Content(role="model", parts=[types.Part.from_text(
                text="Understood. I'll investigate the repository, reproduce the bug, then propose a fix.",
            )]),
        ]

    def inspect_repository(self) -> str:
        prompt = (
            "Investigate this repository well enough to work on the issue above. Use "
            "list_files/read_file/run_command as needed (read-only — do not modify files "
            "yet). When done, reply with a concise plain-text summary (no tool calls): the "
            "repo's language/framework, the files most relevant to the issue, and your "
            "hypothesis about the root cause."
        )
        text = self._agentic_loop(prompt, _READ_ONLY_TOOLS, MAX_TURNS_PER_STAGE)
        return text or "(agent produced no summary)"

    def reproduce_issue(self) -> ReproductionResult:
        prompt = (
            "Now demonstrate that the bug described in the issue actually exists in the "
            "current code. If this repo needs dependencies installed to run anything "
            "(node_modules, a virtualenv, etc.), run that install command first — check "
            "for a package.json / requirements.txt / pyproject.toml if unsure — before "
            "trying to execute code, since nothing will run otherwise. If an install "
            "command times out or fails partway through, delete the partial install "
            "(e.g. `rm -rf node_modules`) before retrying — a half-finished install "
            "directory commonly causes permission/conflict errors on the next attempt, "
            "wasting a retry on a doomed command. Use run_command to "
            "run something that exposes the bug (an existing test, a small script, a "
            "curl/CLI invocation — whatever fits this repo). You may create new small "
            "script files with write_file for this purpose only — do not modify existing "
            "application source files at this stage. When finished, "
            "reply with ONLY a JSON object, no prose and no code fences, of exactly this "
            "form:\n"
            '{"reproduced": true|false, "command": "<the exact command that demonstrates the issue>", '
            '"expected": "<one-line description of correct behavior>", '
            '"observed_summary": "<one or two sentence summary of what actually happened>"}\n'
            "Only set reproduced=true if you actually saw the incorrect behavior in real "
            "command output above — never guess."
        )
        text = self._agentic_loop(prompt, _READ_ONLY_TOOLS + [_WRITE_TOOL], MAX_TURNS_PER_STAGE)
        data = _parse_json_object(text)

        observed = "\n".join(self._stage_log[-3:]) or (data.get("observed_summary", "") if data else "")
        if data is None:
            self._log("note", "Could not parse structured reproduction output from the model; defaulting to not-reproduced.")
            return ReproductionResult(
                reproduced=False,
                command="(unparseable agent output)",
                expected="",
                observed=text[:2000],
                explanation="Agent did not return parseable structured output for reproduction; treating as not reproduced.",
            )

        repro = ReproductionResult(
            reproduced=bool(data.get("reproduced", False)),
            command=str(data.get("command", "")),
            expected=str(data.get("expected", "")),
            observed=observed[:3000],
            explanation=str(data.get("observed_summary", "")),
        )
        self._log("note", repro.explanation, reproduced=repro.reproduced)
        return repro

    def propose_fix(self) -> Patch:
        prompt = (
            "Now implement a minimal fix for the root cause using write_file to edit only "
            "the files necessary. After editing, run `git diff` via run_command to review "
            "your change. When done, reply with ONLY a JSON object, no prose, of the form:\n"
            '{"explanation": "<one or two sentences on what you changed and why>"}'
        )
        text = self._agentic_loop(prompt, _READ_ONLY_TOOLS + [_WRITE_TOOL], MAX_TURNS_PER_STAGE)
        data = _parse_json_object(text)
        explanation = (data or {}).get("explanation") or text[:500] or "(no explanation provided)"

        diff_result = self.sandbox.run("git diff")
        names_result = self.sandbox.run("git diff --name-only")
        diff_text = diff_result.stdout
        files_changed = [f for f in names_result.stdout.splitlines() if f.strip()]
        added = sum(1 for line in diff_text.splitlines() if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in diff_text.splitlines() if line.startswith("-") and not line.startswith("---"))

        patch = Patch(diff=diff_text, files_changed=files_changed, lines_added=added, lines_removed=removed, explanation=explanation)
        self._log("response", f"Proposed patch touching {len(files_changed)} file(s): {explanation}")
        return patch

    def apply_patch(self, patch: Patch) -> None:
        # Edits were already made directly to the sandbox-mounted working copy
        # via write_file during propose_fix(); this just confirms that state
        # against ground truth (`git diff`) rather than re-applying anything.
        current = self.sandbox.run("git diff --stat")
        self._log("command", "git diff --stat (confirming patch state)")
        self._log("tool_result", current.stdout, exit_code=current.exit_code)
        if not patch.files_changed:
            raise RuntimeError("agent produced no file changes during propose_fix")

    def run_tests(self) -> TestRunResult:
        prompt = (
            "Run this repository's existing automated test suite via run_command (detect "
            "the right command by inspecting files like package.json or pyproject.toml if "
            "unsure). When finished, reply with ONLY a JSON object, no prose, of the form:\n"
            '{"passed": <int>, "failed": <int>, "total": <int>}\n'
            "Use the real counts from the test runner's own summary output. If you cannot "
            "determine exact counts, report failed >= 1 rather than claiming a false pass."
        )
        text = self._agentic_loop(prompt, _READ_ONLY_TOOLS, MAX_TURNS_PER_STAGE)
        data = _parse_json_object(text)
        raw_output = "\n".join(self._stage_log)

        if data is None:
            self._log("note", "Could not parse structured test-result output from the model; treating as failed.")
            return TestRunResult(passed=0, failed=1, total=1, raw_output=raw_output or text[:2000])

        return TestRunResult(
            passed=int(data.get("passed", 0)),
            failed=int(data.get("failed", 0)),
            total=int(data.get("total", 0)),
            raw_output=raw_output,
        )

    # ---- internals ---------------------------------------------------------

    def _agentic_loop(self, stage_prompt: str, tools: list[types.FunctionDeclaration], max_turns: int) -> str:
        self._stage_log = []
        self.contents.append(types.Content(role="user", parts=[types.Part.from_text(text=stage_prompt)]))
        tool = types.Tool(function_declarations=tools)

        for _ in range(max_turns):
            response = self._generate_content_with_retry(tool)
            candidate_content = response.candidates[0].content
            self.contents.append(candidate_content)

            for part in candidate_content.parts or []:
                if part.text:
                    self._log("response", part.text)
                elif part.function_call:
                    self._log("tool_call", f"{part.function_call.name}({json.dumps(part.function_call.args)[:300]})")

            function_calls = response.function_calls
            if not function_calls:
                return response.text or ""

            response_parts = []
            for fc in function_calls:
                content, is_error = self._execute_tool(fc.name, fc.args or {})
                self._log("tool_result", content[:1000], exit_code=(1 if is_error else 0))
                resp_dict = {"error": content} if is_error else {"result": content}
                response_parts.append(types.Part.from_function_response(name=fc.name, response=resp_dict))
            self.contents.append(types.Content(role="user", parts=response_parts))

        self._log("note", f"Stage stopped after reaching the {max_turns}-turn limit without a final answer.")
        return ""

    def _generate_content_with_retry(self, tool: types.Tool) -> types.GenerateContentResponse:
        """Retries two distinct transient failure modes rather than letting
        either crash the whole evaluation:
        - 429 (ClientError): the free tier's per-minute quota is tight and
          easy to hit mid-agentic-loop. Retried with the server-suggested
          delay, except a *daily* quota violation (retrying can't help that).
        - 503 (ServerError): "model overloaded", a transient capacity issue
          on Google's side, unrelated to our quota. Retried with a fixed
          backoff since there's no server-suggested delay for this one."""
        config = types.GenerateContentConfig(
            system_instruction=self.system_prompt,
            tools=[tool],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        for attempt in range(MAX_RATE_LIMIT_RETRIES):
            try:
                return self.client.models.generate_content(model=self.model, contents=self.contents, config=config)
            except errors.ClientError as exc:
                if exc.code != 429 or attempt == MAX_RATE_LIMIT_RETRIES - 1:
                    raise
                if _is_daily_quota_exhausted(exc):
                    # Retrying won't help — the quota resets on a ~24h clock,
                    # not on the server's (often meaningless, e.g. "0s")
                    # per-request retryDelay hint. Fail fast instead of
                    # burning the rest of the retry budget pointlessly.
                    raise
                delay = _extract_retry_delay_seconds(exc) or DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
                self._log("note", f"Gemini rate-limited (429); retrying in {delay:.0f}s (attempt {attempt + 1}/{MAX_RATE_LIMIT_RETRIES}).")
                time.sleep(delay)
            except errors.ServerError as exc:
                if exc.code != 503 or attempt == MAX_RATE_LIMIT_RETRIES - 1:
                    raise
                delay = DEFAULT_RATE_LIMIT_BACKOFF_SECONDS * (attempt + 1)
                self._log("note", f"Gemini overloaded (503); retrying in {delay:.0f}s (attempt {attempt + 1}/{MAX_RATE_LIMIT_RETRIES}).")
                time.sleep(delay)
        raise RuntimeError("unreachable")

    def _execute_tool(self, name: str, tool_input: dict) -> tuple[str, bool]:
        try:
            if name == "list_files":
                files = self.sandbox.list_files(tool_input.get("path", "."))
                return "\n".join(files), False
            if name == "read_file":
                return self.sandbox.read_file(tool_input["path"]), False
            if name == "write_file":
                self.sandbox.write_file(tool_input["path"], tool_input["content"])
                return f"wrote {tool_input['path']}", False
            if name == "run_command":
                result = self.sandbox.run(
                    tool_input["command"], timeout=int(tool_input.get("timeout_seconds", 120)),
                )
                output = f"$ {tool_input['command']}\nexit={result.exit_code}\n{result.stdout}{result.stderr}"
                output = output[:MAX_TOOL_OUTPUT_CHARS]
                self._stage_log.append(output)
                return output, result.exit_code != 0
            return f"unknown tool: {name}", True
        except SandboxError as exc:
            return f"error: {exc}", True


def _is_daily_quota_exhausted(exc: "errors.ClientError") -> bool:
    try:
        details = exc.details.get("error", {}).get("details", [])
        for d in details:
            if d.get("@type", "").endswith("QuotaFailure"):
                for v in d.get("violations", []):
                    if "PerDay" in v.get("quotaId", ""):
                        return True
    except (AttributeError, TypeError):
        pass
    return False


def _extract_retry_delay_seconds(exc: "errors.ClientError") -> float | None:
    try:
        details = exc.details.get("error", {}).get("details", [])
        for d in details:
            if d.get("@type", "").endswith("RetryInfo"):
                delay_str = d.get("retryDelay", "")  # e.g. "18s"
                if delay_str.endswith("s"):
                    return float(delay_str[:-1])
    except (AttributeError, TypeError, ValueError):
        pass
    return None


def _parse_json_object(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None
