---
name: close-heartbeat
user-invocable: true
description: >
  Sends a scheduled daily close status digest to a Slack channel. Pulls current close
  progress, overdue tasks, blockers, and pace from Numeric and posts a structured summary.
  Designed to run on a recurring schedule during the close window and self-cancel when
  the close is marked complete. Trigger when the user says: set up daily close updates,
  schedule close status to Slack, close heartbeat, daily close digest, post close status
  to Slack automatically, schedule close reminders, recurring close updates, close standup
  bot, morning close summary, automate close updates, send daily close report, push close
  status to channel, or any request to set up automatic recurring close status updates.
---

## Iteration backlog (last reviewed 2026-06-03)
- [ ] Sub-ledger close signals not checked — task completion ≠ sub-ledger posted — small/medium effort / improves accuracy
- [ ] Blocker detection limited to structured text patterns only — free-text blockers invisible — small effort / improves signal

# Close Heartbeat

Posts a structured daily close status digest to Slack. Pulls live close data from Numeric, formats a channel-ready summary, and optionally wires up a recurring schedule so it runs automatically every weekday during close. Self-cancels the schedule when the close period is complete.

---

## Step 0: Load tools and workspace

**0a. Load tool schemas upfront** (Claude Code: batch them in one `ToolSearch` call. Other agents — Gemini CLI, Codex — expose tools directly, so skip to 0b.)

Load all tool schemas in a single call:
`list_workspaces, set_workspace, get_workspace_context, list_reports, list_tasks, get_task_comments, add_task_comment, edit_task, slack_send_message, slack_search_channels`

**0b. Workspace setup**

Check memory for `workspace_id`. If found, call `set_workspace` directly. Otherwise call `list_workspaces`, ask which workspace to use, call `set_workspace`, save to memory. (Durable per-skill preferences live on the tracking task description — see Step 6 — not in memory.)

**0c. Parallel cold-start**

After `set_workspace`, fire in parallel (max 3):
- `get_workspace_context` — current period, business days, holidays, entities
- `list_tasks` — current period, all statuses

---

## Step 1: Check close status

From `get_workspace_context`, identify the current open period. If no period is open (close is complete):

1. Post the completion message to Slack (see Step 4b).
2. Cancel the recurring schedule if one was set up: tell the user "I'll cancel the scheduled heartbeat since the close is complete."
3. Stop — do not continue with the digest.

---

## Step 2: Gather close data

From the `list_tasks` result (already loaded in Step 0c), compute:

- Total tasks, completed, pending
- **Overdue tasks**: due date < today AND status = PENDING. List with assignee name and days overdue.
- **Structured blockers**: tasks whose description contains `Blocked by:` or `Depends on:` where the referenced task is still PENDING. (Note: only detects structured dependency text — unstructured blockers in Slack or verbal are not visible here.)
- **Completion %** = completed / total × 100

**Pace signal** — use business days only (exclude weekends and workspace holidays from `get_workspace_context`):
```
business_days_elapsed = count of business days from period start through today
total_business_days = count of business days from period start through close deadline
days_elapsed_pct = business_days_elapsed / total_business_days × 100
```
If `business_days_elapsed = 0` (Day 1), skip the pace comparison — report "Day 1 of close" instead of a pace signal.

Otherwise: if `completion_pct < days_elapsed_pct - 10`, flag as **behind pace**.

**Short-circuit on empty**: if total tasks = 0, post a warning to Slack — "No tasks found for the current period. Check that the close checklist has been set up." — and stop.

---

## Step 3: Resolve Slack channel

Read the `## Close heartbeat preferences` block from the tracking task description (Step 6) for a saved channel — that's the durable source of truth. If absent, check the session-memory cache. If found either way, use it without asking.

Otherwise ask which Slack channel to post to. Use a Slack tool to confirm the channel exists (names like `slack_search_channels` or similar). It gets persisted to the tracking task in Step 6.

**If no Slack tool is available:** skip channel resolution and fall back to returning the digest as an in-chat summary (and a file the user can paste into Slack manually). The skill still produces the digest — it just doesn't auto-post.

---

## Step 4a: Build and post the digest

Format as a Slack message:

```
📊 *Close Heartbeat — [Month] [Day] (as of [HH:MM] — close in progress)*

*Progress:* [X]% complete ([completed]/[total] tasks) — [on track ✅ / behind pace ⚠️ / Day 1 🚀]
*Business days remaining:* [N] until close deadline

*Overdue tasks ([count]):*
• [Task name] — [Assignee] — [N days overdue]
• ...

*Structured blockers ([count]):*
• [Task name] — waiting on: [dependency]
• ...
_Note: only blockers noted with "Blocked by:" or "Depends on:" in task descriptions are detected here._
```

If no overdue tasks and no blockers:
```
✅ No overdue tasks · No structured blockers detected
```

Call `slack_send_message`. On failure, report to the user: "Slack send failed — channel [name], reason [X]. The digest was built but not delivered. Check channel permissions and re-run."

**Log in Numeric**: After a successful send, call `add_task_comment` on a designated tracking task (ask user on first run: "Which Numeric task should I log heartbeat runs to? This creates an audit trail."). Comment:
```
📊 Heartbeat posted [YYYY-MM-DD HH:MM] — [X]% complete, [N] overdue, [N] blocked
```

---

## Step 4b: Completion message (close is done)

Post to Slack:
```
🎉 *[Month] Close Complete*

All tasks are wrapped. No further daily updates needed.
Cancelling scheduled heartbeat. Run `close-retro` to review how the close went.
```

Then stop. Cancel the recurring schedule if one was wired up.

---

## Step 5: Optionally set up recurring schedule

Ask: **"Want me to set this up to run automatically each weekday morning during close?"**

If yes, set up the recurring run using your agent's scheduling mechanism — in Claude Code, invoke the `schedule` skill; in other environments (Gemini CLI, Codex, Cowork), use the platform's cron / scheduled-task equivalent, or have the user trigger it each morning. Pass: daily weekday cadence, workspace = current workspace, channel = configured channel. Confirm the schedule is set and note the next run time.

---

## Step 6: Save preferences (durable, on the tracking task)

Persist preferences to the **tracking task's description** (the same task used for the audit log in Step 4a) as a `## Close heartbeat preferences` block via `edit_task` — this is the durable source of truth, surviving across sessions and visible to the team in Numeric:
```
## Close heartbeat preferences
<!-- Maintained by close-heartbeat — updated [YYYY-MM-DD] -->
channel: "#accounting-close"
schedule: daily-weekdays-9am   # or "manual"
```
Keep a copy in session memory under `close_heartbeat_prefs_{workspace_id}` as a within-session cache only. On the next run, read the block from the tracking task first (Step 3 channel resolution); fall back to memory if the task can't be read.

---

## Output summary

```
Heartbeat posted to [#channel] ✅
[N] overdue · [N] blocked · [X]% complete
[Schedule: running daily at 9am / manual mode]
Audit log written to task: [task name]
```
