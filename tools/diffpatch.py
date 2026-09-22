"""M5 diff/patch — pure-Python, git-free.

`diff_tree(original, changed)` -> list of file-diffs (unified text + classified change type).
`apply_copy_to_original(original, copy)` -> applies the copy's changes to the original tree
   (whole-file copy for modified/added, unlink for deleted), backing up each target first.
   All-or-nothing: any failure rolls everything back.
"""

from __future__ import annotations

import difflib
import hashlib
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

# paths that never get diffed or applied (build/junk/cache)
SKIP_PARTS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules",
              ".os", ".idea", ".vscode", "dist", "build", "pgdata", "*.pyc"}
IGNORE_EXTS = {".pyc", ".pyo", ".exe", ".dll", ".so", ".dylib"}


def _skip(path: str) -> bool:
    parts = set(Path(path).parts)
    if parts & SKIP_PARTS:
        return True
    if path.endswith(tuple(IGNORE_EXTS)):
        return True
    return False


def _read(p: Path) -> list[str]:
    return p.read_text(encoding="utf-8", errors="replace").splitlines()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class FileDiff:
    path: str  # slash-relative to repo root
    kind: str  # modified | added | deleted | unchanged
    size_before: int
    size_after: int
    hunks: str = ""

    @property
    def changed(self) -> bool:
        return self.kind in ("modified", "added", "deleted")


def diff_tree(original_root: str, copy_root: str) -> list[FileDiff]:
    """Compare the disposable copy against the original tree, file by file."""
    orig = Path(original_root).resolve()
    copy = Path(copy_root).resolve()
    diffs: list[FileDiff] = []
    for rel in sorted(_walk(copy)):
        if _skip(rel):
            continue
        oc, cc = orig / rel, copy / rel
        exists_o, exists_c = oc.exists(), cc.exists()
        if exists_o and not exists_c:
            diffs.append(FileDiff(rel, "deleted", oc.stat().st_size, 0))
        elif not exists_o and exists_c:
            text_c = _read(cc)
            diffs.append(FileDiff(rel, "added", 0, cc.stat().st_size,
                                  _unified("", "/dev/null" if False else rel,
                                           "new", rel, [], text_c, 1)))
        elif exists_o and exists_c and file_hash(oc) != file_hash(cc):
            text_o, text_c = _read(oc), _read(cc)
            diffs.append(FileDiff(rel, "modified", oc.stat().st_size, cc.stat().st_size,
                                  _unified(rel, rel, rel, rel, text_o, text_c)))
    return [d for d in diffs if d.changed]


def _walk(root: Path):
    for p in root.rglob("*"):
        if p.is_file():
            yield p.relative_to(root).as_posix()


def _unified(old_path, new_path, old_header, new_header, old_lines, new_lines, n=3):
    return "".join(difflib.unified_diff(
        old_lines, new_lines, fromfile=old_path, tofile=new_path, n=n))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def make_patch(original_root: str, copy_root: str) -> dict:
    diffs = diff_tree(original_root, copy_root)
    return {
        "changed_files": [d.path for d in diffs],
        "adds": sum(1 for d in diffs if d.kind == "added"),
        "modifies": sum(1 for d in diffs if d.kind == "modified"),
        "deletes": sum(1 for d in diffs if d.kind == "deleted"),
        "files": [{"path": d.path, "kind": d.kind,
                   "size_before": d.size_before, "size_after": d.size_after,
                   "diff": d.hunks} for d in diffs],
    }


def apply_copy_to_original(
    original_root: str,
    copy_root: str,
    files: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """Apply changes from the sandbox copy to the real tree. Backs up first; atomic on failure."""
    orig = Path(original_root).resolve()
    copy = Path(copy_root).resolve()
    patch = make_patch(original_root, copy_root)
    selected = [d for d in patch["files"] if files is None or d["path"] in files]
    backups, applied, failed = [], [], []

    backup_dir = orig / ".os" / "backups" / time.strftime("%Y%m%d-%H%M%S")
    actions = []
    for fd in selected:
        if fd["kind"] in ("modified", "added"):
            actions.append(("write", fd["path"]))
        elif fd["kind"] == "deleted":
            actions.append(("delete", fd["path"]))

    if dry_run:
        return {"dry_run": True, "would_apply": len(actions), "actions": actions, "patch": patch}

    # preflight: all targets writable / source readable
    for act, rel in actions:
        src = copy / rel if act == "write" else None
        dst = orig / rel
        if act == "write" and not (src and src.exists()):
            failed.append({"path": rel, "error": "source missing in copy"})
        if act == "delete" and not dst.exists():
            failed.append({"path": rel, "error": "target missing for delete"})
    if failed:
        return {"ok": False, "applied": [], "backups": [], "errors": failed}

    backup_dir.mkdir(parents=True, exist_ok=True)
    for act, rel in actions:
        dst = orig / rel
        bak = backup_dir / (rel.replace("/", "__") + ".bak")
        if dst.exists():
            shutil.copy2(dst, bak)  # record backup BEFORE mutation
            backups.append(str(bak))
        try:
            if act == "write":
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(copy / rel, dst)
            elif act == "delete":
                dst.unlink()
            applied.append(rel)
        except OSError as exc:
            failed.append({"path": rel, "error": str(exc)})

    # rollback on any failure
    if failed:
        for rel in reversed(applied):
            bak = backup_dir / (rel.replace("/", "__") + ".bak")
            dst = orig / rel
            try:
                if bak.exists():
                    shutil.copy2(bak, dst)
                else:
                    dst.unlink(missing_ok=True)
            except OSError:
                pass
        return {"ok": False, "applied": [], "backups": backups, "errors": failed,
                "rolled_back": True}

    return {"ok": True, "applied": applied, "backups": backups, "errors": []}