---
name: stakeholder-deck-drafter
user-invocable: true
description: >
  Drafts a post-close stakeholder summary after a close period completes. Pulls financial
  metrics and flux commentary from Numeric, creates a restricted Google Drive document
  pre-populated with revenue, opex, and headcount variance narratives, requires controller
  review and approval before scheduling distribution, then sends a Google Calendar invite
  with the document linked. Trigger when the user says: draft board package, CFO summary,
  stakeholder report, post-close summary, executive summary, draft the board deck,
  monthly report for CFO, management reporting package, investor update draft, close
  summary for leadership, executive close report, board reporting, monthly reporting
  package, or any request to create a post-close summary document for leadership.
---

# Stakeholder Deck Drafter

Assembles a first-draft post-close summary in Google Drive with **restricted access**,
requires controller review and approval before the invite is sent, and surfaces all
flux commentary for human approval before it enters the document.

---

## Step 0: Load tools and workspace

**0a. Load tool schemas upfront** (Claude Code: batch them in one `ToolSearch` call. Other agents — Gemini CLI, Codex — expose tools directly, so skip to 0b.)

Load tools:
`list_workspaces, set_workspace, get_workspace_context, list_reports, get_report_data, get_flux_explanations, list_tasks, edit_task`

**Document + calendar connectors (agent-agnostic):** check for a Google Drive / document tool (names like `create_file` or similar) and a Calendar tool (`create_event` or similar). If Drive is unavailable, save the document locally as markdown and give the user the file path. If Calendar is unavailable, output the meeting details for the user to schedule manually. The skill always produces the document artifact regardless.

**0b. Workspace setup**

Check memory for `workspace_id`. If found, call `set_workspace`. Otherwise call `list_workspaces`, ask which workspace to use, call `set_workspace`, save to memory.

**0c. Parallel cold-start (max 3)**

After `set_workspace`, fire in parallel:
- `get_workspace_context` — all periods, entities, workspace size
- `list_reports` — discover report configs

---

## Step 1: Confirm scope and preferences

Read a `## Stakeholder deck preferences` block from a designated settings task's description (the durable source of truth; fall back to a session-memory cache if the task can't be read). Ask once which task to use as the home (the reporting/board-package close task is natural). If found, confirm:
```
Saved preferences:
• Period: [last used]
• Audience: [CFO only / Board / Management team]
• Distribution list: [emails]
• Drive folder: [name/link]
• Include close health section: [yes / no]
```

If no saved preferences, collect:
1. **Period** — default: most recently **completed** (locked) period. Verify period is complete, not still open.
2. **Audience** — CFO only, Board/investors, or management team (affects tone and detail level)
3. **Distribution list** — names or emails for the Calendar invite
4. **Drive folder** — where to save (default: create a new "Close Summaries" folder if none specified)
5. **Include close health metrics?** — ask explicitly: "Should I include operational close health metrics (% on time, tasks reopened, close cycle days) in the document? These are internal metrics — confirm before including in a board/CFO package."

Persist these to the settings task's description as the `## Stakeholder deck preferences` block via `edit_task` (durable source of truth); keep a session-memory copy only as a cache.

---

## Step 2: Pull financial data — two batches of max 3

**Batch 1 (max 3 parallel)**:
- `get_report_data` — P&L for the confirmed period
- `get_report_data` — Balance sheet for the confirmed period
- `get_report_data` — Prior completed period P&L (for comparison)

**Batch 2 (max 3 parallel)**:
- `get_report_data` — Prior completed period balance sheet
- `get_report_row_trend` — top 5 revenue and top 5 expense accounts, **trailing 6 periods only** (not 24)
- `list_tasks` with `period_id` = confirmed period (close health metrics, only if user opted in)

**Flux commentary** (scoped pull — not all accounts):
Identify the top 10 accounts by absolute dollar variance from the P&L comparison. Call `get_flux_explanations` for those 10 accounts only. Do not call for all accounts.

---

## Step 3: Compute headline metrics

From the P&L data:
- Revenue, gross profit/margin, opex (top 3 movers), net income/EBITDA, cash
- All current vs. prior period, with variance $ and %

**Materiality-based "notable" threshold** (not hardcoded 10%):
- Use the workspace materiality threshold if configured in `variance_alert_prefs_{workspace_id}`
- Otherwise ask: "What variance magnitude is notable for this company? (e.g., >$500K revenue, >15% any line item)"
- Apply consistently across all metrics

---

## Step 4: Flux commentary review — mandatory human gate

Before inserting any flux commentary into the document, present ALL commentary for controller review. Preparer-level working notes from Numeric are **not** board-ready as-is:

```
━━━ Flux commentary for review — approve each section before it enters the document ━━━

Revenue — $[variance]:
  Draft from Numeric: "Software subscription revenue up — new enterprise deal closed Dec 15"
  → Approve / Edit / Replace with placeholder

Opex: Sales & Marketing — $[variance]:
  Draft from Numeric: "marketing spend up bc we ran that SF conference again, will check final invoice"
  → ⚠️ PREPARER NOTE — not board-ready. Replace with: [your narrative] / Use placeholder

[Each account in turn...]
```

Only after the user approves or edits each section does it proceed to the document. Sections with unapproved or placeholder content are marked with `[CONTROLLER TO COMPLETE]` in the document.

---

## Step 5: Close health metrics (if opted in)

From the `list_tasks` result, compute with `period_id` filter:
- % tasks completed by their original due date
- Number of tasks reopened
- Close cycle time (first task opened → last task submitted)

Note in the document: "Close health data reflects task state as of document creation. Tasks modified after close completion may affect these figures."

---

## Step 6: Create Google Drive document — with restricted access

Assemble the document content. Create via Google Drive MCP with:
- **Sharing: restricted** — controller-only access at creation
- File name: `[Company] [Period Name] Close Summary — DRAFT [date]`

Return the document URL but **do not share it yet**. Present the document URL to the user:
```
📄 Draft document created (restricted — only you can access):
[Google Drive URL]

Please review the document before I send the Calendar invite.
After your review, I'll update sharing and send the invite.
```

---

## Step 7: Mandatory controller review gate

Ask:
```
Have you reviewed the document and confirmed it is ready to share?

Before I send the Calendar invite:
• Review placeholders marked [CONTROLLER TO COMPLETE]
• Confirm financial figures are final (period is locked)
• Confirm the distribution list is correct: [list emails]

Ready to share and send invite? (yes — send / no — I need more time)
```

**Do not proceed until the user explicitly says "yes."**

After approval:
1. Update Drive document sharing to allow view access for the distribution list
2. Proceed to Calendar invite

---

## Step 8: Schedule the review meeting

```
Title: 📊 [Period Name] Close Review — [Company]
Date: [confirmed by user in Step 1, or next business day]
Duration: 45 minutes
Attendees: [approved distribution list]
Description: |
  Close summary is ready for review:
  [Google Drive document URL]

  Key items: [top 2-3 variances from Step 3]

  Please review the document before the meeting.
```

---

## Step 9: Summary to user

```
Stakeholder deck complete — [Period Name]

📄 Document: [Drive URL] (access: distribution list only)
📅 Review meeting: [date/time] → [N] attendees invited
✅ [N] flux sections approved and included
[CONTROLLER TO COMPLETE] sections: [N]
   [Account names that still need narrative]

[Close health included: yes / no — opted out]
```
