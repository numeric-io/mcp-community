---
name: close-day-zero-kickoff
user-invocable: true
description: >
  Automates the close kickoff at period-end. Opens the new close checklist in Numeric,
  pre-populates task due dates from a configurable calendar template, reassigns task owners
  based on prior-period assignments, posts a kickoff summary to Slack, and optionally
  creates a kickoff event in Google Calendar. Detects existing assignments to prevent
  overwriting manual changes. Eliminates 30-60 minutes of manual close setup. Trigger
  when the user says: kick off close, start the close, open close checklist, begin
  month-end close, set up close tasks, close kickoff, start the monthly close, period-end
  kickoff, open the new period, assign close tasks, populate close checklist, set up this
  month's close, launch close, initialize close, or any request to set up or start a
  new close period.
---

## Iteration backlog (last reviewed 2026-06-03)
- [ ] Task name fuzzy matching for ownership carry-forward — exact match breaks on renamed tasks — medium effort / improves reliability
- [ ] Close template stored in memory without TTL — stale templates silently applied — small effort / reduces risk
- [ ] Contractor email filtering for Calendar invite — personal emails may receive sensitive close structure — small effort / improves security
- [ ] Calendar kickoff invite to all-hands creates noise for large teams — add role-level filter option — small effort / improves usability

# Close Day Zero Kickoff

Handles the entire close launch sequence: sets up the checklist, populates due dates,
carries forward task ownership, and announces the close to the team. Detects pre-existing
assignments to avoid overwriting manual changes.

---

## Step 0: Load tools and workspace

**0a. Load tool schemas upfront** (Claude Code: batch them in one `ToolSearch` call. Other agents — Gemini CLI, Codex — expose tools directly, so skip to 0b.)

Load tools:
`list_workspaces, set_workspace, get_workspace_context, list_tasks, edit_task, assign_task, set_task_due_date, add_task_comment, slack_send_message, slack_search_users, slack_search_channels`

**Optional connectors (agent-agnostic):** check for a Slack tool (names like `slack_send_message` or similar) for the kickoff announcement, and a Google Calendar tool (`create_event` or similar) for the optional kickoff event. Both are optional — if a tool is absent, skip that output and tell the user (e.g., print the announcement in-chat for manual posting).

**0b. Workspace setup**

Check memory for `workspace_id`. If found, call `set_workspace`. Otherwise call `list_workspaces`, ask which workspace to use, call `set_workspace`, save to memory.

**0c. Parallel cold-start (max 3)**

After `set_workspace`, fire in parallel:
- `get_workspace_context` — all periods, full user roster, holidays, business calendar
- `list_tasks` for the most recently **completed** period — for ownership template

---

## Step 1: Identify the new period

From `get_workspace_context`, identify:
- The **current open period** (to set up)
- The **most recently completed period** (ownership template)

Call `list_tasks` for the current open period to see what tasks already exist and — critically — which already have assignees.

---

## Step 2: Load kickoff calendar template

Read the `## Close kickoff template` block from the designated settings task description (the durable source of truth; fall back to the session-memory cache if the task can't be read). If found, **always show it and ask for confirmation** — never silently apply a prior template:

```
Saved close calendar template (last used [date]):
• Day 1 (first business day): [task category] due
• Day 3: [task category] due
• Day 7: Close deadline

Use this template, or edit it first?
```

If no saved template, collect the due date schedule from the user.

**Holiday-aware date calculation**: when computing calendar dates from business day offsets, use the workspace holiday list from `get_workspace_context`. Present the computed dates alongside the template so the user can catch holiday collisions before confirming.

Persist the confirmed template to a durable home, not just memory: write a `## Close kickoff template` block (due-date schedule + cadence) to the description of a designated settings task via `edit_task` — ask once which task to use as the kickoff template's home (the recurring close checklist's first task is a natural choice), then reuse it. Stamp with the current date. Keep a session-memory copy as a cache only; the task description is the source of truth, so the template survives across sessions and is visible to whoever runs the next close.

---

## Step 3: Carry forward ownership — with change detection

From the prior period's task list, build: `task_name → {preparer, reviewer}`.

For each task in the current period:
- Match by exact task name to the prior period map
- If a match is found, carry forward the owner

**Idempotency check**: before carrying forward, check the current task's existing assignee field. If it is already populated (a previous kickoff or manual assignment), **do not overwrite** — flag it as "already assigned" and show it in the confirmation for the user to review.

Flag any owners who have not been seen as active in the workspace within the past 60 days (based on workspace roster activity if available) — highlight them in the confirmation:
```
⚠️ Stale owner — [Name] (last active >60 days ago): [Task Name]
```

For tasks with no prior-period match: add to "unassigned" list.

---

## Step 4: Full confirmation before any changes

Present to the user before writing anything to Numeric, Slack, or Calendar:

```
Ready to kick off [Period Name] close:

━━━ Task assignments (review carefully) ━━━
[Task Name] — [Preparer] → due [Date], reviewer: [Reviewer]  ← carryover
[Task Name] — already assigned: [Name] → due [Date]  ← will NOT overwrite
⚠️ [Task Name] — stale owner: [Name] (inactive 60+ days) → re-assign?
[Task Name] — UNASSIGNED (no prior-period match)

━━━ Slack announcement ━━━
Preview of message to [#channel]:
"🚀 [Month Year] Close is Open! ..."
[Full message preview here]

━━━ Google Calendar invite ━━━
Attendees: [list of names + emails]
Note: review for any contractors or role accounts before sending.

Proceed? (yes / edit)
```

Wait for user confirmation.

---

## Step 5: Apply assignments and due dates — batched max 3

After confirmation, call `assign_task` and `set_task_due_date` in **batches of 3** (not all in parallel at once). After each batch, verify the responses before proceeding to the next batch. On any failure: stop, report which tasks failed, and allow the user to retry or skip.

For each task successfully assigned, call `add_task_comment`:
```
🚀 Close kickoff [YYYY-MM-DD] — assigned to [Preparer], due [Date], reviewer: [Reviewer]
Auto-configured by close-day-zero-kickoff
```

---

## Step 6: Post Slack kickoff announcement

Use the Slack message preview the user approved in Step 4. Call `slack_search_users` to resolve @mentions. Call `slack_send_message`.

Format:
```
🚀 *[Month Year] Close is Open!*

*[Preparer Name]*
• [Task 1] — due [Date]
• [Task 2] — due [Date]
...

*Key dates:* Recs + Flux: [Date] · Reviews: [Date] · Close target: [Date]

💡 Next steps: Calendar blocks → run `close-calendar-blocker` to reserve time on everyone's calendar.
```

---

## Step 7: Create kickoff Google Calendar event (optional)

Ask: **"Want me to create a close kickoff meeting invite?"**

If yes: show the attendee list (from the workspace roster, matching task owners) before creating the event. Ask the user to confirm the list — it may include contractors with personal email addresses. After confirmation, create the event.

---

## Step 8: Summary to user

```
Close kickoff complete — [Period Name]

✅ [N] tasks assigned with due dates (batched, all confirmed)
⏭ [N] tasks already assigned — not overwritten
⚠️  [N] stale owners flagged — review and reassign manually
❌ [N] tasks left unassigned — no prior-period match
📣 Kickoff posted to [#channel]
📅 Calendar invite sent to [N] team members (or: skipped)

Next: Run `close-calendar-blocker` to add task due dates to everyone's Google Calendar.
Next: Run `close-heartbeat` daily to track progress automatically.
```
