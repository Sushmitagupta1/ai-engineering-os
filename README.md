# AI Engineering OS

A **full AI software-engineering agent** that plans tasks, writes code, debugs, runs and
fixes tests, reviews its own work, and remembers lessons learned — all autonomously.

Built as **three standalone MCP servers**, so you can plug it into **any** MCP-capable
app (Claude Code, opencode, Cursor, VS Code, Claude Desktop, ...). No vendor lock-in.

It uses **free models** for bulk work to keep costs near zero, and runs entirely on
your own machine.

---

## Table of contents

- [Mission](#mission)
- [How it works](#how-it-works-the-workflow)
- [Cost policy](#cost-policy-the-core-rule)
- [The three MCP servers](#the-three-mcp-servers)
- [MCP tools in detail](#mcp-tools-in-detail)
- [Capabilities](#capabilities)
- [Install](#install)
- [Connect the MCP servers](#connect-the-mcp-servers)
- [First steps](#first-steps)
- [CLI commands](#cli-commands)
- [Protocols](#protocols)
- [Milestones & history](#milestones--history)
- [Decisions log](#decisions-log)
- [Repository layout](#repository-layout)
- [Runtime data](#runtime-data)
- [Requirements](#requirements)
- [License](#license)

---

## Mission

Turn a GitHub issue into a merged, tested PR at **minimum cost**:
free and deterministic workers do the bulk + mechanical work; a judgment brain
makes every judgment call.

## How it works (the workflow)

```
 1. PLAN      -> plan ledger created, tasks tagged by tier
 2. EXECUTE   -> free/toolbox tiers run automatically; judgment tasks run by you
 3. TEST      -> code copied into a sandbox, pytest runs there
 4. FIX       -> failures fed to a free worker, who fixes the COPY (never the real tree)
 5. RETEST    -> repeat until green or iteration limit
 6. REVIEW    -> unified diff of copy vs real tree for approval
 7. APPLY     -> approved changes copied back with .os/backups snapshot (rollback-safe)
 8. MEASURE   -> metrics ledger records the run
 9. REMEMBER  -> lessons written to memory journal
```

One call does all of it: `toolbox_autopilot`.

---

## Cost policy (the core rule)

Use the cheapest system capable of reliably completing each task:

| Task type | Owner |
|---|---|
| Architectural / security / root-cause / design choice | Judgment brain (Opus tier) |
| Clearly-scoped implementation, tests from spec | Implementation tier (Sonnet tier) |
| Triage, chunking, summarising, boilerplate, codegen drafts | free Zen worker (`freeworker`) |
| Grep, reformat, patch, git status/log, file discovery | deterministic tools (rg, git, ruff) — NO LLM |

Hard rules:

1. **Judgment is never delegated to free models.** A free-model answer that feeds a
   decision must be cheaply verified by the judgment brain before it acts on it.
2. **Never leak secrets into prompts.** Workers get file paths + scoped snippets, not
   the whole repo.
3. **Free workers are read-only** until sandboxed work (M4) is in play. Mutating edits
   only happen through the sandbox + apply protocol.

---

## The three MCP servers

| Server | Purpose |
|---|---|
| **`freeworker`** | Dispatch bulk/mechanical tasks to free opencode Zen models |
| **`repoindex`** | Code intelligence: symbols, call sites, file list (offline, tree-sitter) |
| **`toolbox`** | Planning, sandbox, diff/apply, eval, metrics, memory, autopilot |

Everything runs locally. `toolbox` and `repoindex` are fully offline and deterministic;
only `freeworker` needs the `opencode` CLI to reach free models.

---

## MCP tools in detail

### freeworker tools (4)

| Tool | Description |
|---|---|
| `free_run` | Run a bulk/mechanical task on a free model (`prompt`, optional `cwd`, `model`, `timeout`). Use for repo-wide search + summarise, issue triage, chunking large files, drafting boilerplate or a first-pass implementation you expect a judgment brain to verify afterwards. |
| `free_summarize` | Summarise a single file on disk (`file_path`, `focus`). Keeps the main agent's context small. |
| `free_scaffold` | Scaffold boilerplate into a directory (`prompt`, `project_dir`). The worker may create new files but may not touch existing ones or delete anything. |
| `list_free_models` | List the free opencode model IDs the control plane can dispatch to. |

### repoindex tools (4)

| Tool | Description |
|---|---|
| `repoindex_file_symbols` | Symbols defined in a file (classes, functions, imports). |
| `repoindex_list_files` | Files in the index, filterable by language. |
| `repoindex_search_symbols` | Search indexed symbols by name fragment. |
| `repoindex_stats` | Index health: counts of files, symbols, chunks; last ingest time. |

### toolbox tools (24)

**Planning**

| Tool | Description |
|---|---|
| `toolbox_plan_create` | Create a plan ledger; returns its `plan_dir`. |
| `toolbox_plan_add_task` | Add a step with a tier: `free` (bulk free-model work), `toolbox` (deterministic ops, action e.g. `ingest`), `claude` (judgment), `sonnet` (implementation). |
| `toolbox_plan_run` | Run the `free` + `toolbox` tiers automatically; marks judgment tasks `assigned`. |
| `toolbox_plan_advance_task` | Mark a task `done` after you (or a subagent) complete it. |
| `toolbox_plan_status` | Current state of a plan ledger. |

**Sandbox (test + fix loop)**

| Tool | Description |
|---|---|
| `toolbox_sandbox_status` | Which backend is active (`docker` vs `local-copy`). |
| `toolbox_test_loop` | Copy the repo to `.os/sandbox/copy-<ts>/`, run pytest (JUnit parse), and if red dispatch a free worker to fix files **inside the copy**, retest, up to `max_iterations`. The real working tree is never modified. Report: `green`, `iterations`, `copy_dir`, `backend`, `history[{passed,failed,errors,green}]`. |

**Apply (review bridge)**

| Tool | Description |
|---|---|
| `toolbox_sandbox_diff` | Unified diff of the disposable copy vs the real tree (classifies added/modified/deleted). Feed this to a reviewer. |
| `toolbox_sandbox_apply` | After reviewer APPROVE: apply copy changes to the real tree with `.os/backups/` snapshots and all-or-nothing rollback. `dry_run=true` previews the action list first. |

**Eval & metrics**

| Tool | Description |
|---|---|
| `toolbox_eval_run` | Run the seeded-bug suite through M4 loop → M5 apply → re-verify; records one metrics row per case (verdict PASS/FAIL/SKIP, worker_seconds, est_cost_usd). Test-file rewrites = FAIL (anti-gaming); already-green = SKIP. |
| `toolbox_metrics_report` | Aggregate: pass_rate (SKIPs excluded), cost, duration. |

**Memory**

| Tool | Description |
|---|---|
| `toolbox_memory_add` | Persist a `decision` / `fact` / `lesson` / `state` entry (with optional tags). |
| `toolbox_memory_recall` | Word-scored, recency-tiebroken recall (`query`, optional `kind`, `limit`). |
| `toolbox_session_primer` | Call at every session start: last decision, recent lessons, open plans, latest eval summary. Resumes the project instantly. |

**Automation**

| Tool | Description |
|---|---|
| `toolbox_autopilot` | One-call chain: run plan's free/toolbox tiers → sandbox test loop → apply if green → metrics row → memory lesson. Judgment tasks stay `assigned` for you. Safe default: `apply=false`. |

Plus lower-level loop/ledger/index helper tools.

---

## Capabilities

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

## Requirements

- **Python 3.11+**
- (Optional) **opencode CLI** — only needed by `freeworker` to reach free models
- (Optional) **Docker** — sandbox uses it if available; otherwise falls back to a
  disposable local copy
- `pip install -r requirements.txt` (mcp + tree-sitter + language grammars)

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

Adjust the `python` path to point at your venv. On Windows use
`<repo>\.venv\Scripts\python.exe` instead of `<repo>/.venv/bin/python`.

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

---

## First steps

1. Index a project for `repoindex`:
   ```bash
   python repoindex/ingest.py ../../path/to/project
   ```
2. In your connected app, ask your agent to:
   - Run `toolbox_session_primer` to load context
   - Run `toolbox_plan_create` to start planning a task
   - Or run the whole loop in one go with `toolbox_autopilot`

---

## CLI commands

The Python modules are also usable from the command line (no MCP client needed):

```bash
# Ingest a repo into the index
python -m repoindex.ingest <repo> --db .os/index.db

# Query the index
python -m repoindex.query symbols <term>
python -m repoindex.query files --lang python
python -m repoindex.query file <path>
python -m repoindex.query stats

# Enrich chunk summaries with free-model workers (optional)
python -m repoindex.summarize --limit 50

# Test loop (M4)
python -m tools.testloop <repo_root> --max-iterations 3

# Plan (M3)
python -m tools.plan create --name "My task"
python -m tools.plan add-task <plan_dir> "Fix the bug" --tier free

# Diff / apply (M5)
python -m tools.diffpatch diff <copy_dir> <repo_root>
python -m tools.diffpatch apply <copy_dir> <repo_root>

# Eval suite (M6)
python -m tools.eval run <suite_root> --db .os/index.db
python -m tools.metrics report

# Memory (M7)
python -m tools.memory add lesson "Always run tests in the sandbox before applying"
python -m tools.memory recall "sandbox apply"
python -m tools.memory primer

# Autopilot (M7)
python -m tools.autopilot <repo_root> --apply
```

Verify free model IDs with `opencode models` (they take the form `opencode/<model>`).

---

## Protocols

The behaviours below are what the agent follows in-session. They document how the MCP
tools are meant to be used end-to-end.

### M3 loop protocol (planner + coder)

1. `toolbox_plan_create` → get `plan_dir`.
2. `toolbox_plan_add_task` per step. The `tier` decides who runs it:
   - `free`    → bulk/mechanical free-model work (auto-run by looper, read-only)
   - `toolbox` → deterministic ops (`action: ingest`, ...) auto-run by looper
   - `claude`  → judgment (architecture/security/root-cause) — the judgment brain runs it
   - `sonnet`  → clearly-scoped implementation — a builder subagent runs it
3. `toolbox_plan_run` → runs free + toolbox tiers, marks judgment tasks `assigned`.
4. Do the `assigned` tasks yourself/builder, then `toolbox_plan_advance_task ... done`.
5. Repeat `toolbox_plan_run` until all tasks are done. Ledger lives in `.os/plans/<id>/`.

### M4 sandbox protocol (test + fix loop)

- `toolbox_sandbox_status` — which backend is active (docker vs local copy).
- `toolbox_test_loop <repo_root>` — copies the repo to `.os/sandbox/copy-<ts>/`, runs
  pytest (JUnit parse), and if red dispatches a free worker to fix files **in the copy**,
  retests, up to `max_iterations`. The real working tree is never modified.
  `dry_run=true` → run tests only.
- Report shape: `green`, `iterations`, `copy_dir`, `backend`,
  `history[{passed,failed,errors,green}]`.
- Use this before handing a fix to the reviewer, and to prove changes: a green loop =
  done, testable work.

### M5 reviewer protocol (approve then apply)

- `toolbox_sandbox_diff <copy_dir>` — unified diff of the disposable copy vs the real
  tree (classifies added/modified/deleted). Hand this to the reviewer subagent.
- Reviewer verdict must be **APPROVE** (tiered: correctness/security/cost/maintainability).
- `toolbox_sandbox_apply <copy_dir> [files] dry_run=true` — preview the action list first.
- `toolbox_sandbox_apply <copy_dir> [files] dry_run=false` — applies copy changes with
  whole-file writes and pre-apply backups in `.os/backups/<ts>/`, full rollback on any
  failure.
- Then re-run `toolbox_test_loop` on the **real** tree to confirm green after apply.

### M6 eval protocol (measure the pipeline)

- Seed cases under `.os/eval/work/<case>/` — a small repo with a REAL bug + failing
  tests + `case.json` `{id, suite, bug_class, expected, model, max_iterations}`.
- `toolbox_eval_run <suite_root>` — runs each case through M4 loop → M5 apply →
  re-verify, records a metrics row per case (verdict PASS/FAIL/SKIP, worker_seconds,
  est_cost_usd).
- An already-green tree yields **SKIP** (not a fresh pass). A fix that rewrites test
  files = **FAIL** (anti-gaming).
- `toolbox_metrics_report` — aggregate: pass_rate excludes SKIPs; cost reflects free=$0
  + ledger counts.
- To re-seed a case to its buggy state, restore its `mylib/*.py` from the case's
  original definition.

### M7 protocol (memory + autonomous)

- `toolbox_session_primer` — call at **every** session start: last decision, recent
  lessons, open plans, latest eval summary. Resumes the project instantly.
- `toolbox_memory_add kind text [tags]` — persist decisions/facts/lessons/state for
  future sessions.
- `toolbox_memory_recall query [kind] [limit]` — word-scored, recency-tiebroken recall.
- `toolbox_autopilot repo_root [plan_dir] [apply]` — chains: run plan's free/toolbox
  tiers → sandbox test loop → apply if green → record metrics + memory lesson. Judgment
  tasks stay `assigned` for you. Safe default: `apply=false`.

---

## Milestones & history

Built in milestones (M0–M7), each verified end-to-end:

- **M0** — scaffold: memory files, subagents, freeworker MCP, hooks.
- **M1** — repo ingestion (DONE): tree-sitter symbol index, chunking, SQLite store,
  query + ingest CLIs (`repoindex` package), free-model chunk summaries, `repoindex`
  MCP server.
- **M2** — tool system (DONE): `tools/` package + `toolbox` MCP server. Deterministic
  code intelligence — callers/callees/references (tree-sitter call graph),
  relevant-files scoring for an issue, bounded sanitized context packs, structured git
  reads. Rule: mechanical ops go through these tools, not an LLM.
- **M3** — planner + coder loop (DONE): plan/task schema + JSONL ledger in `.os/plans/`,
  tier-aware executor (free/toolbox auto-run, claude/sonnet handed to the judgment
  brain), `toolbox_plan_*` MCP tools. Prompts are piped to `opencode run` via stdin
  (Windows 32K arg limit).
- **M4** — sandbox + test loop (DONE): `sandbox/` package (docker-first test runner,
  disposable-copy local fallback) + `tools/testloop.py` (JUnit parse, free-worker
  fix-retry loop inside the copy, real repo never mutated) + `toolbox_sandbox_status` /
  `toolbox_test_loop` MCP tools.
- **M5** — reviewer bridge (DONE): `tools/diffpatch.py` — pure-Python, git-free diff of
  the sandbox copy vs the real tree (classify added/modified/deleted, per-file unified
  diffs) and `apply_copy_to_original` (whole-file copy with `.os/backups/` snapshots,
  all-or-nothing rollback). MCP: `toolbox_sandbox_diff` (feed reviewer) +
  `toolbox_sandbox_apply` (post-approval). A "PR" = apply the reviewer-approved copy
  into the real tree.
- **M6** — eval harness (DONE): `tools/eval.py` (per-case repos with `case.json`
  through M4→M5, anti-gaming checks) + `tools/metrics.py` (JSONL eval ledger in
  `.os/metrics/`, pass_rate with SKIP exclusion, cost/duration) + `toolbox_eval_run` /
  `toolbox_metrics_report`. Verified: seeded bugs fixed for real by a free worker;
  SKIPs don't dilute pass_rate; source-only fixes enforced (test rewrites = FAIL).
- **M7** — memory + autonomous (DONE): `tools/memory.py` (durable JSONL journal:
  decision/fact/lesson/state + recall + session primer) and `tools/autopilot.py`
  (one-call chain: plan → sandbox test loop → optional apply → metrics → memory).
  MCP: `toolbox_memory_add`/`toolbox_memory_recall`/`toolbox_session_primer`/
  `toolbox_autopilot`. Verified: free plan task auto-ran, a bug fixed in a copy,
  applied to the real tree, PASS + lesson logged.

---

## Decisions log

Key engineering decisions recorded as the project was built:

- **2026-09-22** — Base = paid subscription harness + `freeworker` MCP → opencode free
  Zen models. (Anthropic revoked subscription OAuth for third-party tools on
  2026-04-04; subscription works only on the official apps / Agent SDK. So the harness
  is the official client; workers are opencode.)
- **2026-09-22** — Deterministic tools preferred over LLMs for mechanical ops
  (search/replace, git, file discovery).
- **2026-09-22** — M1 symbol extraction uses tree-sitter 0.26. Free-model summaries
  enrich chunks post-ingest (separate `summarize` pass, offline-safe). Worker
  subprocesses must run with stdin=DEVNULL (inheriting the MCP stdin pipe hangs
  opencode).
- **2026-09-22** — M2 toolbox uses tree-sitter 0.26 `QueryCursor.api` (`QueryCursor(query).captures(node)`
  returns a dict; `Query.captures/matches` no longer exist). Call graph is name-based
  (approximate).
- **2026-09-22** — M3 plan ledger — prompts are piped to `opencode run` via stdin
  (arg-limit safe; 60KB+ prompts verified; input closing at EOF does not cause the
  earlier stdin hang).
- **2026-09-22** — M4 sandbox — no Docker/Git on the build machine, so test isolation
  is a *disposable repo copy* by default (`.os/sandbox/copy-<ts>/`). `sandbox.runner`
  auto-promotes to `docker run --rm` if Docker appears. The test loop never touches the
  real tree; workers fix only within the copy. pytest installed in the venv; collection
  errors (e.g. missing module) are parsed as `errors` entries via JUnit, not silent
  green.
- **2026-09-22** — M5 apply — since git is absent, `tools/diffpatch.py` does whole-file
  copy-on-apply (not line hunks): deterministic, no fuzzy matching, backups before
  write, all-or-nothing rollback. Diff text is still line-granular for the reviewer.
- **2026-09-22** — M6 eval — `tools/eval.py` treats tests as GROUND TRUTH (a fix
  touching test files = FAIL / anti-gaming). `tools/metrics.py` records a JSONL row per
  case; pass_rate excludes SKIPs (already-green reruns) so reruns don't inflate scores.
- **2026-09-22** — M7 memory + autopilot — memory is a plain JSONL journal under
  `.os/memory/` (recall by simple word-match; kind-filtered). Autopilot is
  orchestration only: it never makes judgment calls; claude/sonnet plan tasks are
  always returned `assigned` to the judgment brain. `--apply` is the only way autopilot
  touches the real tree, and then only on a green sandbox copy.

---

## Repository layout

```
freeworker/   MCP control plane that shells out to `opencode run` (free models)
  dispatch.py     stdin-pipe runner (Windows 32K arg limit safe)
  server.py       freeworker MCP server
  requirements.txt
repoindex/    M1 code-intelligence engine: tree-sitter extraction, SQLite store
  ingest.py       repo ingestion CLI
  query.py        query CLI        store.py       SQLite store
  symbols.py      symbol extraction lang dispatch
  chunk.py        chunking          ts.py          tree-sitter wiring
  summarize.py    free-model chunk enrichment
  server.py       repoindex MCP server
sandbox/      M4 isolation
  runner.py       docker-first / disposable-copy pytest runner
tools/        M2-M7 deterministic toolbox
  codelens.py     call graph        relevant.py    issue->files scoring
  packer.py       bounded context   plan.py        plan ledger
  looper.py       tier-aware executor
  testloop.py     JUnit parse + fix-retry loop
  diffpatch.py    copy-vs-tree diff + safe apply (M5)
  eval.py         seeded-bug suite  metrics.py     JSONL eval ledger (M6)
  memory.py       journal + recall  autopilot.py   one-call chain (M7)
  server.py       toolbox MCP server (24 tools)
.claude/      subagent definitions (planner/builder/debugger/reviewer) + event hook
.opencode/    (optional) opencode agent definitions
.os/          runtime data (index.db, plans, metrics, memory — gitignored)
.gitignore    ignores .venv, .os, __pycache__, etc.
.mcp.json     Claude Code MCP registration
opencode.json opencode MCP registration
requirements.txt  Python dependencies (mcp, tree-sitter + grammars)
```

---

## Runtime data

All state lives in `.os/` (gitignored):

| Path | Contents |
|---|---|
| `index.db` | repoindex SQLite store (files, symbols, chunks) |
| `plans/` | plan ledgers (JSONL) |
| `sandbox/` | disposable fix-loop copies |
| `backups/` | pre-apply snapshots for rollback |
| `metrics/` | eval ledger (JSONL) |
| `memory/` | durable journal (JSONL) |

---

## Requirements

- **Python 3.11+**
- (Optional) **opencode CLI** — only needed by `freeworker` to reach free models
- (Optional) **Docker** — sandbox uses it if available; otherwise falls back to a
  disposable local copy

---

## License

MIT — free to use, modify, and share.