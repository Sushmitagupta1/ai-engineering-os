# AI Engineering OS

Cost-aware hierarchical AI software-engineering system. A paid Claude Code brain supervises a
pool of free Lyzr/Zen model workers, orchestrated through a Python MCP control plane.

## Mission
Turn a GitHub issue into a merged PR at minimum cost:
free/deterministic workers do bulk + mechanical work; Claude makes every judgment call.

## Cost policy (the core rule)
Use the cheapest system capable of reliably completing each task:

| Task type | Owner |
|---|---|
| Architectural / security / root-cause / design choice | Claude (Opus; level 100-700) |
| Clearly-scoped implementation, tests from spec | Claude (Sonnet) |
| Triage, chunking, summarising, boilerplate, codegen drafts | free Zen worker (freeworker MCP) |
| Grep, reformat, patch, git status/log, file discovery | deterministic tools (rg, git, ruff) — NO LLM |

Hard rules:
1. Judgment never delegated to free models. A free-model answer that feeds a decision must be
   cheaply verified by Claude (builder) before it acts on it.
2. Never leak secrets into prompts. Workers get file paths + scoped snippets, not the repo.
3. Free workers are read-only for M0-M2. Mutating edits only after sandbox (M4).

## Architecture
- Base harness: Claude Code (paid subscription) with subagents:
  planner (Opus), builder (Sonnet), debugger (Opus), reviewer (Opus, read-only).
- freeworker: Python MCP server that shells out to `opencode run -m opencode/<free-model>`
  for bulk work. Registered in .mcp.json.
- Memory: CLAUDE.md + AGENTS.md kept current; decisions log below.
- Observability: hook logs events to `.os/runs/events-*.jsonl` (Postgres/pgvector from M6).
- Sandbox (M4): docker-compose worker (postgres + python worker container).

## M3 loop protocol (planner + coder)
When working an issue through subagents, drive the plan ledger via toolbox MCP tools:
1. `toolbox_plan_create` -> get `plan_dir`.
2. `toolbox_plan_add_task` per step. tier decides who runs it:
   - `free`   -> bulk/mechanical free-model work (auto-run by looper, read-only)
   - `toolbox`-> deterministic ops (`action: ingest`, ...) auto-run by looper
   - `claude` -> judgment (architecture/security/root-cause) — YOU run it
   - `sonnet` -> clearly-scoped implementation — builder subagent runs it
3. `toolbox_plan_run` -> runs free+toolbox tiers, marks judgment tasks `assigned`.
4. Do the `assigned` tasks yourself/builder, then `toolbox_plan_advance_task ... done`.
5. Repeat `toolbox_plan_run` until all tasks done. Ledger lives in `.os/plans/<id>/`.

## M4 sandbox protocol (test + fix loop)
- `toolbox_sandbox_status` — which backend is active (docker vs local copy).
- `toolbox_test_loop repo_root` — copies the repo to `.os/sandbox/copy-<ts>/`, runs pytest
  (JUnit parse), and if red dispatches a free worker to fix files IN THE COPY, retests, up to
  `max_iterations`. The real working tree is never modified. `dry_run=true` → run tests only.
- Report shape: `green`, `iterations`, `copy_dir`, `backend`, `history[ {passed,failed,errors,green} ]`.
- Use this before handing a fix to reviewer, and to prove changes: loop green = done testable work.

## M5 reviewer protocol (approve then apply)
- `toolbox_sandbox_diff copy_dir` — unified diff of the disposable copy vs the real tree
  (classifies added/modified/deleted). Hand this to the reviewer subagent for review.
- Reviewer verdict must be APPROVE (tiered: correctness/security/cost/maintainability).
- `toolbox_sandbox_apply copy_dir [files] dry_run=true` — preview the action list first.
- `toolbox_sandbox_apply copy_dir [files] dry_run=false` — applies copy changes to the real tree:
  whole-file writes, pre-apply backups in `.os/backups/<ts>/`, full rollback on any failure.
