# Performance Patterns

Performance discipline for any automation Build produces. Build wires the patterns in while writing; Review validates that they work.

## Cache cold-start calls

`get_workspace_context`, `list_reports`, and `list_financial_accounts` are 60K+ chars each and rarely change within a session. Write to `outputs/.numeric_session_cache/{workspace_id}_{call}.json` after the first call; read from cache on subsequent calls. TTL ~24h.

## Confirm scope upfront

Before any heavy data pull, estimate the scope and confirm via `AskUserQuestion`. Five dimensions to lock down:

1. **Period** — which close period? Open, most recently closed, specific quarter, trailing window. Default to the open period when unstated, but confirm.
2. **Entity** — single entity, a list, or all? Default to "all" only when the user has been explicit; otherwise ask.
3. **Materiality** — dollar threshold below which a row is ignored. Default to workspace tier (small $1K / medium $5K / large $10K) but let the user override.
4. **Accounts** — all accounts that exceed materiality, or a specific account list? Confirm when the post-materiality count is expected to be large (>100 leaves).
5. **Months in analysis (lookback window)** — default 6 months for transaction history, 3 trailing periods for trend analysis. Confirm before extending to 12 or 24 — doubles the data volume.

Surface the projected cost in the same prompt so the user can narrow on the dimension that matters most. Only proceed after confirmation.

Example prompt:

> "This will pull 12 months of transactions across 5 entities (~60 API calls, est. 4–8 min). Continue, or narrow scope?"
>
> - Period: open (default) | most recent closed | specific
> - Entity: <list> | all
> - Materiality: $5K medium tier (default) | $1K | $10K | custom
> - Accounts: all above threshold (default) | specific list
> - Months: 6 (default) | 12 | 3

Catches expensive runs earlier than fail-fast or materiality gating.

## Fan out independent units in parallel

One subagent per entity / lens / anomaly / period / task, dispatched in a single Agent message. Don't fan out single-unit work. In environments without subagents, run sequentially but keep the script-first, materiality-gate, and checkpoint patterns.

## Cap parallel calls at 3

Empirical finding: when 5+ heavy MCP calls are in flight simultaneously, three of them stall at near-identical 244–253s — rate-limit or queue contention at the MCP server. Cap simultaneous calls at 3. When fanning out N>3 units, batch by 3.

## Subagent contract

Subagents have no conversation history. Pass everything they need as inputs:
- File paths to the prior phase's documents
- The tool list they should use
- The task description / scope

Subagents return small structured JSON, never tool-result content. Specifically: do NOT read or display the TSV/JSON content of any tool-result file. `cp` to the cache path, `wc -l` for the count, return the contracted JSON. Reading content into context costs ~50K tokens per drill that should not be paid.

## Push heavy parsing to bundled scripts

TSV/JSON parsing, pivot reasoning, classification, aggregation — push to `scripts/`. Inline parsing of large MCP responses burns context per task. The skill prompt orchestrates; scripts compute.

## The query funnel: aggregate → narrow → drill

Never start at transaction level. Every question starts at the most aggregated view that can answer or eliminate, and only survivors descend:

```
statement totals  →  pivoted report rows  →  one row's transaction lines
   (~1K tokens)        (~10K)                  (drill ONLY survivors)
```

The rules of the funnel:

1. **Aggregates bound their detail.** If an account's total variance is below threshold, no transaction inside it can matter — skip the entire branch without looking. Apply materiality at the aggregate level, before any drill.
2. **Pivot to the dimension of the question.** A vendor question wants a counterparty-pivoted report (one row per vendor, monthly columns) — not transactions grouped client-side. The pivot IS the group-by, done server-side. Same for departments, entities, classes.
3. **Ask comparisons, not extractions.** `build_report` supports month-over-month natively. "What changed?" is one comparison call with a variance column, never two full pulls diffed in context.
4. **Drill for evidence, not computation.** By the time you reach transaction lines, every number is already computed at the aggregate level. The drill grabs 3–5 example lines (`limit: 5`, narrowest window, top-N rows only) so a human sees *why* — 5 examples explain a variance as well as 500.
5. **Reuse prior conclusions.** Flux explanations, task comments, and persisted preference blocks contain last cycle's answers. A 1KB prior narrative beats a 100KB re-derivation.
6. **Name the irreducible cases.** FIFO aging and audit evidence genuinely need full populations. For those, contain instead: parse via scripts/subagents so the bulk never enters model context, and keep the window as narrow as the requirement allows.

## Apply a materiality gate before drilling

Filter the candidate list before fan-out. Surface in-scope vs. out-of-scope counts and let the user override. Tier-based defaults:
- Small workspace (<5 entities): primary materiality rule
- Medium (5–10 entities): 5× the small default
- Large (>10 entities): 10× the small default

If post-gate count >100 units, suggest a higher threshold before proceeding.

## Push filters into the MCP call

When calling an MCP tool that accepts filters (e.g., `list_tasks` accepts `status`, `task_type`, `assignee_id`, `report_ids`, `name_contains`), pass every filter the MCP supports. The MCP applies them at the source and returns a smaller payload. Filtering in-script after the fact pulls more data than needed and burns context.

This applies to any MCP — Numeric, NetSuite SuiteQL, HubSpot, Pylon, Linear. Read the tool's input schema before the call and use what's there.

## Checkpoint between phases / per unit

Each subagent writes parsed output to a cache path before returning. Re-runs read from cache instead of re-fetching. If a downstream step fails, the next run resumes from the checkpoint.

## Validate scope before pulling

Before a heavy pull, confirm:
- The period exists in `get_workspace_context`
- Filtered task list returned >0 results
- Required accounts resolve in `list_financial_accounts`
- Required reports resolve in `list_reports`

A bad period or unresolved account fails late, after the data is half-pulled.

## Short-circuit on empty

0 results → tell the user and stop. Do not produce an empty artifact, a balanced-by-zero JE, or a dashboard with empty headers.

## Stream progress

One line per subagent return — not fixed cadence. Subagents finish out of order; cadence-based emits arrive in clumps. Per-return updates keep the user informed in real time. Format: `<verb> <unit> (<n>/<N>)`, e.g., `Drilled 5400/Marketing (3/47)`.

## Daily / repeat-use → Cowork artifact

If the user signals daily or repeat use ("I run this every Monday"), generate it once as a Cowork artifact via `mcp__cowork__create_artifact`. The HTML calls the connector at open-time via `window.cowork.callMcpTool`. Refresh becomes ~10–30s vs. running the skill from scratch each time. Suggest this on first repeated use.

## Default windows; confirm before widening

Defaults — confirm via `AskUserQuestion` before extending:
- 6 months for transaction history
- 3 trailing periods for trend analysis
- Single period for status/dashboard work

Avoid silently widening.

