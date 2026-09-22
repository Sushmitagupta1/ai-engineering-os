"""SQLite index store for repoindex."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE,
    lang TEXT,
    loc INTEGER,
    size INTEGER,
    mtime REAL,
    summary TEXT,
    indexed_at TEXT
);
CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY,
    file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
    name TEXT,
    kind TEXT,
    start_line INTEGER,
    end_line INTEGER,
    signature TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
    start_line INTEGER,
    end_line INTEGER,
    summary TEXT
);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id);
CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id);
"""

_DEFAULT_DB = os.environ.get("REPOINDEX_DB", "")


def default_db() -> str:
    if _DEFAULT_DB:
        return _DEFAULT_DB
    return str(Path(__file__).resolve().parent.parent / ".os" / "index.db")


class IndexStore:
    def __init__(self, db_path: str | os.PathLike | None = None):
        self.path = str(db_path or default_db())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # ---- files ----
    def upsert_file(
        self, path: str, lang: str, loc: int, size: int, mtime: float
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.execute(
            """INSERT INTO files(path, lang, loc, size, mtime, indexed_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(path) DO UPDATE SET
                 lang=excluded.lang, loc=excluded.loc, size=excluded.size,
                 mtime=excluded.mtime, indexed_at=excluded.indexed_at""",
            (path, lang, loc, size, mtime, now),
        )
        return cur.lastrowid or self.file_id(path)

    def file_id(self, path: str) -> int:
        row = self.conn.execute("SELECT id FROM files WHERE path=?", (path,)).fetchone()
        return row["id"] if row else 0

    def file_stats(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
        symbols = self.conn.execute("SELECT COUNT(*) c FROM symbols").fetchone()["c"]
        chunks = self.conn.execute("SELECT COUNT(*) c FROM chunks").fetchone()["c"]
        size = self.conn.execute("SELECT COALESCE(SUM(size),0) s FROM files").fetchone()["s"]
        return {"files": total, "symbols": symbols, "chunks": chunks, "size_bytes": size}

    # ---- symbols ----
    def replace_symbols(self, file_id: int, syms: Iterable[dict]) -> None:
        self.conn.execute("DELETE FROM symbols WHERE file_id=?", (file_id,))
        self.conn.executemany(
            """INSERT INTO symbols(file_id, name, kind, start_line, end_line, signature)
               VALUES(?,?,?,?,?,?)""",
            [
                (file_id, s["name"], s["kind"], s["start_line"], s["end_line"], s["signature"])
                for s in syms
            ],
        )

    # ---- chunks ----
    def set_chunk_summary(self, file_id: int, start_line: int, end_line: int, summary: str) -> None:
        row = self.conn.execute(
            "SELECT id FROM chunks WHERE file_id=? AND start_line=? AND end_line=?",
            (file_id, start_line, end_line),
        ).fetchone()
        if row:
            self.conn.execute(
                "UPDATE chunks SET summary=? WHERE id=?", (summary, row["id"])
            )
        else:
            self.conn.execute(
                "INSERT INTO chunks(file_id, start_line, end_line, summary) VALUES(?,?,?,?)",
                (file_id, start_line, end_line, summary),
            )

    def replace_chunks(self, file_id: int, info: Iterable[tuple[int, int, str]]) -> None:
        self.conn.execute("DELETE FROM chunks WHERE file_id=?", (file_id,))
        self.conn.executemany(
            "INSERT INTO chunks(file_id, start_line, end_line, summary) VALUES(?,?,?,?)",
            [(file_id, a, b, s) for a, b, s in info],
        )

    def missing_chunk_summaries(self, limit: int = 500) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT c.id, c.file_id, c.start_line, c.end_line, f.path, f.lang
               FROM chunks c JOIN files f ON f.id=c.file_id
               WHERE c.summary IS NULL OR c.summary=''
               ORDER BY c.id LIMIT ?""",
            (limit,),
        ).fetchall()

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---- queries ----
    def search_symbols(self, term: str, limit: int = 50) -> list[sqlite3.Row]:
        like = f"%{term}%"
        return self.conn.execute(
            """SELECT s.name, s.kind, s.start_line, s.end_line, s.signature, f.path
               FROM symbols s JOIN files f ON f.id=s.file_id
               WHERE s.name LIKE ? OR f.path LIKE ?
               ORDER BY s.name LIMIT ?""",
            (like, like, limit),
        ).fetchall()

    def symbols_in_file(self, path: str) -> list[sqlite3.Row]:
        fid = self.file_id(path)
        if not fid:
            return []
        return self.conn.execute(
            "SELECT name, kind, start_line, end_line, signature FROM symbols WHERE file_id=? ORDER BY start_line",
            (fid,),
        ).fetchall()

    def list_files(self, lang: str | None = None, limit: int = 500) -> list[sqlite3.Row]:
        if lang:
            return self.conn.execute(
                "SELECT path, lang, loc, size FROM files WHERE lang=? ORDER BY path LIMIT ?",
                (lang, limit),
            ).fetchall()
        return self.conn.execute(
            "SELECT path, lang, loc, size FROM files ORDER BY path LIMIT ?", (limit,)
        ).fetchall()

    def file_detail(self, path: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM files WHERE path=?",
            (path,),
        ).fetchone()