- Then re-run `toolbox_test_loop` on the REAL tree to confirm green after apply.

## M6 eval protocol (measure the pipeline)
- Seed cases under `.os/eval/work/<case>/` — a small repo with a REAL bug + failing tests + `case.json`
  `{id, suite, bug_class, expected, model, max_iterations}`.
- `toolbox_eval_run <suite_root>` — runs each case through M4 loop → M5 apply → re-verify, records a
  metrics row per case (verdict PASS/FAIL/SKIP, worker_seconds, est_cost_usd).
- An already-green tree yields SKIP (not a fresh pass). A fix that rewrites test files = FAIL (anti-gaming).
- `toolbox_metrics_report` — aggregate: pass_rate excludes SKIPs; cost reflects free=$0 + ledger counts.
- To re-seed a case to its buggy state, restore its `mylib/*.py` from the case's original definition.

## M7 protocol (memory + autonomous)
- `toolbox_session_primer` — call at EVERY session start: last decision, recent lessons, open
  plans, latest eval summary. Resumes the project instantly.
- `toolbox_memory_add kind text [tags]` — persist decisions/facts/lessons/state for future sessions.
- `toolbox_memory_recall query [kind] [limit]` — word-scored, recency-tiebroken recall.
- `toolbox_autopilot repo_root [plan_dir] [apply]` — chains: run plan's free/toolbox tiers →
  sandbox test loop → apply if green → record metrics + a memory lesson. Judgment tasks stay
  `assigned` for you. Safe default: apply=false.

## Commands
- Start freeworker MCP for Claude Code: it auto-loads from `.mcp.json` (stdio).
- Smoke-test a free worker:
  `opencode run -m opencode/big-pickle --dir <repo> "summarise the diff in one line"`
- Verify free model ids: `opencode models` (model ids `opencode/<model>`).
- Ingest a repo into the index:
  `py -3.14 -m repoindex.ingest <repo> --db .os/index.db` (run via freeworker venv: `freeworker\.venv\Scripts\python.exe`)
- Query the index: `py -3.14 -m repoindex.query symbols <term>` / `files --lang python` / `file <path>` / `stats`
- Enrich chunks with free-model summaries: `py -3.14 -m repoindex.summarize --limit 50`

## Milestones
- M0 scaffold: memory files, subagents, freeworker MCP, hooks.
- M1 repo ingestion (DONE): tree-sitter symbol index, chunking, SQLite store,
  query + ingest CLIs (`repoindex` package), free-model chunk summaries, repoindex MCP server.
- M2 tool system (DONE): `tools/` package + `toolbox` MCP server.
  Deterministic code intelligence — `toolbox_callers` / `toolbox_callees` / `toolbox_references`
  (tree-sitter call graph), `toolbox_relevant_files` (score index for an issue),
  `toolbox_pack_context` (bounded sanitized context pack), `toolbox_git_*` (structured git reads).
  Rule: mechanical ops go through these tools, not an LLM.
- M3 planner+coder loop (DONE): `tools/plan.py` (plan/task schema + JSONL ledger in `.os/plans/`),
  `tools/looper.py` (tier-aware executor: free/toolbox auto-run, claude/sonnet handed to Claude),
  `toolbox_plan_*` MCP tools. Prompts are piped to `opencode run` via stdin (Windows 32K arg limit).
- M4 sandbox+test loop (DONE): `sandbox/` package (docker-first test runner, disposable-copy
  local fallback) + `tools/testloop.py` (JUnit parse, free-worker fix-retry loop inside the copy,
  real repo never mutated) + `toolbox_sandbox_status` / `toolbox_test_loop` MCP tools.
- M5 reviewer bridge (DONE): `tools/diffpatch.py` — pure-Python, git-free diff of the sandbox copy
  vs the real tree (classify added/modified/deleted, per-file unified diffs) and
  `apply_copy_to_original` (whole-file copy with `.os/backups/` snapshots, all-or-nothing rollback).
  MCP: `toolbox_sandbox_diff` (feed reviewer) + `toolbox_sandbox_apply` (post-approval). PR =
  apply the reviewer-approved copy into the real tree.
