"""Structured, read-only git operations. Deterministic; no commits, no pushes."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _default_root() -> Path:
    env = os.environ.get("REPO_ROOT")
    if env and os.path.isdir(env):
        return Path(env)
    return Path(__file__).resolve().parent.parent


def run_git(root: str | None, *args: str, timeout: int = 30) -> str:
    cwd = Path(root) if root else _default_root()
    try:
        proc = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise RuntimeError("git is not installed or not on PATH") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()[:400]}")
    return proc.stdout


def branch(root: str | None = None) -> str:
    return run_git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()


def status(root: str | None = None) -> dict:
    out = run_git(root, "status", "--porcelain=v2", "--branch").strip()
    lines = out.splitlines()
    branch_line = next((l for l in lines if l.startswith("# branch.head")), "# branch.head ")
    ahead_line = next((l for l in lines if l.startswith("# branch.ab")), "# branch.ab +0 -0")
    return {
        "branch": branch_line.split(" ", 2)[2] if len(branch_line.split()) > 2 else "?",
        "ahead": ahead_line.split()[2] if len(ahead_line.split()) > 2 else "+0",
        "behind": ahead_line.split()[3] if len(ahead_line.split()) > 3 else "-0",
        "changed": [
            {"path": l.split()[1], "xy": l.split()[0]} for l in lines if not l.startswith("#")
        ],
    }


def changed_files(root: str | None = None) -> list[str]:
    out = run_git(root, "status", "--porcelain").strip()
    return [l[3:] for l in out.splitlines() if l.strip()]


def log(root: str | None = None, n: int = 15) -> list[dict]:
    out = run_git(root, "log", f"-{n}", "--pretty=%h%x1f%an%x1f%s%x1f%ad", "--date=short")
    commits = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            commits.append({"hash": parts[0], "author": parts[1], "subject": parts[2], "date": parts[3]})
    return commits


def diff(root: str | None = None, base: str | None = None, stat: bool = True) -> dict:
    args = []
    if base:
        args = [base, "--"]
    else:
        args = ["HEAD", "--"]
    if stat:
        body = run_git(root, "diff", *args)
        names = run_git(root, "diff", "--name-only", *(args if base else ["HEAD", "--"]))
        return {
            "base": base or "working tree vs HEAD",
            "files_changed": len([l for l in names.splitlines() if l.strip()]),
            "names": [l for l in names.splitlines() if l.strip()],
            "diff": body[:20000],
        }
    return {"diff": run_git(root, "diff", *args)}