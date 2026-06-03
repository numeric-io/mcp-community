---
name: close-calendar-blocker
user-invocable: true
description: >
  Reads the close task list from Numeric and creates focused-work Google Calendar blocks
  for each task owner on the day their tasks are due, with the Numeric task link embedded.
  Also creates review meeting slots for reviewers. Detects OOO conflicts and reports
  at-risk tasks. Prevents duplicate blocks when due dates change. Trigger when the user
  says: block calendars for close, add close tasks to calendar, calendar blocks for
  close, protect time for close, close calendar setup, add close deadlines to Google
  Calendar, block time for tasks, create close calendar holds, reserve time for close
  work, add task blocks to calendar, close time blocking, or any request to add close
  task due dates as calendar events for the team.
---

## Iteration backlog (last reviewed 2026-06-03)
- [ ] Timezone resolution per user not implemented — all blocks created in workspace timezone — medium effort / improves accuracy for distributed teams
- [ ] Calendar event titles truncated in month view for long task names — cap title at 50 chars — small effort / improves readability
- [ ] Created event IDs not persisted — future re-runs cannot delete stale blocks — medium effort / enables update-in-place

# Close Calendar Blocker

Reads every close task's owner and due date from Numeric, then creates Google Calendar
focused-work blocks for preparers and review slots for reviewers. Detects calendar
permission gaps, prevents duplicate blocks on re-runs, and reports at-risk tasks
(OOO owners) with actionable due date adjustment prompts.

---

## Step 0: Load tools and workspace

**0a. Load tool schemas upfront** (Claude Code: batch them in one `ToolSearch` call. Other agents — Gemini CLI, Codex — expose tools directly, so skip to 0b.)

Load tools:
`list_workspaces, set_workspace, get_workspace_context, list_tasks, set_task_due_date, add_task_comment, edit_task`

**Calendar connector (agent-agnostic):** check for a Google Calendar tool (names like `create_event`, `list_events`, `delete_event`, or similar). Calendar is core to this skill — but if no calendar tool is available, the skill instead outputs a per-person block schedule as a table/file the user can import or add manually. It does not fail silently. (Without `list_events`, conflict detection in Step 2 is skipped and noted.)

**0b. Workspace setup**

Check memory for `workspace_id`. If found, call `set_workspace`. Otherwise call `list_workspaces`, ask which workspace to use, call `set_workspace`, save to memory.

**0c. Parallel cold-start (max 3)**

After `set_workspace`, fire in parallel:
- `get_workspace_context` — current period, full user roster with emails, holidays
- `list_tasks` with `period_id` = current period — all tasks with due dates and owners

---

## Step 1: Build the task schedule

From the task list:
- Collect all tasks with a due date and an assigned preparer
- Tasks with no due date: skip — list in summary as "No due date — run `close-day-zero-kickoff` first"
- Tasks with a due date in the past: skip — list in summary as "Due date already passed"

Build per-owner schedule: `owner_email → [{task_name, task_url, due_date, task_id}]`

**Short-circuit on empty**: if the majority of tasks have no due date (>50%), stop and advise the user to run `close-day-zero-kickoff` first to populate due dates.

---

## Step 2: Calendar permission check and conflict detection — batched max 3

For each owner, call `list_events` to check their calendar for each due date. Batch calls at **max 3 simultaneous**.

**Permission check**: if `list_events` returns a permission error or empty results that look like an access denial (rather than a genuinely empty calendar), flag: "⚠️ Calendar not readable for [Name] — conflict detection unavailable. Blocks will be created without conflict checks."

For successfully readable calendars, identify:
- **Hard conflicts**: all-day events marked OOO, holidays, or >6 hours of meetings (flag as **at-risk**)
- **Meeting-heavy days**: >4 hours of meetings (flag in the event description but proceed with block)

---

## Step 3: Deduplicate — check for existing close blocks

For each owner × due date, check whether a calendar block with title starting with `🔒 Close:` already exists for that task on that date. Do this by searching the `list_events` results from Step 2.

