"""M7 memory — durable JSONL journal for decisions, facts, and lessons + session priming.

Memory kinds: decision (architecture/trading choices), fact (environment/tools), lesson
(what worked/failed), state (latest auto-done milestone). `recall` does word-match scoring
with recency tiebreak; the session primer surfaces the last decision, open plans, and the
latest eval metrics so a fresh Claude Code session resumes instantly.

CLI:  python -m tools.memory add decision  "text" --tags a,b
      python -m tools.memory recall "docker"
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

KINDS = {"decision", "fact", "lesson", "state"}


def _store() -> Path:
    d = Path(__file__).resolve().parent.parent / ".os" / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d / "journal.jsonl"


def add(kind: str, text: str, tags: list[str] | None = None, root: str | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}")
    base = Path(root) if root else Path(__file__).resolve().parent.parent
    path = base / ".os" / "memory" / "journal.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "kind": kind,
        "text": text,
        "tags": tags or [],
    }
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec


def _load(path: Path) -> list[dict]:
    recs = []
    if not path.exists():
        return recs
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return recs


def recall(kind: str | None = None, query: str = "", limit: int = 10,
           root: str | None = None) -> list[dict]:
    base = Path(root) if root else Path(__file__).resolve().parent.parent
    recs = _load(base / ".os" / "memory" / "journal.jsonl")
    if kind:
        recs = [r for r in recs if r.get("kind") == kind]
    qs = {w for w in query.lower().split() if len(w) > 2}
    scored = []
    for r in recs:
        hay = f"{r.get('text','')} {' '.join(r.get('tags',[]))}".lower()
        score = sum(1 for w in qs if w in hay) if qs else 1
        if score:
            scored.append((score, r.get("ts", ""), r))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [r for _, _, r in scored[:limit]]


def session_primer(root: str | None = None) -> dict:
    """Pull the last decision, open plans, and latest eval summary for session start."""
    from tools.plan import PlanStore
    from tools import metrics
    base = Path(root) if root else Path(__file__).resolve().parent.parent
    last = _load(base / ".os" / "memory" / "journal.jsonl")
    decisions = [r for r in last if r.get("kind") == "decision"][-1:]
    lessons = [r for r in last if r.get("kind") == "lesson"][-2:]
    plans_dir = base / ".os" / "plans"
    open_plans = []
    for pd in sorted(plans_dir.glob("*/plan.json")):
        try:
            p = PlanStore(str(pd.parent))
            d = p.to_dict()
            if d.get("status") in ("open", "active", "in_progress"):
                open_plans.append({"id": p.plan_id, "status": d.get("status"),
                                   "remaining": len([t for t in p.tasks()
                                                     if t.status not in ("done", "cancelled")])})
        except Exception:  # noqa: BLE001
            continue
    try:
        m = metrics.report(root=str(base), limit=50)
        msum = {k: m[k] for k in ("total_runs", "passed", "skipped", "pass_rate",
                                  "total_cost_usd") if k in m}
    except Exception:  # noqa: BLE001
        msum = {}
    return {"last_decision": decisions, "recent_lessons": lessons,
            "open_plans": open_plans, "eval": msum}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="M7 memory journal")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("kind", choices=sorted(KINDS))
    a.add_argument("text")
    a.add_argument("--tags", default="")
    r = sub.add_parser("recall")
    r.add_argument("query", default="", nargs="?")
    r.add_argument("--kind", default=None)
    r.add_argument("--limit", type=int, default=10)
    p = sub.add_parser("primer")
    args = ap.parse_args(argv)
    if args.cmd == "add":
        rec = add(args.kind, args.text, [t.strip() for t in args.tags.split(",") if t.strip()])
        print(json.dumps(rec, indent=1))
    elif args.cmd == "recall":
        print(json.dumps(recall(args.kind, args.query, args.limit), indent=1))
    else:
        print(json.dumps(session_primer(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())