"""M6 metrics — append-only JSONL ledger for eval runs + aggregate reporting.

Each eval run appends one record. Records are cheap and honest: modeled wall-time, worker
calls, iterations, token estimates, and an illustrative USD figure (constants below; free
models are $0). SWE-bench-style verdicts land here too.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import uuid
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# format: model_id -> (input_usd / 1M tok, output_usd / 1M tok); free = 0.
MODEL_PRICES = {
    "opencode/big-pickle": (0.0, 0.0),
    "opencode/mimo-v2.5-free": (0.0, 0.0),
    "opencode/ox-alpha-free": (0.0, 0.0),
    "claude-opus": (15.0, 75.0),
    "claude-sonnet": (3.0, 15.0),
}

CHARS_PER_TOKEN = 4.0  # if the layer doesn't report tokens, estimate from chars


def _metrics_dir(root: str | None = None) -> Path:
    base = Path(root) if root else Path(__file__).resolve().parent.parent
    d = base / ".os" / "metrics"
    d.mkdir(parents=True, exist_ok=True)
    return d


def record(
    suite: str,
    case_id: str,
    model: str,
    verdict: str,
    *,
    iterations_to_green: int,
    worker_calls: int,
    worker_seconds: float,
    backend: str,
    prompt_chars: int = 0,
    output_chars: int = 0,
    extra: dict | None = None,
    root: str | None = None,
) -> dict:
    """Append a metrics record; return it with ids + cost attached."""
    now = _dt.datetime.now(_dt.timezone.utc)
    run_id = uuid.uuid4().hex[:12]
    tok_in = max(1, int(prompt_chars / CHARS_PER_TOKEN))
    tok_out = max(1, int(output_chars / CHARS_PER_TOKEN))
    p_in, p_out = MODEL_PRICES.get(model, (0.0, 0.0))
    cost = (tok_in / 1e6) * p_in + (tok_out / 1e6) * p_out
    rec = {
        "ts": now.isoformat(timespec="seconds"),
        "run_id": run_id,
        "suite": suite,
        "case": case_id,
        "model": model,
        "verdict": verdict,
        "pass": verdict in ("PASS", "GREEN"),
        "iterations_to_green": iterations_to_green,
        "worker_calls": worker_calls,
        "worker_seconds": round(worker_seconds, 2),
        "backend": backend,
        "est_tokens_in": tok_in,
        "est_tokens_out": tok_out,
        "est_cost_usd": round(cost, 6),
        **(extra or {}),
    }
    path = _metrics_dir(root) / f"eval-{now:%Y%m%d}.jsonl"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec


def report(root: str | None = None, limit: int = 200) -> dict:
    """Aggregate every recorded run (optionally only the most recent `limit`)."""
    logs = sorted(_metrics_dir(root).glob("eval-*.jsonl"))
    runs: list[dict] = []
    for lp in logs:
        with open(lp, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    runs.append(json.loads(line))
    if not runs:
        return {"runs": 0, "message": "no eval metrics recorded yet"}
    runs = runs[-limit:]
    skipped = sum(1 for r in runs if r.get("verdict") == "SKIP")
    scored = [r for r in runs if r.get("verdict") != "SKIP"]
    passed = sum(1 for r in scored if r.get("pass"))
    total_cost = round(sum(r.get("est_cost_usd", 0.0) for r in runs), 6)
    total_w_sec = round(sum(r.get("worker_seconds", 0.0) for r in runs), 1)
    runs_sorted = sorted(runs, key=lambda r: (r["suite"], r["case"]))
    return {
        "total_runs": len(runs),
        "skipped": skipped,
        "scored": len(scored),
        "passed": passed,
        "failed": len(scored) - passed,
        "pass_rate": round(passed / max(len(scored), 1), 3),
        "total_worker_seconds": total_w_sec,
        "avg_seconds_eval": round(total_w_sec / max(len(runs), 1), 1),
        "total_cost_usd": total_cost,
        "runs": runs_sorted,
    }