# AI Engineering OS

Cost-aware hierarchical AI software-engineering system. A judgment brain supervises a
pool of free model workers, orchestrated through three standalone MCP servers. The MCP
servers are client-agnostic — connect them from **any** MCP-capable app (Claude Code,
opencode, Cursor, VS Code, Claude Desktop, ...).

## The three MCP servers

| Server | Purpose | Tools |
|---|---|---|
| `freeworker` | Dispatch bulk/mechanical tasks to free opencode models via `opencode run` | `free_run`, `free_summarize`, `free_scaffold`, `list_free_models` |
| `repoindex` | Code intelligence via tree-sitter: symbols, call sites, file list | `repoindex_file_symbols`, `repoindex_list_files`, `repoindex_search_symbols`, `repoindex_stats` |
| `toolbox` | Planning, sandboxed test loop, diff/apply, eval, metrics, memory, autopilot | 24 tools: plan*, sandbox*, test loop, diff/apply, eval, metrics, memory, autopilot |

Everything runs locally. `toolbox` and `repoindex` are fully offline/deterministic; only
`freeworker` needs the `opencode` CLI to reach free models.

## Install

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\python.exe -m pip install -r requirements.txt
# macOS/Linux:
source .venv/bin/activate && pip install -r requirements.txt
```

(Optional, for `freeworker` only) install the opencode CLI and log in:
```bash
npm i -g opencode-ai
opencode
```

## Connect the MCP servers (any client)

Register these three stdio servers in your client's MCP settings. Adjust the `python`
path to your venv.

### Claude Code — `.mcp.json` (already provided)

```json
{
  "mcpServers": {
    "freeworker": {
      "command": "<repo>/.venv/bin/python",
      "args": ["-u", "<repo>/freeworker/server.py"],
      "env": {}
    },
    "repoindex": {
      "command": "<repo>/.venv/bin/python",
      "args": ["-u", "<repo>/repoindex/server.py"],
      "env": {}
    },
    "toolbox": {
      "command": "<repo>/.venv/bin/python",
      "args": ["-u", "<repo>/tools/server.py"],
      "env": {}
    }
  }
}
```

### opencode — `opencode.json` (already provided)

```json
{
  "mcp": {
    "freeworker": { "type": "local", "command": ["<repo>/.venv/bin/python", "-u", "<repo>/freeworker/server.py"] },
    "repoindex":  { "type": "local", "command": ["<repo>/.venv/bin/python", "-u", "<repo>/repoindex/server.py"] },
    "toolbox":    { "type": "local", "command": ["<repo>/.venv/bin/python", "-u", "<repo>/tools/server.py"] }
  }
}
```

### Any other client

Add three stdio MCP servers with this shape (VS Code, Cursor, Claude Desktop, etc.):

| Name | Command | Args |
|---|---|---|
| `freeworker` | `<repo>/.venv/bin/python` | `-u`, `<repo>/freeworker/server.py` |
| `repoindex` | `<repo>/.venv/bin/python` | `-u`, `<repo>/repoindex/server.py` |
| `toolbox` | `<repo>/.venv/bin/python` | `-u`, `<repo>/tools/server.py` |

On Windows use `<repo>\.venv\Scripts\python.exe`.

## First steps

1. Index the codebase for `repoindex`: run `repoindex/ingest.py ../../path/to/project`.
2. Ask the connected client to use `toolbox_session_primer` → `toolbox_plan_create`, or just
   run a full job with `toolbox_autopilot`.

## Layout

```
freeworker/   MCP control plane that shells out to `opencode run` (free models)
repoindex/    M1 code-intelligence engine: tree-sitter extraction, SQLite store, MCP + CLI
sandbox/      M4 isolation: pytest in Docker (or a disposable copy), never the real tree
tools/        M2-M7: plan ledger, looper, test loop, diff/apply, eval, metrics, memory, autopilot
.claude/      subagent definitions (Claude Code: planner/builder/debugger/reviewer) + hook
.os/          runtime data (index.db, plans, metrics, memory — gitignored)
```

## Runtime data

All state lives in `.os/` (gitignored): `index.db`, `plans/`, `sandbox/`, `backups/`,
`metrics/`, `memory/`.