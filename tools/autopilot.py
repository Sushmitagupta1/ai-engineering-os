"""M7 autopilot — one-call autonomous drive: plan -> looper -> test loop -> apply -> metrics -> memory.

Contract: this can run ENTIRELY without the Claude brain ONLY when every task is tier
free/toolbox AND the resulting changes pass tests. Any claude/sonnet task is left `assigned`
for the Claude brain (that is by design — judgment stays with Claude; autopilot does the
mechanical orchestration around it).

CLI: python -m tools.autopilot <repo_root> --plan <plan_dir> [--apply] [--free-model ...]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import diffpatch, looper, memory, metrics, testloop
from tools.plan import PlanStore


def run_autopilot(
    repo_root: str,
    plan_dir: str | None = None,
    model: str = "opencode/big-pickle",
    max_iterations: int = 3,
    apply: bool = False,
) -> dict:
    """Chain: (1) execute plan's autonomous tiers, (2) test loop on the repo copy,
    (3) optionally apply the green copy to the real tree, (4) record metrics + memory."""
    root = Path(repo_root).resolve()
    plan_out = {"plan": None, "stats": None}
    if plan_dir:
        st = PlanStore(plan_dir)
        plan_out["plan"] = st.plan_id
        plan_out["stats"] = looper.run_plan(plan_dir, model=model, repo_root=str(root))

    stage = "test"
    loop = testloop.run_test_loop(str(root), model=model, max_iterations=max_iterations)
    green = bool(loop.get("green"))
    applied = {"ok": False}
    if green and loop.get("copy_dir") and apply:
        applied = diffpatch.apply_copy_to_original(str(root), loop["copy_dir"])
        stage = "apply"

    elapsed = loop.get("history", [{}])[0].get("duration", 0.0) if loop.get("history") else 0.0
    rec = metrics.record(
        suite="autopilot",
        case_id=root.name,
        model=model,
        verdict="PASS" if green else "FAIL",
        iterations_to_green=loop.get("iterations", 0),
        worker_calls=max(1, loop.get("iterations", 1)),
        worker_seconds=elapsed,
        backend=loop.get("backend", "local"),
        extra={
            "plan": plan_out.get("plan"),
            "apply": apply,
            "applied": applied.get("ok", False),
            "copy_dir": loop.get("copy_dir", ""),
        },
    )
    lesson = (
        f"autopilot on {root.name}: tests {'green' if green else 'red'}, "
        f"{rec['est_tokens_in']}tok in, {rec['worker_seconds']}s. "
        + ("changes applied to real tree." if applied.get("ok") else "not applied (or not green).")
    )
    memory.add("lesson", lesson, tags=["autopilot", root.name])
    return {"plan": plan_out, "stage": stage, "green": green,
            "loop": loop.get("history"), "applied": applied, "metrics_row": rec}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="M7 autopilot")
    ap.add_argument("repo", help="repo root")
    ap.add_argument("--plan", default=None)
    ap.add_argument("--model", default="opencode/big-pickle")
    ap.add_argument("--iterations", type=int, default=3)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    out = run_autopilot(args.repo, args.plan, args.model, args.iterations, args.apply)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())