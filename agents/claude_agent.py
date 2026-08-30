"""
Live CodingAgent adapter backed by the Anthropic API (Claude), using a
manual tool-use loop (list_files / read_file / write_file / run_command)
against the sandbox. Unlike agents/mock.py, this adapter actually reasons
about whatever repository it's given — it has no scripted playbook.

Every claim this agent hands back to evaluator/pipeline.py (reproduced?,
tests passed?) comes from a final structured-JSON turn the model produces
after it has actually run commands in the sandbox — never from unverified
prose. If the model doesn't return parseable structured output, this agent
defaults to the conservative outcome (not reproduced / tests failed) rather
than quietly reporting success.
"""
from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from agents.base import CodingAgent, Patch, ReproductionResult, TestRunResult
from sandbox.runner import Sandbox, SandboxError

load_dotenv()

DEFAULT_MODEL = os.environ.get("CODEPROOF_AGENT_MODEL", "claude-opus-5")
MAX_TOKENS_PER_TURN = 4096
# 8 was enough for small fixture repos but left a real Next.js/TypeScript
# codebase (dozens of files) stuck mid-exploration with no summary/answer
# produced yet. Raised after observing that on a real evaluation.
MAX_TURNS_PER_STAGE = int(os.environ.get("CODEPROOF_CLAUDE_MAX_TURNS", "20"))
MAX_TOOL_OUTPUT_CHARS = 8000

_READ_ONLY_TOOLS = [
    {
        "name": "list_files",
        "description": "List files in the repository under a given directory (recursive, excludes .git and node_modules).",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory, relative to repo root. Default '.'."}},
        },
    },
    {
        "name": "read_file",
        "description": "Read a text file from the repository, relative to its root.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "run_command",
        "description": "Run a shell command inside the isolated sandbox container, with the repository root as the working directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout_seconds": {"type": "integer", "description": "Default 120."},
            },
            "required": ["command"],
        },
    },
]

_WRITE_TOOL = {
    "name": "write_file",
    "description": "Create or overwrite a text file in the repository, relative to its root. Creates parent directories as needed.",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
}


class ClaudeCodingAgent(CodingAgent):
    def __init__(self, sandbox: Sandbox, model: str = DEFAULT_MODEL):
        super().__init__(name=f"claude:{model}")
        self.sandbox = sandbox
        self.model = model
        # The SDK only auto-attaches `anthropic-workspace-id` when using its
        # OAuth/profile credential chain — not for a plain ANTHROPIC_API_KEY
        # (our case), so an identity-linked key needs it passed explicitly.
        workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID")
        headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self.client = anthropic.Anthropic(default_headers=headers)
        self.messages: list[dict] = []
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
        self.messages = [{
            "role": "user",
            "content": f"Issue title: {issue_title}\n\nIssue description:\n{issue_body}",
        }]
        self.messages.append({
            "role": "assistant",
            "content": "Understood. I'll investigate the repository, reproduce the bug, then propose a fix.",
        })

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

    def _agentic_loop(self, stage_prompt: str, tools: list[dict], max_turns: int) -> str:
        self._stage_log = []
        self.messages.append({"role": "user", "content": stage_prompt})

        for _ in range(max_turns):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS_PER_TURN,
                system=self.system_prompt,
                tools=tools,
                messages=self.messages,
            )
            self.messages.append({"role": "assistant", "content": response.content})

            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            for b in response.content:
                if b.type == "text" and b.text.strip():
                    self._log("response", b.text)
                elif b.type == "tool_use":
                    self._log("tool_call", f"{b.name}({json.dumps(b.input)[:300]})")

            if not tool_use_blocks:
                return "".join(b.text for b in response.content if b.type == "text")

            tool_results = []
            for block in tool_use_blocks:
                content, is_error = self._execute_tool(block.name, block.input)
                self._log("tool_result", content[:1000], exit_code=(1 if is_error else 0))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                    "is_error": is_error,
                })
            self.messages.append({"role": "user", "content": tool_results})

        self._log("note", f"Stage stopped after reaching the {max_turns}-turn limit without a final answer.")
        return ""

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
