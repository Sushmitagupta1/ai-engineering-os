"""Semantic-free chunking of source files by lines, aligned to symbol boundaries."""

from __future__ import annotations

from dataclasses import dataclass

from repoindex.symbols import Symbol


@dataclass
class Chunk:
    start_line: int
    end_line: int
    text: str


def chunk_text(source_text: str, symbols: list[Symbol], max_lines: int = 200) -> list[Chunk]:
    lines = source_text.splitlines()
    total = len(lines)
    if total == 0:
        return []
    bounds = [1]
    for s in sorted(symbols, key=lambda s: s.start_line):
        if 1 < s.start_line <= total:
            bounds.append(s.start_line)
    bounds.append(total + 1)
    bounds = sorted(set(bounds))

    chunks: list[Chunk] = []
    cur_start = bounds[0]
    cur_end = bounds[0]
    for b in bounds[1:]:
        span = b - cur_start
        if span >= max_lines and cur_end > cur_start:
            chunks.append(Chunk(cur_start, cur_end - 1, "\n".join(lines[cur_start - 1:cur_end])))
            cur_start = cur_end
            cur_end = b
        else:
            cur_end = b
    if cur_end > cur_start:
        chunks.append(Chunk(cur_start, cur_end - 1, "\n".join(lines[cur_start - 1:cur_end])))
    return chunks