"""M8 — Standalone AI Engineering OS App (web).

Runs the existing AI-OS backend (plan/worker/test-loop/diff/apply/memory) behind a
simple local web UI. OpenCode stays a background free-model worker; the user talks to
this app instead of the terminal.

Run:  python app/server.py   ->  http://127.0.0.1:8787
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from freeworker.dispatch import run_opencode
from tools import diffpatch, memory
from tools.plan import PlanStore
from sandbox.runner import copy_repo
from tools import testloop, packer

APP = FastAPI(title="AI Engineering OS")

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
PROJECTS_FILE = ROOT / ".os" / "app" / "projects.json"

def _detect_lang(text: str) -> str:
    """Return 'hinglish' when the user clearly writes in Devanagari or heavy Hinglish,
    else 'english'. Bengali/Gujarati/etc count as non-English too -> hinglish fallback."""
    if any("\u0900" <= ch <= "\u097F" for ch in text):  # Devanagari
        return "hinglish"
    if any("\u0980" <= ch <= "\u09FF" for ch in text):  # Bengali
        return "hinglish"
    if any("\u0A00" <= ch <= "\u0A7F" for ch in text):  # Gurmukhi
        return "hinglish"
    if any("\u0A80" <= ch <= "\u0AFF" for ch in text):  # Gujarati
        return "hinglish"
    words = {w for w in text.lower().split() if len(w) > 1}
    strong = {"karo", "karna", "hai", "hain", "raha", "rahi", "banao", "chahiye",
              "nahi", "nhi", "sare", "saare", "batao", "dikhao", "kholo",
              "samajh", "kro", "laga", "apna", "apne", "isko", "usko", "yahan",
              "wahan", "naya", "nayi", "karey", "kre", "pure", "sahi",
              "thik", "lo", "dalo", "likho", "kardo", "kara", "kiya", "mera",
              "tumhara", "aapka", "karta", "karti", "chal", "chala", "jata",
              "jati", "hume", "bilkul", "aur", "hoga", "hota", "karne",
              "banane", "dikhta", "milta", "ho", "jaye", "jake", "khud",
              "waali", "wali", "alag", "jaisa", "kaise", "kiske", "kisi"}
    hits_strong = words & strong
    if hits_strong:
        return "hinglish"
    hing = {"karo", "karna", "hai", "hain", "raha", "rahi", "bana", "banao",
            "do", "de", "chahiye", "kaam", "kya", "ye", "wo", "wala",
            "nahi", "batao", "dikho", "kholo", "samajh", "project", "kro",
            "kar", "laga", "tha", "kuch", "apna", "apne", "isko", "usko",
            "yahan", "wahan", "ek", "naya", "nayi", "jo", "karey", "kre",
            "ko", "se", "par", "ke", "aur", "phir", "agar", "toh", "hota",
            "hoga", "me", "jis", "unko", "inco", "mera", "tum", "aap",
            "kiya", "karta", "karti", "chal", "chala", "jata", "jati",
            "hume", "hum", "bilkul", "karne", "banane", "milta", "dikhta"}
    hits = words & hing
    return "hinglish" if len(hits) >= 3 else "english"


def _dirive_lang(lang: str, reply: bool = True) -> str:
    if lang == "hinglish":
        return ("Reply in simple Hinglish (Hindi written in English letters). "
                "Use English for technical/code terms." if reply else
                "Please respond in simple Hinglish.")
    return ("Reply in English." if reply else "Please respond in English.")


FREE_MODEL = "opencode/big-pickle"

# silence git CRLF chatter etc. via normal stderr capture
_JOB_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}


def _projects() -> list[dict]:
    if PROJECTS_FILE.exists():
        try:
            return json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_projects(projs: list[dict]) -> None:
    PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROJECTS_FILE.write_text(json.dumps(projs, indent=2), encoding="utf-8")


def _job(job_id: str) -> dict:
    with _JOB_LOCK:
        return _JOBS[job_id]


def _job_update(job_id: str, **kw) -> dict:
    with _JOB_LOCK:
        j = _JOBS.setdefault(job_id, {"id": job_id, "events": []})
        for k, v in kw.items():
            if k == "events":
                j["events"].extend(v)
            else:
                j[k] = v
        return j


def _push(job_id: str, stage: str, msg: str) -> None:
    _job_update(job_id, stage=stage, events=[{"t": time.strftime("%H:%M:%S"),
                                              "stage": stage, "msg": msg}])


# ---------------------------------------------------------------- project / fs

def _list_tree(path: Path, depth: int = 0) -> list[dict]:
    if depth > 3 or not path.exists() or path.name.startswith("."):
        return []
    out = []
    try:
        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        return out
    for p in entries:
        if p.name in (".venv", "__pycache__", ".git", "node_modules", "junit.xml"):
            continue
        item = {"name": p.name,
                "is_dir": p.is_dir(),
                "path": str(p).replace("\\", "/")}
        if p.is_dir():
            item["children"] = _list_tree(p, depth + 1)
        else:
            try:
                item["size"] = p.stat().st_size
            except OSError:
                item["size"] = 0
        out.append(item)
    return out


@APP.get("/api/projects")
def api_projects() -> dict:
    return {"projects": _projects()}


@APP.post("/api/project/select")
async def api_project_select(req: Request) -> dict:
    body = await req.json()
    path = str(body.get("path", "")).strip().strip('"').strip("'")
    root = Path(path).resolve()
    if not root.exists() or not root.is_dir():
        return JSONResponse({"error": f"folder not found: {path}"}, status_code=400)
    projs = _projects()
    projs = [p for p in projs if Path(p["path"]).resolve() != root]
    projs.insert(0, {"path": str(root), "name": root.name, "selected": time.time()})
    _save_projects(projs[:12])
    return {"ok": True, "project": projs[0]}


@APP.get("/api/project/tree")
def api_project_tree(path: str) -> dict:
    root = Path(path).resolve()
    if not root.is_dir():
        return JSONResponse({"error": "folder not found"}, status_code=400)
    return {"root": str(root).replace("\\", "/"), "tree": _list_tree(root)}


@APP.get("/api/project/file")
def api_project_file(path: str) -> dict:
    p = Path(path).resolve()
    if not p.is_file():
        return JSONResponse({"error": "file not found"}, status_code=400)
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    return {"path": str(p).replace("\\", "/"), "content": content[:200000],
            "truncated": len(content) > 200000}


# ---------------------------------------------------------------- memory / status

@APP.get("/api/primer")
def api_primer() -> dict:
    return {"primer": memory.session_primer(ROOT)}


@APP.get("/api/status")
def api_status() -> dict:
    with _JOB_LOCK:
        jobs = {k: {kk: vv for kk, vv in v.items()} for k, v in _JOBS.items()}
    return {"free_model": FREE_MODEL, "jobs": jobs}


# ---------------------------------------------------------------- agent run

def _worker_task(prompt: str, cwd: str) -> str:
    return run_opencode(FREE_MODEL, prompt, cwd, 900)


def _agent_worker(job_id: str, project: Path, instruction: str, apply: bool, lang: str) -> None:
    try:
        _push(job_id, "plan", f"creating plan for: {instruction[:80]}")
        ps = PlanStore.create(
            title=f"web: {instruction[:60]}",
            goal=instruction,
            plans_dir=str(ROOT / ".os" / "plans"),
        )
        ps.add_task("Understand and pack context", "free", task_id="understand")
        ps.add_task(instruction, "free", task_id="implement")
        ps.add_task("Run tests and verify", "toolbox", task_id="verify")
        plan_id = ps.plan_id
        _push(job_id, "plan", f"plan {plan_id} created")

        _push(job_id, "context", "packing context of relevant files")
        try:
            pack = packer.pack([], root=str(project), max_lines=600, include_symbol_table=True)
            context = pack.get("output", "")[:12000]
        except Exception as exc:  # noqa: BLE001
            context = f"(context pack failed: {exc})"

        _push(job_id, "worker", "making sandbox copy (real files stay safe)")
        copy = Path(project) / ".os" / "sandbox" / f"web-{int(time.time() * 1000)}"
        copy_repo(str(project), str(copy))
        _push(job_id, "worker", "sending task to free worker (opencode, {})".format(FREE_MODEL))

        prompt = (
            "You are the implementer inside a disposable working copy of a repository "
            f"at {copy}.\n\nTask from the user: {instruction}\n\nRepo context:\n{context}\n\n"
            "Implement the requested change in the working copy by WRITING the files. "
            "Keep edits minimal and idiomatic. Do NOT touch anything under .os/. "
            "When done, reply with a short summary and the files you changed. "
            + _dirive_lang(lang)
        )
        reply = _worker_task(prompt, str(copy))
        if not reply.strip():
            reply = "(worker gave no text reply — checking sandbox files)"
        _push(job_id, "worker", f"worker done: {reply[:300]}")

        # verify + fix INSIDE the worker's copy, so edits and the test loop agree on one
        # battleground (run_test_loop makes its own fresh copy; here we reuse `copy`)
        copy_str = str(copy)
        history = []
        green = False
        for i in range(1, 4):
            result, _rid = testloop.run_tests(str(project), workdir=copy_str)
            history.append({"iteration": i, **result.to_dict()})
            green = result.green()
            _push(job_id, "test",
                  f"iter {i}: {result.passed} passed / {result.failed} failed"
                  + (" -> GREEN" if green else " -> RED"))
            if green or not result.failures:
                break
            brief = "\n".join(
                f"- {f.name} ({f.file}:{f.line}): {f.message[:200]}"
                for f in result.failures[:8])
            ctx = testloop._failure_context(copy_str, result.failures)
            fix = testloop.FIX_PROMPT.format(test_brief=brief, context=ctx)
            fix += "\n" + _dirive_lang(lang)
            _push(job_id, "worker", f"running fix iteration {i}")
            try:
                _worker_task(fix, copy_str)
            except Exception as exc:  # noqa: BLE001
                _push(job_id, "worker", f"fix worker error: {exc}")
                break

        if green:
            _push(job_id, "test", "GREEN — all tests pass")
        else:
            _push(job_id, "test", "RED — tests are failing, review the diff")

        patch = diffpatch.make_patch(str(project), copy_str)
        changed = [f["path"] for f in patch.get("files", [])]
        ps.advance("verify", "done" if green else "blocked",
                   notes=f"green={green}, files={len(changed)}")

        _push(job_id, "diff", "{} file(s) changed in sandbox".format(len(changed)))
        result = {
            "green": green,
            "iterations": len(history),
            "history": history,
            "patch": patch,
            "copy_dir": copy_str,
            "plan_id": plan_id,
            "worker_reply": reply[:800],
            "state": "review",
        }
        if apply and green and changed:
            applied = diffpatch.apply_copy_to_original(str(project), copy_str)
            result["applied"] = applied.get("ok", False)
            result["state"] = "applied" if applied.get("ok") else "review"
            _push(job_id, "apply", "changes applied to the real tree")
            memory.add("lesson", f"web app applied {len(changed)} file(s) on {project.name}",
                       tags=["app", project.name])
        else:
            result["applied"] = False
            if apply and not green:
                _push(job_id, "apply", "tests were red, nothing applied (review first)")
            elif apply and not changed:
                _push(job_id, "apply", "no files changed, apply skipped")
            elif not apply:
                _push(job_id, "apply", "apply is off — press Apply after reviewing")
        _job_update(job_id, done=True, result=result,
                    events=[{"t": time.strftime("%H:%M:%S"), "stage": "done", "msg": "complete"}])
    except Exception as exc:  # noqa: BLE001
        _push(job_id, "error", str(exc)[:400])
        _job_update(job_id, done=True, error=str(exc))


@APP.post("/api/agent/run")
async def api_agent_run(req: Request) -> dict:
    body = await req.json()
    project = Path(str(body.get("project", ""))).resolve()
    instruction = str(body.get("instruction", "")).strip()
    apply = bool(body.get("apply", False))
    if not project.is_dir():
        return JSONResponse({"error": "project folder invalid"}, status_code=400)
    if not instruction:
        return JSONResponse({"error": "instruction empty"}, status_code=400)
    job_id = uuid.uuid4().hex[:10]
    lang = _detect_lang(instruction)
    _JOBS[job_id] = {"id": job_id, "events": [], "stage": "queued", "done": False, "lang": lang}
    threading.Thread(target=_agent_worker,
                     args=(job_id, project, instruction, apply, lang), daemon=True).start()
    return {"job_id": job_id, "lang": lang}


@APP.get("/api/agent/status")
def api_agent_status(job_id: str) -> dict:
    if job_id not in _JOBS:
        return JSONResponse({"error": "job not found"}, status_code=404)
    return _job(job_id)


@APP.post("/api/agent/apply")
async def api_agent_apply(req: Request) -> dict:
    body = await req.json()
    project = Path(str(body.get("project", ""))).resolve()
    copy = Path(str(body.get("copy_dir", ""))).resolve()
    if not project.is_dir() or not copy.is_dir():
        return JSONResponse({"error": "invalid paths"}, status_code=400)
    applied = diffpatch.apply_copy_to_original(str(project), str(copy))
    return {"applied": applied}


# ---------------------------------------------------------------- static / cli

APP.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@APP.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


def main() -> int:
    ap = argparse.ArgumentParser(description="M8 web app")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()
    print(f"AI Engineering OS web app -> http://{args.host}:{args.port}")
    uvicorn.run(APP, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())