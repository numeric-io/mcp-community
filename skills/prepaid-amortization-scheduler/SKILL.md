---
name: prepaid-amortization-scheduler
user-invocable: true
description: >
  Manages prepaid expense amortization end-to-end: reads the prepaid schedule (vendor,
  amount, start date, term) from Numeric tasks or a reference file, generates the
  month-by-month amortization schedule, computes the current period's entries, produces
  an Excel workpaper, generates NetSuite-ready journal entry CSV, posts supporting
  comments to the Numeric task, and submits it. Saves the prepaid schedule to the task
  description so it carries forward automatically next period. Trigger when the user
  says: prepaid amortization, amortize prepaids, prepaid schedule, run prepaid entries,
  prepaid journal entries, prepaid workpaper, amortization schedule, process prepaids,
  monthly prepaid amortization, prepaid expense JEs, prepaid accrual entries, generate
  prepaid amortization, or any request to process or record monthly prepaid amortization
  journal entries.
---

## Iteration backlog (last reviewed 2026-06-03)
- [ ] Proration edge case undefined when start_date is mid-month AND last month is partial — document formula explicitly — small effort / improves accuracy
- [ ] GL account name fuzzy match can return two results for similarly named accounts — add disambiguation prompt — small effort / reduces errors
- [ ] Completed items removed from schedule by default, losing amortization history for the final period — keep for 1 period before removing — small effort / improves audit trail

# Prepaid Amortization Scheduler

Processes monthly prepaid amortization end-to-end: builds the schedule, computes
current-period entries with proper rounding, generates workpaper and NetSuite-ready JEs,
saves preferences before submitting the task.

The task name or description is: $ARGUMENTS

---

## Step 0: Load tools and workspace

**0a. Load tool schemas upfront** (Claude Code: batch them in one `ToolSearch` call. Other agents — Gemini CLI, Codex — expose tools directly, so skip to 0b.)

Load tools:
`list_workspaces, set_workspace, get_workspace_context, list_tasks, edit_task, add_task_comment, submit_task, list_financial_accounts, query_transaction_lines`

**0b. Workspace setup**

Check memory for `workspace_id`. If found, call `set_workspace`. Otherwise call `list_workspaces`, ask which workspace to use, call `set_workspace`, save to memory.

**0c. Parallel cold-start (max 3)**

After `set_workspace`, fire in parallel:
- `get_workspace_context` — open period, entities, period start/end dates
- `list_financial_accounts` — GL account map
- `list_tasks` with `name_contains: prepaid` and `period_id` = current period

---

## Step 0.5: Default schedule format

When no saved schedule is found, collect entries in this format:
```
vendor: [Vendor or description]
total_amount: [Total prepaid amount paid]
start_date: [YYYY-MM-DD — first month of amortization]
term_months: [Number of months to amortize over]
gl_account: [Prepaid asset GL account]
expense_account: [Target expense GL account]
entity: [Entity name, if multi-entity]
minimum_amount: [Skip this item if monthly amount < this — default $500]
```

**Materiality filter**: if `total_amount / term_months < minimum_amount`, skip the item and note it in the workpaper as "Below materiality — no JE generated."

**Rounding rule (straight-line)**:
- Base monthly amount = `floor(total_amount / term_months * 100) / 100` (round down to cents)
- Final period absorbs the rounding adjustment: `final_period_amount = total_amount - (base_monthly_amount × (term_months - 1))`
- The workpaper and JE CSV must show the final-period adjustment explicitly.

**Amortization type**: these are amortization entries, not accruals — they do not reverse. All JE memos must include "Prepaid amortization — no reversal" to satisfy audit trail requirements.

---

## Step 1: Find the task and check for existing entries

From `list_tasks`, identify all tasks matching "prepaid," "amortization," or the user's argument. If multiple tasks match, **list them all** and ask the user to select one — do not auto-select.

Read the selected task description. Look for a `## Prepaid Schedule` section. If found, parse as the saved schedule.

**Idempotency check**: call `get_task_comments` (or equivalent). If a comment containing `Prepaid amortization complete` for the current period already exists, warn the user: "Amortization for [Period Name] may have already been processed (comment found on [date]). Re-running will generate new JEs — continue?" Wait for explicit confirmation before proceeding.

Present the matched task and loaded schedule for user confirmation.

---

## Step 2: Compute current period amortization

For each item, determine if this period is in scope:
- `period_month >= start_date` AND `periods_elapsed < term_months`

Compute this period's amount using the rounding rule above. Mark items as **FINAL PERIOD** where applicable.

**Pre-computation GL balance reconciliation**: for each prepaid asset account, call `query_transaction_lines` to get the current running balance. Compare against the schedule's stated remaining balance:
```
GL balance of [Prepaid Account]: $[X]
Schedule remaining balance: $[Y]
Difference: $[Z]
```
If the difference exceeds the configured materiality threshold, **block progression** and require the user to explain or adjust before generating JEs:
"⚠️ Prepaid asset balance in GL ($X) does not agree with schedule remaining balance ($Y) — difference of $Z. Please investigate before posting entries."

