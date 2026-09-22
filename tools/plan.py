"""Plan / task model + durable progress ledger for the M3 planner-coder loop.

A plan lives in `<project>/.os/plans/<plan_id>/`:
  plan.json    — plan + tasks + status (single source of truth)
  ledger.jsonl — append-only event log (every advance/run)
Plans are valid JSON, edited through PlanStore (MCP tools and looper), never by hand.

Tiers:
  free     -> dispatched to a free opencode Zen model by the looper (read-only analysis/drafts)
  toolbox  -> deterministic tool op (e.g. ingest) run by the looper
  claude   -> judgment task executed by the Claude brain (planner/debugger/review)
  sonnet   -> implementation task executed by the Claude builder subagent
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ALLOWED_TIERS = {"free", "toolbox", "claude", "sonnet"}
STATUSES = {"pending", "ready", "running", "assigned", "done", "blocked", "failed"}
SAFE_ID = re.compile(r"^[a-zA-Z0-9_.-]+$")

DEFAULT_PLANS_DIR = Path(__file__).resolve().parent.parent / ".os" / "plans"


def default_plans_dir() -> Path:
    env = os.environ.get("PLANS_DIR")
    if env:
        return Path(env)
    return DEFAULT_PLANS_DIR


@dataclass
class Task:
    id: str
    description: str
    tier: str
    dedo: str = ""
    depends_on: list[str] = field(default_factory=list)
    target_files: list[str] = field(default_factory=list)
    action: str = ""
    status: str = "pending"
    notes: str = ""
    result: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "tier": self.tier,
            "dedo": self.dedo,
            "depends_on": list(self.depends_on),
            "target_files": list(self.target_files),
            "action": self.action,
            "status": self.status,
            "notes": self.notes,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        return cls(
            id=d["id"],
            description=d.get("description", ""),
            tier=d.get("tier", "claude"),
            dedo=d.get("dedo", ""),
            depends_on=list(d.get("depends_on", [])),
            target_files=list(d.get("target_files", [])),
            action=d.get("action", ""),
            status=d.get("status", "pending"),
            notes=d.get("notes", ""),
            result=d.get("result", ""),
        )

    def validate(self) -> list[str]:
        errs = []
        if not SAFE_ID.match(self.id):
            errs.append(f"task id {self.id!r} has illegal chars")
        if self.tier not in ALLOWED_TIERS:
            errs.append(f"task {self.id}: tier {self.tier!r} not in {sorted(ALLOWED_TIERS)}")
        if self.status not in STATUSES:
            errs.append(f"task {self.id}: status {self.status!r} invalid")
        return errs


class PlanStore:
    def __init__(self, plan_dir: str | os.PathLike):
        self.dir = Path(plan_dir)
        self.plan_path = self.dir / "plan.json"
        self.ledger_path = self.dir / "ledger.jsonl"
        self._data: dict = {}
        if self.plan_path.exists():
            self._data = json.loads(self.plan_path.read_text(encoding="utf-8"))

    # ---- creation ----
    @classmethod
    def create(cls, title: str, goal: str, plans_dir: str | os.PathLike | None = None) -> "PlanStore":
        base = Path(plans_dir) if plans_dir else default_plans_dir()
        plan_id = time.strftime("plan-%Y%m%d-%H%M%S")
        d = base / plan_id
        d.mkdir(parents=True, exist_ok=True)
        store = cls(d)
        store._data = {
            "plan_id": plan_id,
            "title": title,
            "goal": goal,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "in_progress",
            "tasks": [],
        }
        store._flush()
        store._log({"event": "created", "title": title})
        return store

    # ---- persistence ----
    def _flush(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.plan_path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _log(self, event: dict) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **event}
        with self.ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")

    # ---- accessors ----
    @property
    def plan_id(self) -> str:
        return self._data.get("plan_id", self.dir.name)

    def to_dict(self) -> dict:
        return dict(self._data)

    def tasks(self) -> list[Task]:
        return [Task.from_dict(t) for t in self._data.get("tasks", [])]

    def task(self, task_id: str) -> Task | None:
        for t in self.tasks():
            if t.id == task_id:
                return t
        return None

    # ---- mutations ----
    def add_task(
        self,
        description: str,
        tier: str,
        dedo: str = "",
        depends_on: list[str] | None = None,
        target_files: list[str] | None = None,
        action: str = "",
        task_id: str | None = None,
    ) -> Task:
        _tier = tier if tier in ALLOWED_TIERS else "claude"
        existing_ids = {t["id"] for t in self._data["tasks"]}
        tid = task_id or f"t{len(existing_ids) + 1}"
        if tid in existing_ids:
            raise ValueError(f"task id {tid} already exists")
        task = Task(
            id=tid,
            description=description,
            tier=_tier,
            dedo=dedo,
            depends_on=list(depends_on or []),
            target_files=list(target_files or []),
            action=action,
        )
        errs = task.validate()
        if errs:
            raise ValueError("; ".join(errs))
        self._data["tasks"].append(task.to_dict())
        self._flush()
        self._log({"event": "task_added", "id": tid, "tier": _tier})
        return task

    def advance(self, task_id: str, status: str, notes: str = "", result: str = "") -> Task:
        if status not in STATUSES:
            raise ValueError(f"status {status!r} invalid")
        for t in self._data["tasks"]:
            if t["id"] == task_id:
                t["status"] = status
                if notes:
                    t["notes"] = notes
                if result:
                    t["result"] = result[:4000]
                self._flush()
                self._log({"event": "task_advanced", "id": task_id, "status": status, "notes": notes})
                return Task.from_dict(t)
        raise KeyError(f"no task {task_id}")

    def ready_tasks(self) -> list[Task]:
        """pending tasks whose dependencies are all done; also marks blocked ones."""
        by_id = {t.id: t for t in self.tasks()}
        ready: list[Task] = []
        for t in self.tasks():
            if t.status != "pending":
                continue
            deps = [by_id.get(d) for d in t.depends_on]
            if any(d is None for d in deps):
                continue
            if any(d.status == "failed" or d.status == "blocked" for d in deps):
                self.advance(t.id, "blocked", "a dependency failed")
                continue
            if all(d.status == "done" for d in deps):
                self.advance(t.id, "ready")
                ready.append(Task.from_dict(self.task_dict(t.id)))
        return ready

    def task_dict(self, task_id: str) -> dict:
        for t in self._data["tasks"]:
            if t["id"] == task_id:
                return t
        raise KeyError(task_id)


# ---- CLI ----
def _cli_new(args) -> int:
    store = PlanStore.create(args.title, args.goal, args.dir)
    print(store.dir)
    return 0


def _cli_add(args) -> int:
    store = PlanStore(args.plan)
    t = store.add_task(
        description=args.desc,
        tier=args.tier,
        dedo=args.dedo,
        depends_on=args.depends,
        target_files=args.files,
        action=args.action,
    )
    print(f"added {t.id} ({t.tier})")
    return 0


def _cli_tasks(args) -> int:
    store = PlanStore(args.plan)
    for t in store.tasks():
        print(f"{t.status:8} {t.id:6} [{t.tier:7}] {t.description[:80]}")
    return 0


def _cli_update(args) -> int:
    store = PlanStore(args.plan)
    store.advance(args.id, args.status, args.notes)
    print(f"{args.id} -> {args.status}")
    return 0


def _cli_validate(args) -> int:
    store = PlanStore(args.plan)
    errs: list[str] = []
    for t in store.tasks():
        errs += t.validate()
    if errs:
        print("\n".join(errs), file=sys.stderr)
        return 1
    print(f"plan {store.plan_id}: {len(store.tasks())} tasks, valid")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="M3 plan ledger")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new")
    p.add_argument("--title", required=True)
    p.add_argument("--goal", required=True)
    p.add_argument("--dir", default=None, help="plans dir (default .os/plans)")
    p.set_defaults(fn=_cli_new)

    p = sub.add_parser("add")
    p.add_argument("plan")
    p.add_argument("--desc", required=True)
    p.add_argument("--tier", choices=sorted(ALLOWED_TIERS), default="claude")
    p.add_argument("--dedo", default="")
    p.add_argument("--depends", nargs="*", default=[])
    p.add_argument("--files", nargs="*", default=[])
    p.add_argument("--action", default="")
    p.set_defaults(fn=_cli_add)

    p = sub.add_parser("tasks")
    p.add_argument("plan")
    p.set_defaults(fn=_cli_tasks)

    p = sub.add_parser("update")
    p.add_argument("plan")
    p.add_argument("id")
    p.add_argument("status", choices=sorted(STATUSES))
    p.add_argument("--notes", default="")
    p.set_defaults(fn=_cli_update)

    p = sub.add_parser("validate")
    p.add_argument("plan")
    p.set_defaults(fn=_cli_validate)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())