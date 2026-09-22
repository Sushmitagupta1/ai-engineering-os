"""Shared dispatch to opencode free Zen workers.

Used by freeworker MCP server and repoindex summarizer. Subprocess runners always set
stdin=DEVNULL: inheriting the MCP server's open stdin pipe makes `opencode run` block.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache


@lru_cache(maxsize=1)
def opencode_binary() -> str:
    path = shutil.which("opencode")
    if not path:
        raise RuntimeError(
            "'opencode' not found on PATH. Install it from https://opencode.ai/install"
        )
    return path


def run_opencode(model: str, prompt: str, cwd: str | None, timeout: int) -> str:
    cmd = [opencode_binary(), "run", "-m", model, "--dir", cwd or os.getcwd()]
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"worker timed out after {timeout}s ({model})")
    if proc.returncode != 0:
        raise RuntimeError(
            f"worker failed ({model}) rc={proc.returncode}: {proc.stderr[-2000:]}"
        )
    return proc.stdout.strip()