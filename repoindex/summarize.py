"""Enrich chunks with free-model summaries via the shared opencode dispatch.

Used separately from ingestion so M1 core works offline; run it to give Claude
cheap pre-digested per-file/chunk context.

python -m repoindex.summarize [--db PATH] [--model opencode/big-pickle] [--limit N]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from freeworker.dispatch import run_opencode
from repoindex.store import IndexStore

PROMPT_TEMPLATE = (
    "Below is chunk {start}-{end} of file {path} (language {lang}). "
    "Return a terse one-paragraph summary: purpose, key symbols, external deps touched, "
    "anything risky or surprising. Do not add speculation.\n\n"
    "---FILE CONTENT---\n{body}\n---END---"
)

BATCH_SIZE = 8


def summarize(db_path: str | None, model: str, limit: int, dry_run: bool = False) -> dict:
    store = IndexStore(db_path)
    try:
        pending = store.missing_chunk_summaries(limit)
        done = 0
        failed = 0
        for row in pending:
            content = _read_chunk(store, row)
            if dry_run:
                print(f"[dry-run] would summarize {row['path']}:{row['start_line']}-{row['end_line']} "
                      f"({row['lang']})")
                continue
            prompt = PROMPT_TEMPLATE.format(
                start=row["start_line"],
                end=row["end_line"],
                path=row["path"],
                lang=row["lang"],
                body=content,
            )
            try:
                out = run_opencode(model, prompt, str(Path(__file__).resolve().parent.parent), 600)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"  [fail] {row['path']}:{row['start_line']} -> {exc}", file=sys.stderr)
                continue
            store.set_chunk_summary(row["file_id"], row["start_line"], row["end_line"], out)
            done += 1
            print(f"  [ok] {row['path']}:{row['start_line']}-{row['end_line']} ({len(out)} chars)")
        store.commit()
        return {"done": done, "failed": failed, "pending": len(pending)}
    finally:
        store.close()


def _read_chunk(store: IndexStore, row) -> str:
    detail = store.file_detail(row["path"])
    if not detail:
        return ""
    root = Path(__file__).resolve().parent.parent
    path = root / row["path"]
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[row["start_line"] - 1: row["end_line"]])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="summarize unmatched chunks with a free model")
    ap.add_argument("--db", default=None)
    ap.add_argument("--model", default="opencode/big-pickle")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    res = summarize(args.db, args.model, args.limit, args.dry_run)
    print(f"summarized {res['done']}, failed {res['failed']}, leftover {res['pending']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())