- M6 eval harness (DONE): `tools/eval.py` (per-case repos with `case.json` through M4→M5, anti-gaming
  checks) + `tools/metrics.py` (JSONL eval ledger in `.os/metrics/`, pass_rate with SKIP exclusion,
  cost/duration) + `toolbox_eval_run` / `toolbox_metrics_report` MCP tools. Verified: 3/3 seeded bugs
  fixed for real by free worker (19%/20% VAT case also passed via real knowledge); SKIPs don't
  dilute pass_rate; source-only fixes enforced (test rewrites = FAIL).
- M7 memory + autonomous (DONE): `tools/memory.py` (durable JSONL journal: decision/fact/lesson/
  state + `recall` word-match scoring + `session_primer`) and `tools/autopilot.py` (one-call chain:
  plan free/toolbox tiers → sandbox test loop → optional apply → metrics row → memory lesson).
  MCP: `toolbox_memory_add`/`toolbox_memory_recall`/`toolbox_session_primer`/`toolbox_autopilot`.
  Verified: free plan task auto-ran, celsius bug fixed in copy, applied to real tree, PASS + lesson logged.

## All milestones met. Tollgate for next system: see ./AGENTS.md for conventions; start sessions with
## toolbox_session_primer.

## Decisions log
- 2026-09-22: Base = Claude Code (paid sub) + freeworker MCP → opencode free Zen models.
  Anthropic revoked subscription OAuth for third-party tools (2026-04-04); subscription works
  only on Claude.ai / Claude Code / Agent SDK. So the harness is Claude Code, workers are opencode.
- 2026-09-22: Deterministic tools preferred over LLMs for mechanical ops (search/replace, git).
- 2026-09-22: M1 symbol extraction uses tree-sitter 0.26 (node kinds per language in `_DEF_KINDS`).
  Free-model summaries enrich chunks post-ingest (separate `summarize` pass, offline-safe).
  Worker subprocesses must run with stdin=DEVNULL (inheriting MCP stdin pipe hangs opencode).
- 2026-09-22: M2 toolbox uses tree-sitter 0.26 QueryCursor API (`QueryCursor(query).captures(node)`
  returns dict; Query.captures/matches no longer exist). Call graph is name-based (approximate).
  Git is NOT installed on this machine yet — git_* tools return a clear error until it is.
- 2026-09-22: M3 plan ledger — prompts are PIPEfed to `opencode run` via stdin (arg-limit safe,
  60KB+ prompts verified; input closing at EOF does not cause the earlier stdin hang).
- 2026-09-22: M4 sandbox — no Docker/Git on this machine, so test isolation is a *disposable repo
  copy* by default (`.os/sandbox/copy-<ts>/`). `sandbox.runner` auto-promotes to `docker run --rm`
  if Docker appears. The test loop never touches the real tree; workers fix only within the copy.
  pytest 9 installed in the venv; collection errors (e.g. missing module) are parsed as `errors`
  entries via JUnit, not silent green.
- 2026-09-22: M5 apply — since git is absent, `tools/diffpatch.py` does whole-file copy-on-apply
  (not line hunks): deterministic, no fuzzy matching, backups before write, all-or-nothing
  rollback. Diff text is still line-granular for the reviewer.
- 2026-09-22: M6 eval — `tools/eval.py` treats tests as GROUND TRUTH (a fix touching test files =
  FAIL / anti-gaming). `tools/metrics.py` records a JSONL row per case; pass_rate excludes SKIPs
  (already-green reruns) so reruns don't inflate scores.
- 2026-09-22: M7 memory+autopilot — memory is a plain JSONL journal under `.os/memory/` (recall by
  simple word-match; kind-filtered). Autopilot is orchestration only: it never makes judgment calls;
  claude/sonnet plan tasks are always returned `assigned` to the Claude brain. `--apply` is the only
  way autopilot touches the real tree, and then only on a green sandbox copy.
- _next decision_