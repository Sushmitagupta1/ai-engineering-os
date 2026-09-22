"""Relevant-file discovery for a natural-language issue / query.

Scores indexed files by symbol-name matches, path matches, and free-model chunk summaries.
Deterministic first pass; cheap enough that Claude calls it instead of guessing file lists.
"""

from __future__ import annotations

import re
from pathlib import Path

from repoindex.store import IndexStore

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "with", "at", "by",
    "this", "that", "it", "is", "are", "was", "be", "as", "from", "into", "about",
    "should", "would", "could", "can", "will", "using", "use", "we", "our", "fix",
    "add", "issue", "file", "code", "also", "so", "if", "then", "there", "please",
    "bug", "does", "do", "not", "how", "what", "when", "my", "new", "get", "set",
}

_TOKEN = re.compile(r"[a-z0-9_\u2a2f\d<>]+[a-zA-Z0-9_]*|[a-zA-Z_][a-zA-Z0-9_]*")


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if len(t) > 2 and t not in STOPWORDS]


def relevant_files(
    query: str,
    root: str | None = None,
    db: str | None = None,
    topk: int = 8,
    min_score: float = 1.0,
) -> list[dict]:
    terms = tokenize(query)
    if not terms:
        return []
    store = IndexStore(db)
    try:
        rows = []
        for file_row in store.list_files():
            path = file_row["path"]
            symbols = store.symbols_in_file(path)
            summaries = _chunk_summaries(store, path)
            path_l = path.lower()
            score = 0.0
            matched_symbols: list[str] = []
            for term in terms:
                hit_sym = False
                for s in symbols:
                    if term in s["name"].lower():
                        score += 3.0
                        hit_sym = True
                        if s["name"] not in matched_symbols:
                            matched_symbols.append(s["name"])
                if term in path_l:
                    score += 2.0
                for summ in summaries:
                    if term in summ.lower():
                        score += 1.0
                        break
                if hit_sym:
                    score += 0.0
            if score >= min_score:
                rows.append({
                    "path": path,
                    "score": round(score, 2),
                    "lang": file_row["lang"],
                    "loc": file_row["loc"],
                    "matched_symbols": matched_symbols,
                })
        rows.sort(key=lambda r: -r["score"])
        return rows[:topk]
    finally:
        store.close()


def _chunk_summaries(store: IndexStore, path: str) -> list[str]:
    fid = store.file_id(path)
    if not fid:
        return []
    rows = store.conn.execute(
        "SELECT summary FROM chunks WHERE file_id=? AND summary IS NOT NULL AND summary<>''",
        (fid,),
    ).fetchall()
    return [r["summary"] for r in rows]