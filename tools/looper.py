"""M3 loop executor: drive a plan's tasks, tier-aware.

The looper runs ONLY deterministic (toolbox) and free-model (free) tasks autonomously
(safe - read-only). Judgment tasks (claude, sonnet) are marked `assigned` and returned to
the caller so the Claude brain (planner/builder subagents) does them, then calls
`tools.plan.update` to mark them done and re-runs the looper.

python -m tools.looper <plan_dir> [--model ...] [--max-free ...]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from freeworker.dispatch import run_opencode
from repoindex.ingest import ingest as ingest_repo
from tools import packer
from tools.plan import PlanStore

FREE_PROMPT = """You are a READ-ONLY analyst/worker for an AI engineering system.
Do NOT modify, create, or delete any files. Never echo secrets.
TASK: {desc}
DEFINITION OF DONE: {dedo}
ANSWER as the final message with your deliverable, terse and structured. No preamble.

CONTEXT FILES:
{context}
"""

TOOLBOX_ACTIONS = {
    "ingest": "re-index the repository",
    "summarize": "enrich chunks with free-model summaries",
}


def _repo_root() -> Path:
    env = os.environ.get("REPO_ROOT")
    if env and os.path.isdir(env):
        return Path(env)
    return Path(__file__).resolve().parent.parent


def _free_context(repo_root: Path, files: list[str]) -> str:
    cleaned = [f.replace("\\", "/") for f in files if f]
    if not cleaned:
        return "(no target files listed; see repo root)"
    pack = packer.pack(cleaned, root=str(repo_root), max_lines=200, include_symbol_table=True)
    return pack["output"][:16000]


def _run_free(store: PlanStore, task, repo_root: Path, model: str, max_retries: int = 2) -> tuple[str, str]:
    context = _free_context(repo_root, task.target_files)
    prompt = FREE_PROMPT.format(desc=task.description, dedo=task.dedo or "fits the task description", context=context)
    last_err = ""
    for attempt in range(1, max_retries + 1):
        try:
            out = run_opencode(model, prompt, str(repo_root), 600)
            if not out.strip():
                raise RuntimeError("empty worker response")
            return "done", out[:3000]
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            if attempt < max_retries:
                continue
    return "failed", last_err


def _run_toolbox(store: PlanStore, task, repo_root: Path) -> tuple[str, str]:
    action = task.action or "ingest"
    if action == "ingest":
        res = ingest_repo(repo_root)
        return "done", json.dumps({"indexed_files": res["indexed_files"], "symbols": res["symbols"]})
    if action == "summarize":
        # defer to summarize CLI semantics: too heavy to run inline without a model flag
        return "assigned", "run `python -m repoindex.summarize` (needs a free-model budget)"
    return "assigned", f"unknown toolbox action {action!r}; pick from {sorted(TOOLBOX_ACTIONS)}"


def run_plan(
    plan_dir: str,
    model: str = "opencode/big-pickle",
    max_free: int = 10,
    repo_root: str | None = None,
) -> dict:
    store = PlanStore(plan_dir)
    root = Path(repo_root) if repo_root else _repo_root()
    stats = {"free_done": 0, "toolbox_done": 0, "assigned": 0, "failed": 0, "blocked": 0}
    for _ in range(max_free):
        ready = store.ready_tasks()
        if not ready:
            break
        progressed = False
        for task in ready:
            if task.tier == "free":
                status, result = _run_free(store, task, root, model)
                store.advance(task.id, status, result=result)
                stats["free_done" if status == "done" else "failed"] += 1
                progressed = True
            elif task.tier == "toolbox":
                status, result = _run_toolbox(store, task, root)
                store.advance(task.id, status, notes=result if status != "done" else "", result=result)
                stats["toolbox_done" if status == "done" else ("assigned" if status == "assigned" else "failed")] += 1
                progressed = True
            else:  # claude / sonnet: judgment -> hand back to Claude Code
                store.advance(task.id, "assigned", "awaiting Claude brain")
                stats["assigned"] += 1
                progressed = True
        if not progressed:
            break

    remaining = [t for t in store.tasks() if t.status in ("pending", "ready")]
    stats["remaining"] = len(remaining)
    stats["assigned_now"] = [t.id for t in store.tasks() if t.status == "assigned"]
    return {"plan": store.plan_id, **stats}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="run autonomous tiers of a plan")
    ap.add_argument("plan", help="plan directory")
    ap.add_argument("--model", default="opencode/big-pickle")
    ap.add_argument("--max-free", type=int, default=10)
    ap.add_argument("--repo-root", default=None)
    args = ap.parse_args(argv)
    res = run_plan(args.plan, args.model, args.max_free, args.repo_root)
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())