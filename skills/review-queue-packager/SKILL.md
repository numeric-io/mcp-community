---
name: review-queue-packager
user-invocable: true
description: >
  Collects all tasks in "ready for review" or "pending review" state in Numeric, bundles
  supporting transaction detail and flux commentary per task, and routes a structured
  review digest to each assigned reviewer via Slack DM (or Gmail). Tasks are sorted by
  risk within each reviewer's queue. Logs the routing as a task comment to prevent
  duplicate sends. Trigger when the user says: route reviews, send review queue, notify
  reviewers, package tasks for review, what needs to be reviewed, send reviews to
  reviewers, reviewer notifications, push tasks to reviewers, review digest, send
  pending approvals, route ready-for-review tasks, package review queue, approval
  routing, or any request to notify reviewers about tasks that are ready for their attention.
---

# Review Queue Packager

Routes each reviewer their personalized queue of tasks awaiting their sign-off. Bundles
transaction context and flux commentary into each message. Enforces access control (no
transaction detail for sensitive accounts in external channels) and segregation of duties
checks before sending.

---

## Step 0: Load tools and workspace

**0a. Load tool schemas upfront** (Claude Code: batch them in one `ToolSearch` call. Other agents — Gemini CLI, Codex — expose tools directly, so skip to 0b.)

Load tools:
`list_workspaces, set_workspace, get_workspace_context, list_tasks, get_task_comments, add_task_comment, edit_task, query_transaction_lines, get_flux_explanations, slack_send_message, slack_search_users`

**Messaging connector (agent-agnostic):** check for a Slack tool (names like `slack_send_message`, `slack_post`, or similar) as the primary channel, and a Gmail/email tool (`gmail`, `send_email`, `draft_email`, or similar) as the fallback. If neither is available, the skill still builds each reviewer's queue and returns it as an in-chat summary / file the user forwards manually — it does not fail.

**0b. Workspace setup**

Check memory for `workspace_id`. If found, call `set_workspace`. Otherwise call `list_workspaces`, ask which workspace to use, call `set_workspace`, save to memory.

**0c. Parallel cold-start (max 3)**

After `set_workspace`, fire in parallel:
- `get_workspace_context` — current period, full user roster with IDs and emails
- `list_tasks` with `status: IN_REVIEW` and `period_id` = current period (server-side filter)

---

## Step 1: Filter to reviewable tasks

Keep tasks with status "ready for review," "in review," or "pending approval." A reviewer must be assigned.

**Short-circuit on empty**: if no tasks in this state, report and stop:
```
No tasks are currently in "ready for review" state.
Tasks appear here when preparers submit them in Numeric.
```

---

## Step 2: Segregation of duties check

For each task, confirm that the assigned reviewer ≠ the preparer. If reviewer = preparer, **flag the task** and exclude it from routing:
```
⚠️ SOD violation: [Task Name] — reviewer and preparer are the same person ([Name]).
   This task has been excluded from routing. Assign a different reviewer in Numeric before re-running.
```

---

## Step 3: Cooldown check — prevent duplicate sends

For each remaining task, call `get_task_comments`. If a comment containing `📬 Review queue sent to` was posted within the past **8 hours**, skip that task. Group skipped tasks in the final summary.

---

## Step 4: Group tasks by reviewer and sort

Group eligible tasks by reviewer. Within each reviewer's list, sort by **risk-first order**:
1. Tasks with open variance flags or pending flux explanations (highest risk)
2. Tasks by absolute account balance, descending
3. Alphabetical fallback only for tie-breaking

---

## Step 5: Pull supporting context — batched to max 3 parallel calls

For each reviewer's task list, pull context in **batches of max 3** simultaneous calls (not all at once):

For each task:
- `query_transaction_lines` — top 5 transactions by amount for the associated account/entity. **QBO/Sage/Xero workspaces don't expose transaction lines — skip this and route with task + flux context only.** Transaction detail is enrichment, not core, which keeps the skill QBO-safe.
- `get_flux_explanations` — flux commentary for this account in the current period if available

**Access control gate for transaction detail**: before including transaction lines in the message, check whether the account name suggests sensitive data. Sensitive patterns include: payroll, compensation, salary, bonus, legal, litigation, exec, officer, board, M&A, acquisition, equity.

If the account is sensitive:
- Replace transaction detail in the Slack/Gmail message with: `"Transaction detail omitted — sensitive account. Review in Numeric: [task URL]"`

---

## Step 6: Resolve reviewer communication channel

Default: Slack DM. Search for reviewer's Slack handle via `slack_search_users` using their name or email.

**Gmail fallback**: if no Slack handle found, resolve the reviewer's email from the workspace roster. **Before sending**: show the user the resolved email address and require explicit confirmation:
```
No Slack handle found for [Reviewer Name]. I found this email: [email@company.com]
Is it safe to send their review queue to this email address? (yes / skip this reviewer)
```

Only send to Gmail after explicit approval per reviewer.

---

## Step 7: Build and send per-reviewer digest

One message per reviewer. Cap the message at the top 10 tasks — if a reviewer has more than 10, note "Showing top 10 by priority. [N] additional tasks await review — open Numeric for the full list."

**Slack format:**
```
Hi [First Name] 👋 — you have [N] task(s) ready for your review in Numeric:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. *[Task Name]* — [Account] | [Entity]
   Preparer: [Name] · Submitted: [date]
   [Task URL]

   Top transactions: [vendor] $[amt], [vendor] $[amt]
   [or: Transaction detail omitted — sensitive account. Review in Numeric.]

   Flux note: [excerpt or "No flux commentary yet"]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Gmail format**: same content as plain text. Subject: `[N] tasks ready for your review — [Period Name]`

---

## Step 8: Log routing on each task

After each **successful** send, immediately call `add_task_comment`:
```
📬 Review queue sent to [Reviewer Name] via [Slack/Gmail] on [YYYY-MM-DD HH:MM]
```

Write the comment **before** moving to the next reviewer. This ensures the cooldown marker exists even if a subsequent send fails.

---

## Step 8b: Persist routing preferences (durable, on a settings task)

So routing decisions don't reset each period, persist a `## Review routing preferences` block to a designated settings task's description via `edit_task` (ask once which task to use as the home; the close checklist's review task is natural):
```
## Review routing preferences
<!-- Maintained by review-queue-packager — updated [YYYY-MM-DD] -->
reviewer_channels:               # confirmed channel per reviewer — reuse, don't re-ask
  - Jane Smith: slack
  - External Auditor: gmail (billing@firm.com)
sensitive_accounts:              # user-confirmed — always withhold transaction detail
  - "5125 — Bonus"
  - "5420 — Legal Fees"
```
Read this block at the start (Step 6 channel resolution reuses `reviewer_channels`; Step 5 treats `sensitive_accounts` as confirmed-sensitive in addition to the pattern match). Merge, don't overwrite. Keep memory only as a session cache.

---

## Step 9: Summary to user

```
Review queue packaged — [date]

✅ Notified [N] reviewers across [M] tasks
  • [Reviewer Name] — [Task 1], [Task 2] (via Slack)
  • [Reviewer Name] — [Task 3] (via Gmail — user confirmed)

⚠️ SOD violations excluded (reviewer = preparer): [task names]
⏸ Skipped – cooldown active (sent <8h ago): [task names]
🔒 Sensitive accounts — transaction detail withheld in message: [account names]
❌ Could not resolve channel (no Slack handle, Gmail not approved): [reviewer names]
```
