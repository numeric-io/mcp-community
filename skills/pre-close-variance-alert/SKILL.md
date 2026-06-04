---
name: pre-close-variance-alert
user-invocable: true
description: >
  Proactive pre-close variance scanner. Compares current-month actuals against prior
  period and/or budget, identifies accounts breaching a configurable materiality threshold,
  and posts a prioritized Slack alert — before the flux narrative step, not after. Designed
  to run nightly during the first week of close or on demand to surface surprises early.
  Trigger when the user says: pre-close variance check, early variance alert, what's
  already moved this month, variance scan before close, accounts over threshold, alert
  me on big variances, close risk scan, what should I investigate before close, early
  warning variances, pre-close anomaly check, flag large movements, variance early
  warning, or any request to proactively identify material variances before close review.
---

# Pre-Close Variance Alert

Scans current-month actuals against prior period (and optionally budget), flags accounts
that breach a materiality threshold, and posts a prioritized Slack digest. Designed to run
early in close so teams investigate surprises before they become last-minute fire drills.

**Important:** All results are qualified as *in-progress data*. An open period is never
complete — actuals are still moving. This alert surfaces early signals, not final variances.

---

## Step 0: Load tools and workspace

**0a. Load tool schemas upfront** (Claude Code: batch them in one `ToolSearch` call. Other agents — Gemini CLI, Codex — expose tools directly, so skip to 0b.)

Load all tool schemas:
`list_workspaces, set_workspace, get_workspace_context, list_reports, get_report_data, list_financial_accounts, query_transaction_lines, list_tasks, add_task_comment, edit_task, slack_send_message, slack_search_channels`

**0b. Workspace setup**

Check memory for `variance_alert_prefs_{workspace_id}`. If found, call `set_workspace` directly. Otherwise call `list_workspaces`, ask which workspace to use, call `set_workspace`, save to memory.

**0c. Parallel cold-start (max 3)**

After `set_workspace`, fire in parallel:
- `get_workspace_context` — current period, prior period, entities, workspace entity count
- `list_reports` — discover report configs

---

## Step 1: Configure alert preferences (durable, in the task description)

Find the designated settings task (ask the user once which task to use as this alert's home — e.g. the close checklist's "Variance review" task — and remember it). Read its description for a `## Variance alert preferences` block:

```
## Variance alert preferences
<!-- Maintained by pre-close-variance-alert — updated [YYYY-MM-DD] -->

threshold_dollar: 25000
threshold_percent: 15
immaterial_floor: 5000
comparison: prior_period        # prior_period | budget | both
slack_channel: "#accounting-close"
acknowledged_accounts:          # known/expected movers — keep out of the "new" alert
  - "5105 — Payroll: Wages": recurring — headcount growth (ongoing)
  - "5335 — Tradeshows/Events": this period mar-2025 only — annual conference
```

This block is the **source of truth** (durable across sessions and users); hold a copy in session memory only as a within-run cache. If the user declines to designate a task, fall back to memory and warn that settings won't persist across sessions.

**Workspace-tier materiality defaults** (per entity count from `get_workspace_context`), used only when no block exists:
- Small (<5 entities): $10,000 or 15%
- Medium (5–10 entities): $25,000 or 15%
- Large (>10 entities): $50,000 or 15%

If no block exists (first run), collect threshold, immaterial floor, comparison baseline, and Slack channel — then write the block in Step 6b. If a block exists, confirm it with the user (interactive runs) or use it as-is (scheduled runs).

---

## Step 2: Pull current period actuals

Validate: confirm current period exists in `get_workspace_context` before pulling.

Call `get_report_data` for the primary P&L or trial balance report for the current (open) period. Parse into: `account_id → {name, current_period_balance}`.

**Short-circuit on empty**: if 0 accounts returned, report to user and stop.

---

## Step 3: Pull comparison data

**First wave (prior period — max 3 parallel)**:
Call `get_report_data` for the most recently completed period. Build the same map.

**Second wave (budget — only if configured)**:
*Before calling*, check whether a budget/forecast report exists in `list_reports`. If no budget report is found, note "Budget comparison unavailable — no budget report found in this workspace" and skip the budget call entirely. Do not make the API call.

If budget report exists, call `get_report_data` for it.

---

## Step 4: Compute variances and apply threshold

For each account:
```
prior_variance_$ = current_balance - prior_period_balance
prior_variance_%:
  - if prior_period_balance = 0: flag as NEW ACCOUNT (no % calc)
  - otherwise: prior_variance_$ / abs(prior_period_balance) × 100

budget_variance_$ = current_balance - budget_balance  (if available)
budget_variance_%: same null-safe approach
```

**Flag as alert-worthy** if:
- `|prior_variance_$| ≥ threshold_$` OR `|prior_variance_%| ≥ threshold_%` (where % is non-null)
- New accounts (prior = 0): flag if `|current_balance| ≥ threshold_$` (dollar only)
- Exclude if `|current_balance| < immaterial_balance_floor`

