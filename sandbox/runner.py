"""
Docker-based sandbox for executing untrusted repository code.

Design constraints (see docs/ARCHITECTURE.md):
- Never run evaluated repo code on the host.
- No host credentials/secrets are passed into the container.
- Resource limits (memory, CPU, pids) and a hard wall-clock timeout on every command.
- Network is enabled by default so dependency installs can reach a package
  registry (see Sandbox.start() / lock_down_network() below for why and how
  to disable it once setup is done).
- Every command run and its output is captured for the evidence trail.
"""
from __future__ import annotations

import dataclasses
import shlex
import subprocess
import time
import uuid
from pathlib import Path

IMAGE_NAME = "codeproof-sandbox:latest"
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_MEMORY = "2g"
DEFAULT_CPUS = "2"
DEFAULT_PIDS_LIMIT = "256"

# Persistent, shared package-manager caches (npm's download cache, pip's
# wheel cache — NOT a per-repo node_modules snapshot, which is what caused
# the corrupted-partial-install failures we saw). Reused across every
# evaluation regardless of which repo, so a second run of any repo that
# shares a dependency never re-downloads it.
CACHE_ROOT = Path.home() / ".codeproof_cache"
NPM_CACHE_DIR = CACHE_ROOT / "npm"
PIP_CACHE_DIR = CACHE_ROOT / "pip"

# subprocess.run(..., text=True, encoding="utf-8", errors="replace") decodes with the OS's default encoding
# (cp1252 on Windows) unless told otherwise, which raises UnicodeDecodeError
# on the first non-ASCII byte a subprocess writes (observed from pip/npm
# output). Every text-mode subprocess.run call below explicitly passes
# encoding="utf-8", errors="replace" so any command's output decodes
# permissively instead of crashing the evaluation over a single stray byte.


@dataclasses.dataclass
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool


class SandboxError(RuntimeError):
    pass


