# AGENTS.md

Machine-readable conventions for any agent operating in this repo.

## Layout
- `freeworker/` — Python MCP control plane (FastMCP stdio), shells out to `opencode run`.
- `freeworker/dispatch.py` — shared runner for opencode free workers (prompt piped via stdin;
  do NOT pass it as an argv arg — Windows 32K limit).
- `repoindex/` — M1 ingestion engine: tree-sitter symbol extraction, chunking, SQLite store,
  ingest/query/summarize CLIs, and the `repoindex` MCP server (query tools for Claude).
- `repoindex/ts.py` — shared tree-sitter wiring: language registry, parsing, call-site queries.
- `tools/` — M2 tool system + M3 loop + M4 loop + M5 bridge: `codelens.py` (call graph),
  `relevant.py` (issue→files), `packer.py` (bounded sanitized context), `gitops.py` (structured git),
  `plan.py` (plan ledger), `looper.py` (tier-aware executor), `testloop.py` (JUnit-structure parse +
  fix-retry), `diffpatch.py` (copy-vs-tree diff + safe apply), and the `toolbox` MCP server
  (read-only against the real tree by design).
- `sandbox/` — M4 isolation: `runner.py` runs pytest via `docker run --rm` if Docker is available,
  else in a disposable repo copy under `.os/sandbox/`. Nothing here writes to the real repo.
- `tools/diffpatch.py` — M5 bridge: git-free unified diff of copy-vs-tree + whole-file apply with
  `.os/backups/` snapshots and rollback. Diffing is free; applying only AFTER reviewer APPROVE.
- `tools/eval.py` + `tools/metrics.py` — M6: seeded-bug suite driving M4→M5 per case (anti-gaming:
  test rewrites = FAIL; already-green = SKIP), JSONL ledger in `.os/metrics/` for reports.
- `tools/memory.py` + `tools/autopilot.py` — M7: durable JSONL memory journal (`.os/memory/`) with
  `recall`/`session_primer`; autopilot chains plan→loop→test→apply→metrics→memory in one call.
- `.claude/agents/` — Claude Code subagents (planner/builder/debugger/reviewer).
- `.claude/hooks/` — event log hook (PowerShell).
- `.os/` — runtime data (index.db, plans/, event logs; gitignored).

## Conventions
- Code: Python 3.14 available via `py -3.14` (plain `python` NOT on PATH).
- Prefer rg over grep; use the freeworker MCP for bulk LLM work; do not force-fit an LLM.
- After any design change, append a dated entry to the Decisions log in CLAUDE.md.

## Free model ids (subject to change; confirm with `opencode models`)
- `opencode/big-pickle`, `opencode/ox-alpha-free`, `opencode/mimo-v2.5-free`,
  `opencode/nemotron-3-ultra-free`, `opencode/nemotron-3.5-lightning-free`,
  `opencode/hy3-free`, `opencode/ling-3.0-flash-fin-free`.

## Hooks
`.claude/settings.json` → PostToolUse(Edit|Write) and Stop call `.claude/hooks/log-event.ps1`,
which appends the event JSON to `.os/runs/events-YYYYMMDD.jsonl`.