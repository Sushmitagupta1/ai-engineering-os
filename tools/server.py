"""toolbox MCP server — deterministic tools for Claude Code (M2).

Call graph lookup, relevant-file discovery, context packing, structured git reads.
Read-only by design. Registered in .mcp.json.
"""

from __future__ import annotations

import os
import sys
from functools import wraps
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP

from tools import codelens, diffpatch, gitops, packer, relevant
from tools import looper, testloop
from tools.plan import PlanStore
from sandbox.runner import backend as _sandbox_backend

mcp = FastMCP("toolbox")


class ToolError(Exception):
    pass


def _guard(fn):
    @wraps(fn)
    def wrap(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(str(exc)) from exc
    return wrap


def _root() -> str:
    env = os.environ.get("REPO_ROOT")
    return env if env and os.path.isdir(env) else str(Path(__file__).resolve().parent.parent)


# ---- codelens ----
@mcp.tool()
@_guard
def toolbox_callers(symbol: str, limit: int = 100, root: str | None = None) -> list[dict]:
    """Find every call site of a symbol/function across the repo. Returns file, line, and the enclosing function."""
    return codelens.callers(symbol, root=root or _root(), limit=limit)


@mcp.tool()
@_guard
def toolbox_references(symbol: str, limit: int = 200, root: str | None = None) -> list[dict]:
    """Definitions + call sites of a symbol. Each entry: kind, file, line."""
    return codelens.references(symbol, root=root or _root(), limit=limit)


@mcp.tool()
@_guard
def toolbox_callees(symbol: str, limit: int = 100, root: str | None = None) -> list[dict]:
    """Distinct functions a symbol calls internally, with first call line."""
    return codelens.callees(symbol, root=root or _root(), limit=limit)


# ---- relevant files ----
@mcp.tool()
@_guard
def toolbox_relevant_files(query: str, topk: int = 8, root: str | None = None) -> list[dict]:
    """Score-indexed files by how relevant they are to a natural-language query/issue. Uses symbol names, paths, and free-model chunk summaries."""
    return relevant.relevant_files(query, root=root or _root(), topk=topk)


# ---- packer ----
@mcp.tool()
@_guard
def toolbox_pack_context(
    paths: list[str],
    focus_symbols: list[str] | None = None,
    max_lines: int = 300,
    include_symbol_table: bool = True,
    root: str | None = None,
) -> dict:
    """Pack selected files (relative to repo root, or full paths) into one sanitized, bounded context block with symbols. Use for worker prompts."""
    root_path = root or _root()
    cleaned = []
    for p in paths:
        if os.path.isabs(p):
            try:
                cleaned.append(str(Path(p).relative_to(root_path)).replace("\\", "/"))
            except ValueError:
                cleaned.append(p)
        else:
            cleaned.append(p.replace("\\", "/"))
    return packer.pack(
        cleaned, root=root_path, focus_symbols=focus_symbols,
        max_lines=max_lines, include_symbol_table=include_symbol_table,
    )


# ---- git ----
@mcp.tool()
@_guard
def toolbox_git_branch(root: str | None = None) -> str:
    """Current git branch name."""
    return gitops.branch(root or _root())


@mcp.tool()
@_guard
def toolbox_git_status(root: str | None = None) -> dict:
    """Git status: branch, ahead/behind, changed files with XY codes."""
    return gitops.status(root or _root())


@mcp.tool()
@_guard
def toolbox_git_log(n: int = 15, root: str | None = None) -> list[dict]:
    """Recent commit list: hash, author, subject, date."""
    return gitops.log(root or _root(), n=n)


@mcp.tool()
@_guard
def toolbox_git_diff(base: str | None = None, root: str | None = None) -> dict:
    """Diff (base or working tree vs HEAD): changed file names + diff text."""
    return gitops.diff(root or _root(), base=base)


# ---- M3 plan ledger ----
def _plans_dir() -> Path:
    env = os.environ.get("PLANS_DIR")
    if env:
        return Path(env)
    return Path(_root()) / ".os" / "plans"


@mcp.tool()
@_guard
def toolbox_plan_create(title: str, goal: str) -> dict:
    """Create a new plan (M3 loop). Returns the plan directory path and empty task list."""
    store = PlanStore.create(title, goal, _plans_dir())
    return {"plan_dir": str(store.dir), **store.to_dict()}


@mcp.tool()
@_guard
def toolbox_plan_add_task(
    plan_dir: str,
    description: str,
    tier: str = "claude",
    dedo: str = "",
    depends_on: list[str] | None = None,
    target_files: list[str] | None = None,
    action: str = "",
    task_id: str | None = None,
) -> dict:
    """Add a task to a plan. tier: claude/sonnet (judgment - Claude does it), free (auto free-model), toolbox (auto deterministic). Returns added task."""
    store = PlanStore(plan_dir)
    t = store.add_task(
        description=description, tier=tier, dedo=dedo, depends_on=depends_on,
        target_files=target_files, action=action, task_id=task_id,
    )
    return t.to_dict()


@mcp.tool()
@_guard
def toolbox_plan_tasks(plan_dir: str) -> dict:
    """List all tasks of a plan with their status."""
    store = PlanStore(plan_dir)
    tasks = [t.to_dict() for t in store.tasks()]
    return {"plan_id": store.plan_id, "status": store.to_dict().get("status"), "tasks": tasks}


@mcp.tool()
@_guard
def toolbox_plan_run(
    plan_dir: str,
    model: str = "opencode/big-pickle",
    max_free: int = 10,
    repo_root: str | None = None,
) -> dict:
    """Run the autonomous tiers of a plan: free + toolbox tasks execute now; claude/sonnet tasks become 'assigned' for you to do. Call repeatedly after each Claude task."""
    return looper.run_plan(plan_dir, model=model, max_free=max_free, repo_root=repo_root or _root())


@mcp.tool()
@_guard
def toolbox_plan_advance_task(
    plan_dir: str, task_id: str, status: str,
    notes: str = "", result: str = "",
) -> dict:
    """Mark a task done/failed/blocked after you (Claude) implemented it. Then call toolbox_plan_run again."""
    store = PlanStore(plan_dir)
    t = store.advance(task_id, status, notes=notes, result=result)
    return t.to_dict()


# ---- M4 sandbox + test loop ----
@mcp.tool()
@_guard
def toolbox_sandbox_status() -> dict:
    """Sandbox backend in use: 'docker' (isolated container) or 'local' (disposable repo copy fallback)."""
    return {"backend": _sandbox_backend()}


@mcp.tool()
@_guard
def toolbox_test_loop(
    repo_root: str,
    model: str = "opencode/big-pickle",
    max_iterations: int = 3,
    dry_run: bool = False,
) -> dict:
    """Run the M4 test loop: copy repo into a sandbox, run tests, and if they fail dispatch a free worker to fix the copy, then retest. All mutations happen in the disposable copy - the real repo is untouched. Returns run history + whether green. dry_run=True runs tests only (no fix attempt)."""
    if dry_run:
        res, _ = testloop.run_tests(repo_root)
        return {"green": res.green(), "report": res.to_dict()}
    return testloop.run_test_loop(repo_root, model=model, max_iterations=max_iterations)


# ---- M5 reviewer bridge: diff + safe apply ----
@mcp.tool()
@_guard
def toolbox_sandbox_diff(copy_dir: str, repo_root: str | None = None) -> dict:
    """Diff the sandbox copy against the real tree: per-file unified diffs + classify added/modified/deleted. Feed this to the reviewer subagent."""
    return diffpatch.make_patch(repo_root or _root(), copy_dir)


@mcp.tool()
@_guard
def toolbox_sandbox_apply(
    copy_dir: str,
    repo_root: str | None = None,
    files: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """After reviewer APPROVES toolbox_sandbox_diff: apply the copy's changes to the real tree (whole-file copy, backups to .os/backups/, rollback on failure). files=None applies all. Use dry_run=true to preview the action list first."""
    return diffpatch.apply_copy_to_original(
        repo_root or _root(), copy_dir, files=files, dry_run=dry_run,
    )


# ---- M6 eval harness ----
@mcp.tool()
@_guard
def toolbox_eval_run(suite_root: str) -> dict:
    """Run the M6 eval suite: every case repo under suite_root (each with case.json + failing tests) goes through the full M4 loop -> M5 apply pipeline, then a metrics record is written per case. Returns per-case verdicts + aggregate."""
    from tools import eval as evalmod
    return evalmod.run_suite(suite_root)


@mcp.tool()
@_guard
def toolbox_metrics_report(limit: int = 200) -> dict:
    """Aggregate eval metrics ledger: pass_rate (SKIPs excluded), total cost, worker seconds, latest runs."""
    from tools import metrics
    return metrics.report(limit=limit)


# ---- M7 memory + autopilot ----
@mcp.tool()
@_guard
def toolbox_memory_add(kind: str, text: str, tags: list[str] | None = None) -> dict:
    """Persist a durable memory row. kind: decision/fact/lesson/state. Use for anything future sessions must know."""
    from tools import memory
    if kind not in memory.KINDS:
        raise ToolError(f"kind must be one of {sorted(memory.KINDS)}")
    return memory.add(kind, text, tags)


@mcp.tool()
@_guard
def toolbox_memory_recall(query: str = "", kind: str | None = None, limit: int = 10) -> list[dict]:
    """Recall past memory rows by word-match (recency tiebreak). kind: decision/fact/lesson/state."""
    from tools import memory
    return memory.recall(kind, query, limit)


@mcp.tool()
@_guard
def toolbox_session_primer() -> dict:
    """Call at session start: last decision, recent lessons, open plans, latest eval summary."""
    from tools import memory
    return memory.session_primer(_root())


@mcp.tool()
@_guard
def toolbox_autopilot(
    repo_root: str,
    plan_dir: str | None = None,
    model: str = "opencode/big-pickle",
    max_iterations: int = 3,
    apply: bool = False,
) -> dict:
    """One-call autonomous drive: run plan's free/toolbox tiers, test the repo in the sandbox copy, optionally apply a green fix to the real tree, record metrics + a memory lesson. Judgment (claude/sonnet) tasks are left assigned for you. apply=false (default) keeps the real tree untouched."""
    from tools import autopilot
    return autopilot.run_autopilot(repo_root, plan_dir, model, max_iterations, apply)


if __name__ == "__main__":
    mcp.run(transport="stdio")