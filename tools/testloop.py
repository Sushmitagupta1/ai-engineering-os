"""M4 test loop: run tests in the sandbox copy, parse results, auto-retry.

Iteration: run pytest (junit xml) -> parse failures -> send failing tests + tombstone context
to a fixer worker (free model by default) -> apply result -> re-run. Bounded iterations.
The loop ALWAYS works on a disposable copy of the repo, never the real working tree.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from freeworker.dispatch import run_opencode
from sandbox.runner import copy_repo, run_pytest
from tools import packer

JUNIT = "junit.xml"


@dataclass
class Failure:
    name: str
    file: str
    line: int
    message: str

    def to_dict(self) -> dict:
        return {"name": self.name, "file": self.file, "line": self.line, "message": self.message[:800]}


@dataclass
class TestResult:
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration: float = 0.0
    failures: list[Failure] = field(default_factory=list)
    backend: str = "local"

    def green(self) -> bool:
        return self.failed == 0 and self.errors == 0

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "duration": round(self.duration, 2),
            "backend": self.backend,
            "green": self.green(),
            "failures": [f.to_dict() for f in self.failures],
        }


def _parse_junit(xml_path: Path) -> TestResult:
    res = TestResult()
    try:
        root = ElementTree.parse(xml_path).getroot()
    except (ElementTree.ParseError, FileNotFoundError):
        return res
    suite = root
    res.total = res.failed = res.errors = res.skipped = 0
    for tc in suite.iter("testcase"):
        res.total += 1
        kids = list(tc)
        is_err = any(k.tag in ("failure", "error") for k in kids)
        if not is_err:
            res.passed += 1
            continue
        for node in kids:
            if node.tag == "failure":
                res.failed += 1
            elif node.tag == "error":
                res.errors += 1
            res.failures.append(Failure(
                name=tc.get("name", "?"),
                file=tc.get("file", ""),
                line=int(tc.get("line", 0) or 0),
                message=(node.text or node.get("message", "") or "")[:1400],
            ))
    res.skipped = int(suite.get("skipped", 0)) or res.skipped
    res.duration = float(suite.get("time", 0.0))
    return res


def run_tests(
    repo_root: str,
    workdir: str | None = None,
    pytest_args: list[str] | None = None,
    timeout: int = 600,
) -> tuple[TestResult, str | None]:
    """Run pytest on repo_root (or its sandbox copy at workdir). Returns (result, xml_path)."""
    target = workdir or repo_root
    xml_path = Path(target) / JUNIT
    if xml_path.exists():
        xml_path.unlink()
    args = ["--junitxml=" + str(xml_path), "-q"] + (pytest_args or [])
    sr = run_pytest(target, args, timeout)
    res = _parse_junit(xml_path)
    res.backend = sr.backend
    if sr.timed_out:
        res.errors += 1
    if xml_path.exists():
        xml_path.unlink()
    return res, sr.raw.get("run_id")


def _failure_context(repo_root: str, failures: list[Failure]) -> str:
    files = {f.file for f in failures if f.file}
    rel_files = []
    root = Path(repo_root)
    for f in files:
        p = Path(f)
        if p.is_absolute():
            try:
                rel = str(p.relative_to(root)).replace("\\", "/")
            except ValueError:
                rel = str(p).replace("\\", "/")
        else:
            rel = str(p).replace("\\", "/")
        if rel not in rel_files:
            rel_files.append(rel)
    if not rel_files:
        return "(failing tests had no file info)"
    try:
        pack = packer.pack(rel_files[:6], root=str(root), max_lines=400, include_symbol_table=True)
        return pack["output"][:20000]
    except Exception:  # noqa: BLE001
        return "(context pack failed)"


FIX_PROMPT = """You are a debugging engineer. Tests are failing in the repository at the working copy.
Reproduce and visually inspect the files. The failing tests are:

{test_brief}

Relevant source context:
{context}

Produce a MINIMAL fix. Rules:
- Only change files under the repo. Do not remove or weaken tests unless they are demonstrably wrong.
- Keep the fix small and idiomatic.
- Output the exact patch applied as final message: a diff-style list "file: changed lines".

Think step by step, then apply the edit."""
# note: workers made read-only in M0-M3 policy; M4 fixes run inside the disposable copy,
# so mutation there is permitted by construction.


def run_test_loop(
    repo_root: str,
    model: str = "opencode/big-pickle",
    max_iterations: int = 3,
    workdir: str | None = None,
) -> dict:
    """Iterate: test -> fix (free worker) -> retest, inside a disposable copy."""
    repo_root = str(Path(repo_root).resolve())
    root = Path(repo_root)
    if workdir:
        sandbox_dir = Path(workdir)
    else:
        sandbox_dir = Path(root) / ".os" / "sandbox"
        # use a stable session temp even if repo is read-only at .os
        try:
            sandbox_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            sandbox_dir = Path(tempfile.gettempdir()) / "ai-os-sandbox"
            sandbox_dir.mkdir(parents=True, exist_ok=True)

    copy = sandbox_dir / f"copy-{int(time.time() * 1000)}"
    copy_repo(str(root), str(copy))

    history = []
    green_at = None
    for i in range(1, max_iterations + 1):
        result, _rid = run_tests(str(root), workdir=str(copy))
        history.append({"iteration": i, **result.to_dict()})
        if result.green():
            green_at = i
            break
        if not result.failures:
            # errors w/o per-test info (import/collection) -> need message, not per-test patch
            break
        brief = "\n".join(
            f"- {f.name} ({f.file}:{f.line}): {f.message[:200]}" for f in result.failures[:8]
        )
        context = _failure_context(str(copy), result.failures)
        prompt = FIX_PROMPT.format(test_brief=brief, context=context)
        try:
            run_opencode(model, prompt, str(copy), 600)
        except Exception as exc:  # noqa: BLE001
            history.append({"iteration": i + 1, "fix_error": str(exc)})
            break

    final, _frid = run_tests(str(root), workdir=str(copy))
    history.append({"iteration": (green_at or max_iterations) + 1, **final.to_dict()})
    last_green = any(h.get("green") for h in history)
    return {
        "green": last_green,
        "iterations": green_at or max_iterations,
        "copy_dir": str(copy),
        "backend": final.backend,
        "history": history,
        "first_run": history[0] if history else None,
        "final": final.to_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="M4 test loop (run in sandbox copy, auto-fix replay)")
    ap.add_argument("repo", help="repository root to test")
    ap.add_argument("--model", default="opencode/big-pickle")
    ap.add_argument("--iterations", type=int, default=3)
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--dry-run", action="store_true", help="run tests only, no fix loop")
    args = ap.parse_args(argv)
    if args.dry_run:
        res, _ = run_tests(args.repo, workdir=args.workdir)
        print(json.dumps(res.to_dict(), indent=1))
        return 0
    out = run_test_loop(args.repo, args.model, args.iterations, args.workdir)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())