"""Context packer + secret sanitizer.

Builds a bounded, sanitized markdown pack of selected files (symbol tables from the index,
body truncated or focused to given symbols) for use in worker prompts / context windows.
"""

from __future__ import annotations

import re
from pathlib import Path

from repoindex.store import IndexStore

SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd|private[_-]?key|authorization)\b\s*[:=]\s*['\"][^'\"]+['\"]"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"(?i)\b(bearer|basic)\s+[a-z0-9._~+/-]+=*", re.I),
]

# also scrub known env-style lears in one pass below


def sanitize(text: str) -> str:
    if not text:
        return text
    for pat in SECRET_PATTERNS:
        text = pat.sub("***REDACTED***", text)
    return text


def pack(
    paths: list[str],
    root: str | None = None,
    db: str | None = None,
    focus_symbols: list[str] | None = None,
    max_lines: int = 300,
    include_symbol_table: bool = True,
) -> dict:
    root_path = Path(root) if root else _default_root()
    store = IndexStore(db)
    sections: list[dict] = []
    total_chars = 0
    for rel in paths:
        fpath = root_path / rel
        if not fpath.is_file():
            sections.append({"file": rel, "error": "file not found in repo root"})
            continue
        detail = store.file_detail(rel)
        symbols = store.symbols_in_file(rel) if detail else []
        try:
            lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            sections.append({"file": rel, "error": "unreadable"})
            continue

        body: list[str] = []
        if focus_symbols:
            focus = [s for s in symbols if s["name"] in focus_symbols]
            if focus:
                kept_lines: set[int] = set()
                for s in focus:
                    kept_lines.update(range(s["start_line"], min(s["end_line"] + 1, len(lines) + 1)))
                body = [f"{i + 1}| {ln}" for i, ln in enumerate(lines) if (i + 1) in kept_lines]
            else:
                body = [f"{i + 1}| {ln}" for i, ln in enumerate(lines[:max_lines])]
        else:
            if len(lines) > max_lines:
                body = [f"{i + 1}| {ln}" for i, ln in enumerate(lines[:max_lines])]
                body.append(f"... ({len(lines) - max_lines} more lines)")
            else:
                body = [f"{i + 1}| {ln}" for i, ln in enumerate(lines)]

        table = ""
        if include_symbol_table and symbols:
            rows = [
                f"- {s['name']} ({s['kind']}) lines {s['start_line']}-{s['end_line']}"
                for s in symbols[:60]
            ]
            table = "### symbols\n" + "\n".join(rows) + "\n"

        section = table + "\n" + "\n".join(body)
        section = sanitize(section)
        sections.append({
            "file": rel,
            "lang": detail["lang"] if detail else "?",
            "loc": detail["loc"] if detail else len(lines),
            "chars": len(section),
            "text": section,
        })
        total_chars += len(section)

    store.close()
    output = "\n\n".join(
        f"== file: {s['file']} ==\n" + (s.get("text") or s.get("error", ""))
        for s in sections
    )
    return {
        "files": len(sections),
        "total_chars": total_chars,
        "sections": sections,
        "output": output,
    }


def _default_root() -> Path:
    import os
    env = os.environ.get("REPO_ROOT")
    if env and os.path.isdir(env):
        return Path(env)
    return Path(__file__).resolve().parent.parent