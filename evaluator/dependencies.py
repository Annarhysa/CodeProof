"""
Deterministic dependency installation, run once by the pipeline before the
agent ever touches the repo — not left to the agent to figure out.

This exists because every real failure we saw on a real (non-fixture) repo
traced back to this step: an agent forgetting to install dependencies,
picking the wrong install command, or retrying after a timeout without
cleaning up first and hitting a corrupted partial install. None of that is
an interesting thing for an agent to reason about — it's plumbing, and
plumbing should be deterministic.

Uses the sandbox's persistent, shared package-manager caches (npm's
download cache, pip's wheel cache — see sandbox/runner.py) so repeat runs,
even across different repos, don't re-download shared dependencies.
"""
from __future__ import annotations

import dataclasses

from sandbox.runner import CommandResult, Sandbox

INSTALL_TIMEOUT_SECONDS = 600


@dataclasses.dataclass
class DependencyInstallResult:
    attempted: bool
    detected: list[str]
    commands: list[CommandResult]
    success: bool
    summary: str


def install_dependencies(sandbox: Sandbox) -> DependencyInstallResult:
    files = set(sandbox.list_files(".", max_entries=2000))
    detected: list[str] = []
    commands: list[CommandResult] = []
    manifest_ok: list[bool] = []  # one entry per manifest actually installed, final outcome only

    if "package.json" in files:
        detected.append("npm (package.json)")
        install_cmd = (
            "npm ci --cache /cache/npm --no-audit --no-fund"
            if "package-lock.json" in files
            else "npm install --cache /cache/npm --no-audit --no-fund"
        )
        result = sandbox.run(install_cmd, timeout=INSTALL_TIMEOUT_SECONDS)
        commands.append(result)
        final = result
        if result.exit_code != 0:
            # A killed/failed install can leave node_modules half-written,
            # which reliably breaks the next attempt with permission/
            # conflict errors (observed firsthand) — clean up before retrying
            # once, rather than compounding the failure.
            cleanup = sandbox.run("rm -rf node_modules", timeout=60)
            commands.append(cleanup)
            retry = sandbox.run("npm install --cache /cache/npm --no-audit --no-fund", timeout=INSTALL_TIMEOUT_SECONDS)
            commands.append(retry)
            final = retry
        manifest_ok.append(final.exit_code == 0)

    if "requirements.txt" in files:
        detected.append("pip (requirements.txt)")
        result = sandbox.run("pip install --cache-dir /cache/pip -r requirements.txt", timeout=INSTALL_TIMEOUT_SECONDS)
        commands.append(result)
        manifest_ok.append(result.exit_code == 0)

    if "pyproject.toml" in files and "requirements.txt" not in files:
        detected.append("pip (pyproject.toml)")
        result = sandbox.run("pip install --cache-dir /cache/pip -e . || pip install --cache-dir /cache/pip .", timeout=INSTALL_TIMEOUT_SECONDS)
        commands.append(result)
        manifest_ok.append(result.exit_code == 0)

    for marker, label in [("Gemfile", "bundler"), ("go.mod", "go modules"), ("Cargo.toml", "cargo")]:
        if marker in files:
            detected.append(f"{label} ({marker}) — detected but not auto-installed yet")

    if not detected:
        return DependencyInstallResult(
            attempted=False, detected=[], commands=[], success=True,
            summary="No recognized dependency manifest found; nothing to install.",
        )

    success = all(manifest_ok) if manifest_ok else True

    return DependencyInstallResult(
        attempted=True,
        detected=detected,
        commands=commands,
        success=success,
        summary=f"Detected: {', '.join(detected)}. " + ("All installs succeeded." if success else "One or more installs failed — see command output."),
    )


def format_evidence(result: DependencyInstallResult) -> str:
    if not result.attempted:
        return result.summary
    parts = [result.summary, ""]
    for c in result.commands:
        parts.append(f"$ {c.command}\nexit={c.exit_code}\n{c.stdout[-1500:]}{c.stderr[-1500:]}")
    return "\n\n".join(parts)
