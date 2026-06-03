---
date: 2026-06-03
topic: accounting-skills-for-mcp-toolkit
focus: New skills for accounting professionals leveraging Numeric + Slack/Gmail/Calendar/Drive MCPs
---

# Ideation: New Accounting Skills for numeric-mcp-toolkit

## Codebase Context

20 existing skills covering close management, flux/variance, accruals, reporting, audit, reconciliation, and JE generation. Skills are self-contained Markdown files with YAML frontmatter, distributed via .zip. All use Numeric MCP; can chain Slack, Gmail, Google Calendar, NetSuite, Google Drive, and other MCPs. The `accounting-skill-builder` meta-skill handles new skill creation. The `complete-accruals-task` preference-persistence pattern (storing structured state in task descriptions) is the toolkit's key reuse mechanic.

**Key gaps identified:**
- No recurring/scheduled Slack push skill (only one-off DMs via `overdue-task-nudge`)
- No prepaid/fixed asset schedule skills
- No intercompany elimination skill
- No approval/review routing workflow
- No period-open kickoff automation
- No pre-close (proactive) variance alerting
- Slack integration is top product feedback cluster (Linear: SOL-7038, SOL-7022, SOL-7228)
- Google Calendar, Gmail, Google Drive MCPs unused by existing skills

## Ranked Ideas

### 1. `close-heartbeat`
**Description:** Scheduled daily push to Slack during close. Pulls close progress, overdue tasks, blockers, and pace from Numeric and posts a structured digest to a configured channel. Stops when close is marked complete.
**Rationale:** Directly addresses the #1 product feedback cluster (Slack automation). Three open Linear tickets. The overdue-nudge demo was described as "blew my mind" at MCP launch. Close-pulse already provides the data layer — this adds scheduling + push delivery.
**Downsides:** Requires the `schedule` skill to wire up cron; quality depends on Numeric MCP close state exposure.
**Confidence:** 92%
**Complexity:** Low
**Status:** Unexplored

### 2. `prepaid-amortization-scheduler`
**Description:** Reads prepaid balances from the GL, generates a month-by-month amortization schedule, posts the current-period JE to NetSuite, and flags schedules expiring within the close window. Reuses preference-persistence pattern from `complete-accruals-task`.
**Rationale:** Explicit toolkit gap. Deterministic math done manually in spreadsheets every month. Highest-frequency, lowest-judgment close task.
**Downsides:** Requires NetSuite MCP connectivity; initial schedule onboarding needs structured input.
**Confidence:** 88%
**Complexity:** Medium
**Status:** Unexplored

### 3. `pre-close-variance-alert`
**Description:** Runs nightly or on-demand, compares current-month actuals against prior period and budget, posts a prioritized Slack alert for accounts breaching a configurable materiality threshold — before the flux narrative step.
**Rationale:** All existing flux skills are reactive. This is proactive — catch the surprise on day 3, not day 8. Addresses SOL-7022 ("actionable Slack notifications").
**Downsides:** Requires budget/prior-period data accessible via Numeric MCP; threshold config needed per workspace.
**Confidence:** 85%
**Complexity:** Low-Medium
**Status:** Unexplored

### 4. `review-queue-packager`
**Description:** Collects tasks in "ready for review" state, bundles transaction detail and flux commentary per task, routes a structured digest to each assigned reviewer via Slack (or Gmail), sorted by materiality.
**Rationale:** Explicit gap — no approval workflow skill. Reviewers hunt manually through Numeric. SOL-7228 specifically calls out approval notification flows.
**Downsides:** Requires preparer-to-reviewer mapping; Slack DM routing needs workspace setup.
**Confidence:** 87%
**Complexity:** Medium
**Status:** Unexplored

### 5. `close-day-zero-kickoff`
**Description:** At period-end, opens the new close checklist in Numeric, pre-populates task due dates from a configurable calendar template, reassigns owners from prior period, posts a kickoff summary to Slack with each person's task list, and optionally creates a kickoff Google Calendar event.
**Rationale:** The first 30-60 minutes of every close is pure coordination overhead. Chains Numeric + Slack + Google Calendar — none used together in any existing skill.
**Downsides:** Requires initial template configuration; Google Calendar MCP scoping needed.
**Confidence:** 83%
**Complexity:** Medium
**Status:** Unexplored

