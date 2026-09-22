"""Ingest a repository into the SQLite index.

python -m repoindex.ingest <repo-or-dir> [--db PATH]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from repoindex import chunk as chunker
from repoindex import langs
from repoindex.store import IndexStore
from repoindex.symbols import extract_symbols

MAX_FILE_BYTES = 2 * 1024 * 1024  # skip files > 2MB


def walk_repo(root: str | Path) -> list[Path]:
    root = Path(root)
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in langs.IGNORED_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            if langs.is_indexable(p):
                files.append(p)
    return sorted(files)


def ingest(repo: str | Path, db_path: str | None = None) -> dict:
    repo = Path(repo)
    store = IndexStore(db_path)
    files = walk_repo(repo)
    indexed = 0
    skipped = 0
    for f in files:
        try:
            stat = f.stat()
        except OSError:
            skipped += 1
            continue
        if stat.st_size > MAX_FILE_BYTES:
            skipped += 1
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped += 1
            continue
        lang = langs.lang_for(f) or ""
        rel = str(f.relative_to(repo)).replace("\\", "/")
        fid = store.upsert_file(rel, lang, len(text.splitlines()), stat.st_size, stat.st_mtime)
        syms = extract_symbols(lang, text)
        store.replace_symbols(fid, [s.to_dict() for s in syms])
        chunks = chunker.chunk_text(text, syms)
        store.replace_chunks(fid, [(c.start_line, c.end_line, "") for c in chunks])
        indexed += 1

    store.commit()
    stats = store.file_stats()
    store.close()
    return {"repo": str(repo), "indexed_files": indexed, "skipped": skipped, **stats}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ingest a repository into the repoindex")
    ap.add_argument("repo", help="repository or directory to index")
    ap.add_argument("--db", default=None, help="sqlite path (default .os/index.db)")
    args = ap.parse_args(argv)
    if not Path(args.repo).is_dir():
        print(f"error: not a directory: {args.repo}", file=sys.stderr)
        return 2
    result = ingest(args.repo, args.db)
    print(
        f"indexed {result['indexed_files']} files "
        f"({result['files']} stored, {result['symbols']} symbols, {result['chunks']} chunks, "
        f"{result['size_bytes']//1024} KiB total)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())