class Sandbox:
    """
    One Sandbox instance == one running, isolated container bound to a single
    evaluation's working copy of a repository. Callers clone the repo on the
    host into a temp dir, then `start()` mounts it read-write into the
    container at /workspace and runs commands via `docker exec`.
    """

    def __init__(self, host_repo_path: Path, evaluation_id: str | None = None):
        self.host_repo_path = Path(host_repo_path).resolve()
        self.evaluation_id = evaluation_id or str(uuid.uuid4())[:8]
        self.container_name = f"codeproof-eval-{self.evaluation_id}"
        self._started = False

    def start(self) -> None:
        """
        Network is enabled by default (see lock_down_network()) so that a
        repo's dependency install step (`pip install`, `npm ci`, ...) can
        actually reach a package registry — with --network none nothing
        with third-party dependencies could ever be evaluated. Every other
        isolation layer (no host credentials, dropped capabilities,
        no-new-privileges, memory/CPU/pids limits, non-root user) is applied
        regardless. Call lock_down_network() once dependencies are installed
        and before running untrusted reproduction/test code, for evaluations
        where the repo's full dependency list is known upfront.
        """
        if self._started:
            return
        NPM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        PIP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cmd = [
            "docker", "run", "-d",
            "--name", self.container_name,
            "--memory", DEFAULT_MEMORY,
            "--cpus", DEFAULT_CPUS,
            "--pids-limit", DEFAULT_PIDS_LIMIT,
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
            "-v", f"{self.host_repo_path}:/workspace:rw",
            "-v", f"{NPM_CACHE_DIR}:/cache/npm:rw",
            "-v", f"{PIP_CACHE_DIR}:/cache/pip:rw",
            IMAGE_NAME,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise SandboxError(f"failed to start sandbox container: {proc.stderr.strip()}")
        self._started = True

    def _resolve_in_repo(self, relative_path: str) -> Path:
        """Resolve a repo-relative path and refuse anything that escapes the
        mounted working copy (defense against a malicious/careless agent
        passing '../../etc/passwd'-style paths as a tool argument)."""
        candidate = (self.host_repo_path / relative_path).resolve()
        if not str(candidate).startswith(str(self.host_repo_path)):
            raise SandboxError(f"path escapes repository working copy: {relative_path!r}")
        return candidate

    def list_files(self, relative_dir: str = ".", max_entries: int = 500) -> list[str]:
        """List files under the repo working copy, host-side (no docker exec
        needed — the container sees the same bind-mounted files)."""
        base = self._resolve_in_repo(relative_dir)
        entries: list[str] = []
        for path in sorted(base.rglob("*")):
            if ".git" in path.parts or "node_modules" in path.parts:
                continue
            if path.is_file():
                entries.append(str(path.relative_to(self.host_repo_path)).replace("\\", "/"))
            if len(entries) >= max_entries:
                break
        return entries

    def read_file(self, relative_path: str, max_bytes: int = 50_000) -> str:
        path = self._resolve_in_repo(relative_path)
        if not path.is_file():
            raise SandboxError(f"not a file: {relative_path!r}")
        data = path.read_bytes()[:max_bytes]
        return data.decode("utf-8", errors="replace")

    def write_file(self, relative_path: str, content: str) -> None:
        path = self._resolve_in_repo(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # newline="" disables Python's OS-based newline translation (on
        # Windows, text-mode write silently turns every \n into \r\n) — for
        # a diff/patch written here and then git-applied against a Linux
        # container's checkout, that silent rewrite is exactly the kind of
        # byte-for-byte mismatch `git apply` rejects. Write exactly what was
        # given.
        path.write_text(content, encoding="utf-8", newline="")

    def lock_down_network(self) -> None:
        """Disconnect the container from the network. Call this after any
        dependency-install step, before running untrusted repo code, in
        flows where no further network access is needed."""
        if not self._started:
            raise SandboxError("sandbox not started; call start() first")
        subprocess.run(
            ["docker", "network", "disconnect", "bridge", self.container_name],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )

    def run(self, command: str, timeout: int = DEFAULT_TIMEOUT_SECONDS, workdir: str = "/workspace") -> CommandResult:
        if not self._started:
            raise SandboxError("sandbox not started; call start() first")

        exec_cmd = [
            "docker", "exec", "-w", workdir, self.container_name,
            "bash", "-lc", command,
        ]
        start = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(
                exec_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
            )
            exit_code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as e:
            timed_out = True
            exit_code = -1
            stdout = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            stderr = (e.stderr or b"").decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
            stderr += "\n[codeproof] command timed out and was killed"
        duration = time.monotonic() - start

        return CommandResult(
            command=command,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=round(duration, 3),
            timed_out=timed_out,
        )

    def stop(self) -> None:
        if not self._started:
            return
        subprocess.run(["docker", "rm", "-f", self.container_name], capture_output=True, text=True, encoding="utf-8", errors="replace")
        self._started = False

    def __enter__(self) -> "Sandbox":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()


def build_image(dockerfile_dir: Path | None = None) -> CommandResult:
    """Build the sandbox image once (idempotent, cached by docker)."""
    dockerfile_dir = dockerfile_dir or Path(__file__).parent
    start = time.monotonic()
    proc = subprocess.run(
        ["docker", "build", "-t", IMAGE_NAME, str(dockerfile_dir)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return CommandResult(
        command="docker build",
        exit_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        duration_seconds=round(time.monotonic() - start, 3),
        timed_out=False,
    )


def clone_repo(repo_url: str, dest_dir: Path, commit_sha: str | None = None) -> CommandResult:
    """Clone happens on the HOST (needs network + possibly a GitHub token),
    never inside the sandbox. The sandbox only ever sees the resulting
    working copy, mounted read-write, with no credentials attached."""
    start = time.monotonic()
    proc = subprocess.run(
        # core.autocrlf=false: don't let git silently rewrite line endings
        # on checkout. On a machine with autocrlf=true (common on Windows),
        # a checked-out file's line endings depend on checkout history in a
        # way that made an agent-written patch match by accident in one
        # code path and fail to apply in another (same file, same patch
        # content) — keep the working tree byte-identical to what's stored.
        ["git", "-c", "core.autocrlf=false", "clone", "--quiet", repo_url, str(dest_dir)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode == 0 and commit_sha:
        checkout = subprocess.run(
            ["git", "-C", str(dest_dir), "checkout", "--quiet", commit_sha],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        proc_stdout = proc.stdout + checkout.stdout
        proc_stderr = proc.stderr + checkout.stderr
        exit_code = checkout.returncode
    else:
        proc_stdout, proc_stderr, exit_code = proc.stdout, proc.stderr, proc.returncode

    return CommandResult(
        command=f"git clone {repo_url} @ {commit_sha or 'HEAD'}",
        exit_code=exit_code,
        stdout=proc_stdout,
        stderr=proc_stderr,
        duration_seconds=round(time.monotonic() - start, 3),
        timed_out=False,
    )
