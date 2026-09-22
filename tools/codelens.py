"""Call graph + symbol reference lookup on top of the repoindex.

Deterministic, tree-sitter based. Not perfect (name-based resolution), but fast and reliable
enough for agent navigation. All functions read source files fresh from disk; no write.
"""

from __future__ import annotations

import os
from pathlib import Path

from repoindex import ts
from repoindex.store import IndexStore

MAX_REFERENCER_FILES = 4000


def _read(path: Path, root: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _owning_symbol(symbols: list[dict], line: int) -> dict | None:
    best = None
    for s in symbols:
        if s["start_line"] <= line <= s["end_line"]:
            if best is None or (s["end_line"] - s["start_line"]) < (
                best["end_line"] - best["start_line"]
            ):
                best = s
    return best


def _analyze_file(path: Path, root: Path, lang: str, symbols: list[dict]):
    """Yield (line, callee_name, owning_symbol) for every call site."""
    text = _read(path, root)
    if text is None:
        return
    tree = ts.parse_text(lang, text)
    if tree is None:
        return
    for line, name in ts.call_sites(tree, lang):
        yield line, name, _owning_symbol(symbols, line)


def callers(
    symbol: str,
    root: str | None = None,
    db: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Find every call site of `symbol` across the repo. Returns list of
    {file, line, from_func, from_kind}."""
    root_path = Path(root) if root else _default_root()
    store = IndexStore(db)
    results: list[dict] = []
    try:
        for file_row in store.list_files(limit=MAX_REFERENCER_FILES):
            fpath = root_path / file_row["path"]
            lang = file_row["lang"]
            symbols = store.symbols_in_file(file_row["path"])
            for line, name, owner in _analyze_file(fpath, root_path, lang, symbols):
                if name == symbol:
                    results.append({
                        "file": file_row["path"],
                        "line": line,
                        "from_func": owner and owner["name"],
                        "from_kind": owner and owner["kind"],
                    })
                    if len(results) >= limit:
                        return results
    finally:
        store.close()
    results.sort(key=lambda r: (r["file"], r["line"]))
    return results


def references(
    symbol: str,
    root: str | None = None,
    db: str | None = None,
    limit: int = 300,
) -> list[dict]:
    """Definitions + call sites of `symbol`. Each entry: {kind, file, line}."""
    root_path = Path(root) if root else _default_root()
    store = IndexStore(db)
    out: list[dict] = []
    try:
        # definitions from the index
        for row in store.search_symbols(symbol, limit=limit):
            if row["name"] == symbol:
                out.append({
                    "kind": row["kind"],
                    "file": row["path"],
                    "line": row["start_line"],
                })
        # call sites
        for call in callers(symbol, root=str(root_path), db=db, limit=limit):
            if {"kind": "call", "file": call["file"], "line": call["line"]} not in out:
                out.append({"kind": "call", "file": call["file"], "line": call["line"]})
    finally:
        store.close()
    out.sort(key=lambda r: (r["file"], r["line"]))
    return out[:limit]


def callees(
    symbol: str,
    root: str | None = None,
    db: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Distinct downstream calls inside `symbol`'s body. Entry: {name, file, first_line}."""
    root_path = Path(root) if root else _default_root()
    store = IndexStore(db)
    try:
        # locate the definition
        candidates = [
            r for r in store.search_symbols(symbol, limit=20) if r["name"] == symbol
        ]
        if not candidates:
            return []
        target = candidates[0]
        fpath = root_path / target["path"]
        lang = store.file_detail(target["path"])["lang"]
        text = _read(fpath, root_path)
        if text is None:
            return []
        tree = ts.parse_text(lang, text)
        if tree is None:
            return []
        ignored = ts.IGNORED_CALLEES.get(lang, set())
        within = {
            (line, name)
            for line, name in ts.call_sites(tree, lang)
            if target["start_line"] <= line <= target["end_line"]
        }
        seen: dict[str, int] = {}
        for line, name in within:
            if name in ignored:
                continue
            seen.setdefault(name, line)
        return [
            {"name": name, "file": target["path"], "first_line": ln}
            for name, ln in seen.items()
        ][:limit]
    finally:
        store.close()


def _default_root() -> Path:
    env = os.environ.get("REPO_ROOT")
    if env and os.path.isdir(env):
        return Path(env)
    return Path(__file__).resolve().parent.parent