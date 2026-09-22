# AI Engineering OS

A **full AI software-engineering agent** that plans tasks, writes code, debugs, runs and
fixes tests, reviews its own work, and remembers lessons learned — all autonomously.

It is built as **three standalone MCP servers**, so you can plug it into **any**
MCP-capable app (Claude Code, opencode, Cursor, VS Code, Claude Desktop, ...). No
vendor lock-in.

It uses **free models** for bulk work to keep costs near zero, and runs entirely on
your own machine.

---

## What it does

| Capability | How |
|---|---|
| Understand code | tree-sitter symbol extraction + SQLite index (`repoindex`) |
| Plan work | plan ledger with tiered tasks (`toolbox`) |
| Write code | free-model workers via `opencode run` (`freeworker`) |
| Test safely | pytest in a disposable sandbox copy — real tree is never touched |
| Fix bugs on its own | test → see failure → fix in copy → retest, up to N iterations |
| Review before applying | copy-vs-tree unified diff, reviewer approves, then safe apply with backups |
| Learn | durable memory journal: decisions, facts, lessons; recall by keyword |
| Measure itself | seeded-bug eval suite + metrics ledger with pass rates |

---

## The three MCP servers

| Server | Purpose |
|---|---|
| **`freeworker`** | Dispatch bulk/mechanical tasks to free opencode Zen models |
| **`repoindex`** | Code intelligence: symbols, call sites, file list (offline, tree-sitter) |
| **`toolbox`** | Planning, sandbox, diff/apply, eval, metrics, memory, autopilot |

### freeworker tools

- `free_run` — run any bulk/mechanical task on a free model
- `free_summarize` — summarize a single file quickly
- `free_scaffold` — scaffold boilerplate into a directory
- `list_free_models` — list the free model IDs available

### repoindex tools

- `repoindex_file_symbols` — symbols in a file
- `repoindex_list_files` — indexed files
- `repoindex_search_symbols` — search symbols by name
- `repoindex_stats` — index health

### toolbox tools (24)

- **Planning:** `toolbox_plan_create`, `toolbox_plan_add_task`, `toolbox_plan_run`,
  `toolbox_plan_advance_task`, `toolbox_plan_status`
- **Sandbox:** `toolbox_sandbox_status`, `toolbox_test_loop`
- **Apply:** `toolbox_sandbox_diff`, `toolbox_sandbox_apply`
- **Eval & metrics:** `toolbox_eval_run`, `toolbox_metrics_report`
- **Memory:** `toolbox_memory_add`, `toolbox_memory_recall`, `toolbox_session_primer`
- **Automation:** `toolbox_autopilot`
- **Plus** lower-level loop/ledger/index helpers

---

## How it works (the workflow)

```
1. PLAN      → plan ledger created, tasks tagged by tier
2. EXECUTE   → free/toolbox tiers run automatically; judgment tasks run by you
3. TEST      → code copied into a sandbox, pytest runs there
4. FIX       → failures fed to a free worker, who fixes the COPY (never the real tree)
5. RETEST    → repeat until green or iteration limit
6. REVIEW    → unified diff of copy vs real tree for approval
7. APPLY     → approved changes copied back with .os/backups snapshot (rollback-safe)
8. MEASURE   → metrics ledger records the run
9. REMEMBER  → lessons written to memory journal
```

One call does all of it: `toolbox_autopilot`.

---

## Requirements

- **Python 3.11+**
- (Optional) **opencode CLI** — only needed by `freeworker` to reach free models
- (Optional) **Docker** — sandbox uses it if available; otherwise falls back to a
  disposable local copy

## Install

```bash
git clone https://github.com/Sushmitagupta1/ai-engineering-os.git
cd ai-engineering-os
python -m venv .venv

# Windows:
.venv\Scripts\python.exe -m pip install -r requirements.txt
# macOS/Linux:
source .venv/bin/activate && pip install -r requirements.txt
```

For `freeworker` (free models):

```bash
npm i -g opencode-ai
opencode
```

---

## Connect the MCP servers

Adjust the `python` path to point at your venv.

### Claude Code — `.mcp.json` (already in the repo)

```json
{
  "mcpServers": {
    "freeworker": {
      "command": "<repo>/.venv/bin/python",
      "args": ["-u", "<repo>/freeworker/server.py"]
    },
    "repoindex": {
      "command": "<repo>/.venv/bin/python",
      "args": ["-u", "<repo>/repoindex/server.py"]
    },
    "toolbox": {
      "command": "<repo>/.venv/bin/python",
      "args": ["-u", "<repo>/tools/server.py"]
    }
  }
}
```

### opencode — `opencode.json` (already in the repo)

```json
{
  "mcp": {
    "freeworker": { "type": "local", "command": ["<repo>/.venv/bin/python", "-u", "<repo>/freeworker/server.py"] },
    "repoindex":  { "type": "local", "command": ["<repo>/.venv/bin/python", "-u", "<repo>/repoindex/server.py"] },
    "toolbox":    { "type": "local", "command": ["<repo>/.venv/bin/python", "-u", "<repo>/tools/server.py"] }
  }
}
```

### Any other MCP client

Add three **stdio** servers:

| Name | Command | Args |
|---|---|---|
| `freeworker` | `<repo>/.venv/bin/python` | `-u`, `<repo>/freeworker/server.py` |
| `repoindex` | `<repo>/.venv/bin/python` | `-u`, `<repo>/repoindex/server.py` |
| `toolbox` | `<repo>/.venv/bin/python` | `-u`, `<repo>/tools/server.py` |

On Windows use `<repo>\.venv\Scripts\python.exe`.

---

## First steps

1. Index a project:
   ```bash
   python repoindex/ingest.py ../../path/to/project
   ```
2. In your connected app, ask your agent to:
   - Run `toolbox_session_primer` to load context
   - Run `toolbox_plan_create` to start planning a task
   - Or run the whole loop in one go with `toolbox_autopilot`

---

## Repository layout

```
freeworker/   MCP control plane that shells out to `opencode run` (free models)
repoindex/    M1 code-intelligence engine: tree-sitter extraction, SQLite store, MCP + CLI
sandbox/      M4 isolation: pytest in Docker (or a disposable copy), never the real tree
tools/        M2-M7: plan ledger, looper, test loop, diff/apply, eval, metrics, memory, autopilot
.claude/      subagent definitions (planner/builder/debugger/reviewer) + event hook
.opencode/    (optional) opencode agent definitions
.os/          runtime data (index.db, plans, metrics, memory — gitignored)
```

---

## Runtime data

All state lives in `.os/` (gitignored):

- `index.db` — repoindex SQLite store
- `plans/` — plan ledgers
- `sandbox/` — disposable fix-loop copies
- `backups/` — pre-apply snapshots for rollback
- `metrics/` — eval ledger (JSONL)
- `memory/` — durable journal (JSONL)

---

## Project history

Built in milestones (M0–M7):

- **M0** — harness + subagents setup
- **M1** — repoindex code intelligence
- **M2** — tool system (codelens, relevant, packer, gitops)
- **M3** — plan ledger + tiered loop
- **M4** — sandboxed test/fix loop
- **M5** — reviewer bridge (diff + safe apply)
- **M6** — eval harness + metrics
- **M7** — memory + autopilot

---

## License

MIT — free to use, modify, and share.