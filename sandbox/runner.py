"""Sandbox runner — executes test commands in isolation.

Backends:
  docker — `docker run --rm` mounting the workdir read-write (best, if Docker installed)
  local  — fallback: same semantics but the copy stays on the host (containment via disposable
           repo copy, not OS isolation). Selected automatically.

The M4 guarantee: the *workdir is a disposable copy* of the repo, so mutations never touch
the real repo regardless of backend.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field

DEFAULT_IMAGE = "python:3.12-slim"


def available() -> bool:
    return shutil.which("docker") is not None


def backend() -> str:
    return "docker" if available() else "local"


@dataclass
class SandboxResult:
    backend: str
    returncode: int
    stdout: str
    stderr: str
    duration: float
    timed_out: bool = False
    raw: dict = field(default_factory=dict)

    def ok(self) -> bool:
        return self.returncode == 0


def _run(argv: list[str], cwd: str, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


def run_pytest(
    workdir: str,
    pytest_args: list[str] | None = None,
    timeout: int = 600,
    image: str = DEFAULT_IMAGE,
    run_id: str = "run",
) -> SandboxResult:
    """Run pytest against `workdir` inside the sandbox (docker or local fallback)."""
    args = pytest_args or []
    start = time.time()
    be = backend()
    timed_out = False
    try:
        if be == "docker":
            bail = f"python -m pip install -q --disable-pip-version-check pytest || true"
            test = f"python -m pytest {shutil_args(args)}"
            cmd = ["docker", "run", "--rm", "-v", f"{workdir}:/work", "-w", "/work",
                   image, "sh", "-lc", f"{bail} && {test}"]
            proc = _run(cmd, workdir, timeout)
        else:  # local fallback
            proc = _run([sys.executable, "-m", "pytest", *args], workdir, timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc = None
        try:
            result = subprocess.run(["timeout", "1", "true"], capture_output=True)
        except Exception:  # noqa: BLE001
            result = None
        duration = timeout
        return SandboxResult(be, -1, "", f"timed out after {timeout}s", duration, True)

    duration = round(time.time() - start, 2)
    return SandboxResult(
        backend=be,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        duration=duration,
        raw={"run_id": run_id, "args": args},
    )


def shutil_args(args: list[str]) -> str:
    import shlex
    return " ".join(shlex.quote(a) for a in args)


def copy_repo(src: str, dst: str) -> None:
    """Copy a repo into a disposable sandbox dir, skipping junk dirs."""
    ignore = shutil.ignore_patterns(
        ".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules",
        ".os", "dist", "build", "pgdata", ".idea", ".vscode", "*.pyc",
    )
    shutil.copytree(src, dst, ignore=ignore)