If an existing block is found:
- If the task title matches: skip creating a new block (idempotent re-run)
- If the task exists but the date differs (due date was adjusted): mark the old block for deletion and create a fresh one at the new date

---

## Step 4: Present at-risk tasks — with actionable prompt

Before creating any calendar events, surface at-risk tasks and offer to adjust due dates inline:

```
━━━ At-risk tasks (owner OOO or calendar unreadable) ━━━
⚠️  [Task Name] — [Owner] — OOO on [due_date]
⚠️  [Task Name] — [Owner] — calendar not readable (no conflict check)

For the OOO conflicts: should I adjust the due dates to the next available business day?
(yes — auto-adjust / no — keep dates and note the risk / skip these tasks)
```

If user approves auto-adjustment, call `set_task_due_date` to update the task in Numeric before creating calendar blocks.

Present the full block plan to the user and confirm before creating events:
```
Ready to create [N] calendar blocks for [M] team members.
[Preview of per-owner blocks with dates and times]
Proceed?
```

---

## Step 5: Create preparer focus blocks — sequential per person

For each preparer, create blocks one person at a time (not all in parallel — to respect Calendar API per-service-account rate limits). For each block:

```
Title: 🔒 Close: [Task Name] (capped at 50 chars)
Date: [due_date]
Time: 9:00am – 11:00am (configurable via preferences)
Attendees: [preparer email only — solo focus block]
Description: |
  Numeric task: [task_url]
  Due today for [period_name] close.
  Reviewer: [reviewer_name]
  [⚠️ Heavy meeting day — consider adjusting due date.]  ← only if flagged
```

After creating each person's blocks, verify success before moving to the next person. On failure: log "Calendar block creation failed for [Name] on [date] — [reason]" and continue to the next person.

**Write audit comment to Numeric task** after each successful block creation:
```
📅 Calendar block created: [YYYY-MM-DD] 9am–11am for [Owner Name]
Created by close-calendar-blocker on [date]
```

---

## Step 6: Create reviewer meeting slots — per-reviewer, grouped by wave

Group reviewer tasks by due-date wave (tasks due in the same week). For each reviewer × wave, create one consolidated review block. Scale block duration by task count: 1 task = 30 min, 2-4 tasks = 1 hour, 5+ tasks = 2 hours.

```
Title: 📋 Close Review — [Period Name] ([N] tasks)
Date: [day after latest preparer due date in this wave]
Time: 2:00pm – [end time scaled by task count]
Attendees: [reviewer email]
Description: |
  [N] tasks to review for [period_name]:
  • [Task Name] — preparer: [name] — [task_url]
  • ...
```

---

## Step 7: Save preferences (durable, on a settings task)

Persist preferences to a designated settings task's description as a `## Calendar blocker preferences` block via `edit_task` — ask once which task to use as the home (the close checklist's first task is fine), then reuse it. This is the durable source of truth; keep a session-memory copy only as a cache.
```
## Calendar blocker preferences
<!-- Maintained by close-calendar-blocker — updated [YYYY-MM-DD] -->
focus_block_duration_hours: 2
focus_block_start_time: 9:00am
review_block_start_time: 2:00pm
```
On the next run, read this block from the settings task first; fall back to the memory cache if the task can't be read.

---

## Step 8: Summary to user

```
Calendar blocking complete — [Period Name]

✅ Created [N] focus blocks across [M] preparers (all verified successful)
✅ Created [N] review blocks for [K] reviewers
⚠️  At-risk tasks — OOO conflicts:
   • [Task Name] — [Owner] — [action taken: date adjusted to X / noted as risk]
⚠️  Calendar not readable for: [Owner names] — blocks created without conflict check
⏭ [N] blocks already existed — skipped (no duplicate)
❌ [N] blocks failed to create — [Owner names]

Note: blocks use workspace local time. Distributed teams should verify timezone alignment.
```
