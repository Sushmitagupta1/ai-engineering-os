"""Query the repoindex.

python -m repoindex.query <lookup> [--db PATH]        e.g. repoindex.query name search_term
E.g. `python -m repoindex.query symbol append_data`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from repoindex.store import IndexStore


def _dump(rows, count: int | None = None) -> None:
    data = [dict(r) for r in rows]
    if count is not None:
        data = data[:count]
    print(json.dumps(data, indent=1, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="query the repoindex")
    ap.add_argument("--db", default=None, help="sqlite path (default .os/index.db)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("symbols", help="search symbols by name (fuzzy substring)")
    p.add_argument("term")
    p.add_argument("--limit", type=int, default=50)

    p = sub.add_parser("files", help="list indexed files")
    p.add_argument("--lang")
    p.add_argument("--limit", type=int, default=500)

    p = sub.add_parser("file", help="detail (symbols) for one path")
    p.add_argument("path")

    p = sub.add_parser("stats", help="index statistics")

    args = ap.parse_args(argv)
    store = IndexStore(args.db)
    try:
        if args.cmd == "symbols":
            _dump(store.search_symbols(args.term, args.limit))
        elif args.cmd == "files":
            _dump(store.list_files(getattr(args, "lang", None), args.limit))
        elif args.cmd == "file":
            detail = store.file_detail(args.path)
            if not detail:
                print(json.dumps({"error": "not found"}))
            else:
                syms = store.symbols_in_file(args.path)
                _dump([detail] + syms)
        elif args.cmd == "stats":
            print(json.dumps(store.file_stats(), indent=1))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())