---

## Step 3: Period-lock check

Before generating any JEs, verify the posting date (period end date from `get_workspace_context`) is in an open, unlocked period. If the period is locked or closed, stop and report:
"⚠️ Cannot generate entries — the period ending [date] appears to be locked. If you are processing a prior period, please confirm and unlock the period in NetSuite before proceeding."

---

## Step 4: Resolve GL account IDs

From `list_financial_accounts`, match `gl_account` (prepaid asset) and `expense_account` (target expense) by name. If a match is ambiguous (multiple accounts with similar names), show all candidates and ask the user to select.

---

## Step 5: Generate the Excel workpaper

Two tabs:

**Tab 1: Monthly Schedule**
One row per prepaid item. All months shown. Current period column highlighted. "Final Period" flagged. Rounding adjustment shown in the final period column explicitly.

**Tab 2: Current Period Entries**
| Vendor | Dr Account | Cr Account | Amount | Adjustment | Memo | Period |
One row per active item. Rounding adjustment shown where applicable.

File: `prepaid_amortization_[period_name]_[period_id].xlsx` (include period_id for traceability).

---

## Step 6: Generate NetSuite-ready JE CSV

```csv
Journal Date,Memo,Line Description,Account Number,Debit,Credit,External ID
[period_end_date],[period_id] Prepaid Amortization,[vendor] amortization - no reversal,[expense_acct_id],[amount],,PREPAID-[period_id]-[vendor_code]-DR
[period_end_date],[period_id] Prepaid Amortization,[vendor] amortization - no reversal,[prepaid_asset_acct_id],,[amount],PREPAID-[period_id]-[vendor_code]-CR
```

**External ID** format: `PREPAID-[period_id]-[vendor_code]-[DR/CR]` — provides idempotency key: if the same CSV is uploaded twice, NetSuite will reject the second as a duplicate External ID. Include this in the user instructions.

File: `prepaid_JE_[period_name]_[period_id].csv`

---

## Step 7: Confirmation gate — show full picture before any mutation

Present for user review before posting:
```
Prepaid amortization for [Period Name]:

GL balance check: [agreement / ⚠️ difference $X — resolved by user]
Period lock check: ✅ period [period_id] is open

[N] active entries — total $[X,XXX]
• [Vendor] — Dr [Expense Account] $[X] / Cr Prepaid $[X] — [N months remaining]
• [Vendor] — $[X] — FINAL PERIOD (rounding adjustment: $[Y])

[N] items skipped (below $[minimum_amount] materiality)

Files ready:
• prepaid_amortization_[period].xlsx
• prepaid_JE_[period]_[period_id].csv (External IDs provide double-post protection)

Post to NetSuite / download CSV for manual upload / re-run with changes?
```

---

## Step 8: Save updated schedule to task description — BEFORE submitting

Call `edit_task` **before** calling `submit_task`. Saving preferences after submission risks losing the schedule if the task becomes read-only after submission.

```markdown
## Prepaid Schedule
<!-- Updated [YYYY-MM-DD] by prepaid-amortization-scheduler — [N] active items -->

| Vendor | Total | Start | Term | Monthly | Periods Remaining | Status |
|--------|-------|-------|------|---------|-------------------|--------|
| [Vendor] | $[X] | [date] | [N]mo | $[X] | [N] | active |
| [Vendor] | $[X] | [date] | [N]mo | $[X] | 1 | FINAL PERIOD — remove next cycle |
| [Vendor] | $[X] | [date] | [N]mo | $[X] | 0 | completed [period_name] — remove next cycle |

## Amortization preferences
expense_account_default: [account name]
prepaid_asset_account: [account name]
entity: [entity name]
materiality_minimum_monthly: $[X]
```

Keep completed items for one additional period (for the final-period audit trail), then remove.

---

## Step 9: Post JEs and submit task

**If a NetSuite tool is available** (names like `ns_createRecord` or similar): post via it. Capture the returned JE reference numbers. If any post fails, stop and report — do not submit the task until all entries are confirmed posted. If no NetSuite tool is present, skip posting — the CSV (Step 6) is the deliverable for manual upload.

**If manual upload**: save CSV and tell user: "Upload `prepaid_JE_[period]_[period_id].csv` to NetSuite. The External IDs prevent double-posting if uploaded twice."

Call `add_task_comment`:
```
📋 Prepaid amortization complete — [Period Name] — [YYYY-MM-DD HH:MM]
Auto-generated by prepaid-amortization-scheduler

[N] prepaids amortized · Total: $[X,XXX]
• [Vendor] — $[amount] — [months remaining] months remaining
• [Vendor] — $[amount] — FINAL PERIOD (rounding absorbed: $[Y])

GL balance reconciliation: [agreed / difference $X — user approved]
JEs posted to NetSuite: [reference numbers]  (or: CSV saved for manual upload — filename: [name])
Workpaper: [filename]
Period: [period_id]
```

Call `submit_task` only after the comment is written successfully.