### 6. `intercompany-elimination-checker`
**Description:** Queries transaction lines across entities in a consolidated workspace, surfaces unmatched intercompany payables/receivables, and generates elimination JEs.
**Rationale:** Multi-entity customers have no elimination workflow. `cross-workspace-dashboard` and `consolidated-flux` prove multi-entity usage is real. `query_transaction_lines` supports the lookup.
**Downsides:** Requires multi-entity Numeric setup; IC account tagging conventions vary.
**Confidence:** 78%
**Complexity:** High
**Status:** Unexplored

### 7. `vendor-accrual-confirmation-mailer`
**Description:** Reads open accrual tasks, identifies vendors with no invoice in Gmail in the past 30 days, sends templated "please confirm services rendered" confirmation emails, and logs sent confirmations back as Numeric task comments.
**Rationale:** Accrual cutoff confirmation emails are sent manually one-by-one — missing one is an audit finding. Write-back creates an auditable record. First Gmail-chain skill in the toolkit.
**Downsides:** Vendor email addresses need to be in Gmail/contacts.
**Confidence:** 84%
**Complexity:** Low-Medium
**Status:** Unexplored

### 8. `close-calendar-blocker`
**Description:** Reads the full close task list, due dates, and owners from Numeric, creates per-task focused-work calendar blocks on each preparer's Google Calendar with the Numeric task link, and creates review meeting slots in dependency order.
**Rationale:** Different from `close-day-zero-kickoff` (one kickoff event). This populates each person's entire close calendar so tasks don't get buried by meetings.
**Downsides:** Calendar OAuth required per team member.
**Confidence:** 81%
**Complexity:** Medium
**Status:** Unexplored

### 9. `stakeholder-deck-drafter`
**Description:** After close, pulls key metrics and flux commentary from Numeric, creates a structured Google Drive doc pre-populated with revenue/opex/headcount variances, then sends a Google Calendar invite to the CFO/board distribution list with the doc linked.
**Rationale:** "First draft of the board package" always blocks the controller. Pulling numbers, writing commentary, and scheduling the review meeting are three separate steps — all chainable in one skill run. DailyPay CFO explicitly requested a daily close digest email.
**Downsides:** Drive doc formatting requires consistent template setup.
**Confidence:** 82%
**Complexity:** Medium
**Status:** Unexplored

## Rejection Summary

| Idea | Reason Rejected |
|------|-----------------|
| controller-scope-flux-drafter | Enhancement to existing skill, not a new skill |
| accruals-confidence-scorer | Statistical model too expensive for skills format |
| flux-challenge-responder | Too narrow; better as flux skill enhancement |
| close-unblock-bot | Duplicates close-pulse + review-queue-packager |
| flux-to-ticket | Narrow, cross-system dependencies, vague trigger |
| fixed-asset-depreciation-reconciler | Merges into prepaid-amortization-scheduler |
| accrual-reversal-guardian | Feature add for complete-accruals-task |
| close-calendar-enforcer | Calendar conflict inference too fragile to generalize |
| fp-and-a-flux-handoff | Org-structure-dependent; can't package generically |
| pre-close-runway | Overlaps close-heartbeat + close-day-zero-kickoff |
| variance-escalation-router | Better as config inside pre-close-variance-alert |
| close-retro-auto | Schedule wrapper on existing close-retro |
| audit-trail-sentinel | Narrow audience; monitoring too complex |
| new-hire-close-coach | No reliable signal for "new user" detection |
| legal-accruals-intake | Org-structure-dependent |
| cash-signal-watch | Outside close-focused use case |
| All compounding/memory ideas (10) | Require persistent storage; skills are stateless |
| bank-rec-exception-driller | Narrower than survivors; rec structure already handled |
| cfo-push-digest | Partially covered by executive-report + pre-close-variance-alert |
| ar-collection-drafter | Removed by user — out of scope |
| notion-runbook-builder | Removed by user — out of scope |

## Session Log
- 2026-06-03: Initial ideation — 37 candidates generated across 4 frames + 8 MCP-chain ideas; 9 survived after two-pass filtering
