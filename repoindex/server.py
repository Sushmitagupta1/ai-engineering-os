"""repoindex MCP server — query tools for Claude Code over the SQLite index.
Run: <venv python> -u repoindex/server.py   (registered in .mcp.json)
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache, wraps
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP

from repoindex.store import IndexStore, default_db

mcp = FastMCP("repoindex")


@lru_cache(maxsize=1)
def _store(db: str | None = None) -> IndexStore:
    return IndexStore(db or default_db())


class DBError(Exception):
    pass


def _guard(fn):
    @wraps(fn)
    def wrap(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            raise DBError(str(exc)) from exc
    return wrap


@_guard
def _index_path(db: str | None) -> str:
    s = _store(db)
    return str(s.path)


@mcp.tool()
@_guard
def repoindex_stats(db: str | None = None) -> dict:
    """Index statistics: file/symbol/chunk counts and total size."""
    return _store(db).file_stats()


@mcp.tool()
@_guard
def repoindex_search_symbols(term: str, limit: int = 50, db: str | None = None) -> list[dict]:
    """Search indexed symbols by name (case-insensitive substring). Returns name, kind, lines, signature, file."""
    return [dict(r) for r in _store(db).search_symbols(term, limit)]


@mcp.tool()
@_guard
def repoindex_list_files(lang: str | None = None, limit: int = 200, db: str | None = None) -> list[dict]:
    """List indexed files, optionally filtered by language (python, javascript, typescript, bash, ...)."""
    return [dict(r) for r in _store(db).list_files(lang, limit)]


@mcp.tool()
@_guard
def repoindex_file_symbols(path: str, db: str | None = None) -> dict:
    """All symbols (with line ranges) for one indexed file path, plus file metadata."""
    store = _store(db)
    detail = store.file_detail(path)
    if not detail:
        return {"error": f"not indexed: {path}"}
    return {
        "file": dict(detail),
        "symbols": [dict(r) for r in store.symbols_in_file(path)],
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")