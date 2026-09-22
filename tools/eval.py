"""M6 eval harness — drive real seeded/real bugs through the M4+M5 pipeline, record metrics.

Design:
  - Each case is a directory under EVAL_SUITE_ROOT (default .os/eval/work) containing a small
    repo WITH a failing test (the bug), plus a `case.json` describing it.
  - The harness runs the M4 test loop (copy -> free-worker fix -> retest), and if green,
    applies the fix to the case's real tree (review-gated in real use; here auto-applied for
    the metric), re-verifies, then records a metrics row.
  - Curated SWE-bench-style tasks can be dropped in later as real issue repos.

case.json:
  { "id": "calc-001", "suite": "ml", "bug_class": "arithmetic",
    "expected": "PASS", "model": "opencode/big-pickle", "max_iterations": 3 }

CLI:  python -m tools.eval [suite_root] — runs every case, prints a report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import diffpatch, metrics, testloop


def discover(suite_root: str) -> list[dict]:
    root = Path(suite_root)
    out = []
    for repo in sorted(p for p in root.iterdir() if p.is_dir()):
        cfg = repo / "case.json"
        if not cfg.exists():
            continue
        meta = json.loads(cfg.read_text(encoding="utf-8"))
        out.append({"root": str(repo), "meta": meta})
    return out


def _is_test_file(rel: str) -> bool:
    r = rel.replace("\\", "/")
    return (r.startswith(("tests/", "test/")) or "/tests/" in r or "/test/" in r
            or r.startswith("test_") or r.endswith("_test.py") or r.endswith("_test.go"))


def run_one(repo_root: str, meta: dict) -> dict:
    started = time.monotonic()
    model = meta.get("model", "opencode/big-pickle")
    max_iter = int(meta.get("max_iterations", 3))

    # 0) already-green trees mean a prior run applied the fix; don't count as a fresh PASS
    pre, _rid = testloop.run_tests(repo_root)
    if pre.green():
        rec = metrics.record(
            suite=meta.get("suite", "default"), case_id=meta.get("id", Path(repo_root).name),
            model=model, verdict="SKIP", iterations_to_green=0, worker_calls=0,
            worker_seconds=0.0, backend=pre.backend,
            extra={"reason": "already_green", "bug_class": meta.get("bug_class", "")},
        )
        return {"case": rec["case"], "verdict": "SKIP", "cost_usd": 0.0, "seconds": 0.0,
                "it_green": 0, "apply_ok": False, "recheck_green": True, "reason": "already_green"}

    # 1) M4: copy -> fix -> retest (never touches real tree)
    loop = testloop.run_test_loop(repo_root, model=model, max_iterations=max_iter)
    final = loop.get("final", {})
    green = bool(loop.get("green"))
    test_gamed = False

    # 2) anti-gaming: the fix must not rewrite test files (tests are ground truth)
    if green and loop.get("copy_dir"):
        patch = diffpatch.make_patch(repo_root, str(Path(loop["copy_dir"]).resolve()))
        changed = [d["path"] for d in patch.get("files", [])]
        test_gamed = any(_is_test_file(p) for p in changed)
        if test_gamed:
            green = False

    # 3) M5: if green, apply copy to real tree, then re-verify on the real tree
    apply_snapshot = {"applied": False}
    final_verdict = "FAIL"
    if green and loop.get("copy_dir"):
        copy_dir = str(Path(loop["copy_dir"]).resolve())
        apply_snapshot = diffpatch.apply_copy_to_original(repo_root, copy_dir)
        if apply_snapshot.get("ok"):
            real, _rid = testloop.run_tests(repo_root)
            if real.green():
                final_verdict = "PASS"
                apply_snapshot["recheck_green"] = True
            else:
                apply_snapshot["recheck_green"] = False
    if test_gamed:
        final_verdict = "FAIL"

    elapsed = time.monotonic() - started
    iterations = loop.get("iterations", max_iter)
    prompt_chars = output_chars = 0
    for h in loop.get("history", []):
        prompt_chars += len(str(h.get("fix_error", "")))
        output_chars += sum(len(str(f.get("message", ""))) for f in h.get("failures", []))

    rec = metrics.record(
        suite=meta.get("suite", "default"),
        case_id=meta.get("id", Path(repo_root).name),
        model=model,
        verdict=final_verdict,
        iterations_to_green=iterations,
        worker_calls=max(1, iterations),
        worker_seconds=round(elapsed, 2),
        backend=loop.get("backend", "local"),
        prompt_chars=prompt_chars,
        output_chars=output_chars,
        extra={
            "bug_class": meta.get("bug_class", ""),
            "copy_dir": loop.get("copy_dir", ""),
            "apply_ok": apply_snapshot.get("ok", False),
            "recheck_green": apply_snapshot.get("recheck_green", None),
            "test_gamed": test_gamed,
        },
    )
    return {"case": rec["case"], "verdict": rec["verdict"], "cost_usd": rec["est_cost_usd"],
            "seconds": rec["worker_seconds"], "it_green": rec["iterations_to_green"],
            "apply_ok": apply_snapshot.get("ok", False),
            "recheck_green": apply_snapshot.get("recheck_green", None),
            "test_gamed": test_gamed}


def run_suite(suite_root: str) -> dict:
    cases = discover(suite_root)
    results = []
    for c in cases:
        try:
            results.append(run_one(c["root"], c["meta"]))
        except Exception as exc:  # noqa: BLE001
            results.append({"case": c["meta"].get("id"), "verdict": "ERROR", "error": str(exc)})
    rep = metrics.report()
    return {"cases": len(cases), "results": results, "metrics": rep}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="run M6 eval suite")
    ap.add_argument("suite_root", nargs="?", default=None,
                    help="dir of case repos (default: .os/eval/work)")
    args = ap.parse_args(argv)
    root = args.suite_root or str(Path(__file__).resolve().parent.parent / ".os" / "eval" / "work")
    report = run_suite(root)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())