Sort flagged accounts by `abs(prior_variance_$)` descending.

**Apply `acknowledged_accounts` (from Step 1):** split the flagged list into two groups so known movers don't read as fresh surprises:
- **New / unacknowledged** — flagged accounts NOT on the acknowledged list. These are the headline alert.
- **Known / expected** — flagged accounts on the acknowledged list whose acknowledgment is still valid (a `recurring` entry always applies; a `this period <X>` entry applies only when the current period = X). Move these to a muted section.

An acknowledged entry whose scope was a *prior* period has expired — treat that account as new again (and drop the stale entry in Step 6b).

---

## Step 5: Pull transaction context for top accounts

**QBO/Sage/Xero workspaces:** these don't expose transaction-level data in Numeric — skip this step entirely. The variance flagging from report data (Step 4) is the deliverable; the alert simply omits the per-transaction context. (This is why the skill is QBO-safe: transaction detail is enrichment, not core.)

**NetSuite (transaction-level) workspaces:** for the **top 5 flagged accounts** (not 10 — to respect max-3 cap), call `query_transaction_lines` with **`limit: 5`** in **two batches of max 3** (first 3, then next 2). This drill is for *evidence, not computation* — the variances were already computed from report data in Step 4; these 5 lines exist so the reader sees what's behind the number.

If a batch call fails, note "Transaction detail unavailable" for that account rather than halting the scan.

---

## Step 6: Build and post the Slack alert

**Alert header — always include the qualification statement:**

```
🔍 *Pre-Close Variance Alert — [Period Name]*
_Accounts above [$X or X%] threshold — in-progress data as of [YYYY-MM-DD HH:MM]_
_⚠️ This period is not yet closed. Actuals are still moving._
[If budget unavailable: _Budget comparison was requested but no budget report was found._]

*[N] new accounts flagged* (+ [M] known/expected, muted) | Sorted by dollar variance
```

**Per-account format (new / unacknowledged — the headline):**
```
1. *[Account Name]*
   Prior period: $[X] → Current: $[Y]  |  Δ $[Z] ([pct]%)  [or: NEW ACCOUNT]
   [If budget]: vs. Budget: Δ $[Z] ([pct]%)
   Top transactions: [vendor] $[amt], [vendor] $[amt]
```

**Known / expected (muted footer — not headline noise):**
```
ℹ️ Known movers (previously acknowledged, shown for completeness):
   • [Account Name] — Δ $[Z] — [reason from acknowledged_accounts]
```

**No-alert format:**
```
✅ *Pre-Close Variance Scan — [Period Name]*
No accounts exceeded the [$X or X%] threshold as of [date/time].
_Note: close is in progress — continue monitoring._
```

**Budget unavailable footnote** (when budget was configured but not found): append to message footer so readers know the scan is partial.

Post via a Slack tool (names like `slack_send_message` or similar). On failure, notify the user directly. **If no Slack tool is available**, return the alert as an in-chat summary / file instead — the scan results are still delivered, just not auto-posted.

---

## Step 6b: Capture acknowledgments and persist (the "stop re-flagging this" loop)

**Interactive runs only** (skip when running unattended/scheduled): after presenting the alert, offer to acknowledge any new flagged account the user considers expected:

```
Mark any of these as expected so they stop showing as new next time?
• [Account] — Δ $[Z]  → acknowledge as: recurring / this period only / no
```

For each acknowledged account, record the reason and scope (`recurring` or `this period <period>`). Then call `edit_task` to update the `## Variance alert preferences` block on the settings task:
- Add new `acknowledged_accounts` entries
- Drop entries whose `this period <X>` scope has expired
- Refresh threshold/channel if the user changed them this run

Merge, don't overwrite. Stamp with today's date.

This is the difference between an alert that nags and one that learns: next period, acknowledged recurring movers drop to the muted footer automatically, so the headline only surfaces genuinely new movement.

---

## Step 7: Optional schedule setup

Ask: **"Want me to set this up to run automatically each night during close?"**

If yes, set up the recurring run via your agent's scheduling mechanism (Claude Code: the `schedule` skill; Gemini CLI / Codex / Cowork: a cron or scheduled-task equivalent, or a manual nightly trigger). It runs nightly; `close-heartbeat`'s completion detection (its Step 1) handles when to stop.

---

## Summary to user

```
Variance scan complete — [date/time]
[N] new accounts flagged above [$X / X%] threshold (+ [M] known/expected, muted)
Top mover: [Account Name] — Δ $[Z] ([pct]%)
Alert posted to [#channel]
Preferences (threshold, channel, acknowledged accounts) saved to: [settings task]
[Acknowledged this run: [account names] — won't headline next period]
[Budget: available / unavailable — prior period only used]
[Schedule: running nightly / manual mode]
```
