"""freeworker MCP control plane.

Bridges Claude Code to free opencode Zen models via `opencode run`.
Tools: free_run (generic bulk task), free_summarize, free_scaffold, list_free_models.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP

from freeworker.dispatch import run_opencode

mcp = FastMCP("freeworker")

DEFAULT_TIMEOUT = 600  # seconds

FREE_MODELS = [
    "opencode/big-pickle",
    "opencode/ox-alpha-free",
    "opencode/mimo-v2.5-free",
    "opencode/nemotron-3-ultra-free",
    "opencode/nemotron-3.5-lightning-free",
    "opencode/hy3-free",
    "opencode/ling-3.0-flash-fin-free",
]


def _prompt_user(prompt: str) -> str:
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("prompt must not be empty")
    return prompt


@mcp.tool()
def list_free_models() -> list[str]:
    """List free opencode model ids the control plane can dispatch to."""
    return FREE_MODELS


@mcp.tool()
def free_run(
    prompt: str,
    cwd: str | None = None,
    model: str = "opencode/big-pickle",
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Run a bulk/mechanical task on a free opencode Zen model and return its text output.

    Use for: repo-wide search + summarise, issue triage, chunking large files, drafting
    boilerplate or a first-pass implementation you expect Claude to verify afterwards.
    NEVER send secrets. Treat read-only for M0-M2.
    """
    return run_opencode(model, _prompt_user(prompt), cwd, timeout)


@mcp.tool()
def free_summarize(
    file_path: str,
    focus: str = "what this file does, key symbols, and anything surprising",
    model: str = "opencode/big-pickle",
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Summarise a single file on disk with a free worker (reads it via ripgrep inside the worker). Keeps Claude's context small."""
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"file not found: {file_path}")
    prompt = (
        f"Read the file at {file_path!r}. Focus: {focus}. "
        "Return a terse structured summary (purpose, key symbols with line numbers, risks)."
    )
    return run_opencode(model, prompt, os.path.dirname(file_path) or None, timeout)


@mcp.tool()
def free_scaffold(
    prompt: str,
    project_dir: str,
    model: str = "opencode/big-pickle",
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Ask a free worker to emit boilerplate scaffold (config, CI, stubs) into project_dir. The worker writes files — still read-only stamped for M0; verify output on this side."""
    if not os.path.isdir(project_dir):
        raise NotADirectoryError(f"project_dir not found: {project_dir}")
    wrapped = (
        f"Scaffold per this request. You MAY create new files under {project_dir!r}, "
        "but must not modify existing files or delete anything. "
        f"Request: {prompt}\n"
        "Afterwards list every file you created with a one-line purpose."
    )
    return run_opencode(model, wrapped, project_dir, timeout)


if __name__ == "__main__":
    if sys.version_info < (3, 11):
        sys.exit("freeworker requires Python 3.11+")
    mcp.run(transport="stdio")