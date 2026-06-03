---
name: vendor-accrual-confirmation-mailer
user-invocable: true
description: >
  Sends accrual cutoff confirmation emails to vendors via Gmail for period-end close.
  Reads open accrual tasks from Numeric, identifies vendors with no invoice received in
  the past 30 days, collects and confirms vendor email addresses, presents drafts for
  controller review, sends approved emails via Gmail, and logs each confirmation as a
  task comment in Numeric for auditability. Carries forward confirmed vendor contacts,
  exclusions, and estimate overrides in the task description so each period refines rather
  than restarts. Prevents duplicate sends using a cooldown
  check on prior task comments. Trigger when the user says: send accrual confirmations,
  vendor confirmation emails, accrual cutoff emails, confirm services with vendors,
  vendor accrual emails, send cutoff confirmations, email vendors for accruals, accrual
  period-end confirmations, vendor outreach for accruals, confirm vendor services,
  or any request to reach out to vendors to confirm period-end accruals via email.
---

## Iteration backlog (last reviewed 2026-06-03)
- [ ] Gmail invoice check misses invoices in NetSuite/Coupa/EDI — add note to user that non-Gmail AP systems need manual check — small effort / improves accuracy
- [ ] Reply tracking not automated — add Gmail MCP search step in follow-up run to check for replies — medium effort / closes the loop
- [ ] One-time vendors included as confirmation candidates — now mitigated by persisted `excluded_vendors`; could add auto-detection of first-occurrence-only vendors — small effort / reduces noise

# Vendor Accrual Confirmation Mailer

Sends period-end confirmation emails to vendors where no invoice has been received in
the past 30 days, with full controller review before sending. Logs each outreach to the
Numeric task for an auditable record. Prevents duplicate sends using task comment history.

---

## Step 0: Load tools and workspace

**0a. Load tool schemas upfront** (Claude Code: batch them in one `ToolSearch` call. Other agents — Gemini CLI, Codex — expose tools directly, so skip to 0b.)

Load tools:
`list_workspaces, set_workspace, get_workspace_context, list_tasks, get_task_comments, add_task_comment, edit_task, query_transaction_lines`

**Email connector (agent-agnostic):** check for a Gmail/email tool (names like `gmail`, `send_email`, `draft_email`, `search`, or similar). Email is core to this skill — but if no email tool is available, the skill still drafts every confirmation email and saves them to a file (`vendor_confirmations_[period].md`) for the user to send manually. It never sends silently or fails without an artifact.

**0b. Workspace setup**

Check memory for `workspace_id`. If found, call `set_workspace`. Otherwise call `list_workspaces`, ask which workspace to use, call `set_workspace`, save to memory.

**0c. Parallel cold-start (max 3)**

After `set_workspace`, fire in parallel:
- `get_workspace_context` — open period, period end date, entities
- `list_tasks` with `status: PENDING` and `name_contains: accru` — filter server-side

---

## Step 1: Identify open accrual tasks

From the task list, filter to accrual-related tasks (name/description containing: "accrue", "accrual", "period-end expense", "cutoff", "month-end vendor"). If `$ARGUMENTS` provided, fuzzy-match a specific task.

Present matched tasks and ask user to confirm which to process.

**Short-circuit on empty**: if no accrual tasks found, report and stop.

---

## Step 1.5: Load saved preferences from the task description (the "next time" memory)

Read the confirmed task's description for a `## Vendor confirmation preferences` block written by a prior run. It carries forward everything the user decided last period so this run **refines rather than restarts**:

```
## Vendor confirmation preferences
<!-- Maintained by vendor-accrual-confirmation-mailer — updated [YYYY-MM-DD] -->

vendor_contacts:           # confirmed emails — reuse, don't re-resolve
  - Ashby: billing@ashbyhq.com
  - Datadog: ap@datadoghq.com
excluded_vendors:          # NOT accrual candidates — do not re-surface
  - Carta: prepaid, not an accrual (per user, 2026-05)
  - Earth Class Mail: one-time, project ended (2026-04)
estimate_overrides:        # corrected estimation method/amount
  - Datadog: use 3-month average, not prior month
recurring_accrual_vendors: # known true accrual vendors — high confidence
  - Ashby
  - Datadog
```

If no block exists (first run), proceed with defaults — the block gets created in Step 8b.

**Precedence:** defaults < saved preferences (this block) < explicit instructions elsewhere in the task description < the user's explicit overrides during this run.

---

## Step 2: Cooldown check — prevent duplicate sends

For each task, call `get_task_comments`. If a comment containing `📧 Vendor confirmation email sent` was posted within the **last 30 days** (one per close cycle), skip the task and note it in the summary. This prevents re-sending to the same vendors in the same close period.

---

## Step 3: Extract vendor candidates from transaction history

For each confirmed task, call `query_transaction_lines` for the current open period. Identify vendors with:
- $0 activity in the current period AND
- Transactions in the most recently completed period

For each candidate vendor, the **estimated amount** is the most recent completed month's spend.

**Apply saved preferences from Step 1.5 before showing anything to the user:**
- **Drop `excluded_vendors`** from the candidate list entirely — don't re-surface vendors the user already ruled out. List them under "Auto-excluded (your prior decision)" in the review so the user can un-exclude if needed.
- **Apply `estimate_overrides`** — use the saved method (e.g. 3-month average) instead of the default prior-month figure for those vendors.
- **Tag `recurring_accrual_vendors`** as high-confidence so the user can skim past them.

**Controller review of estimates** — present the refined list, separating known from new so the user confirms *deltas*, not the whole list each month:
```
Vendor candidates for confirmation:

Known recurring (confirmed before):
• [Vendor] — estimated: $[X] (source: [prior month / 3-mo avg override])

⭐ NEW this period (not seen before — please verify):
• [Vendor] — estimated: $[X] (source: prior month spend)

Auto-excluded (your prior decision — say so to re-include):
• [Vendor] — [reason from excluded_vendors]

Adjust estimates, exclude any vendor, or confirm to proceed.
```

Capture any new exclusions or estimate changes the user makes here — they get written back in Step 8b. Wait for confirmation before proceeding.

---

## Step 4: Resolve vendor email addresses

For each vendor, attempt to resolve an email address in this order:

1. **Saved `vendor_contacts` (from Step 1.5)** — if the vendor already has a confirmed email from a prior period, **reuse it** — do not re-resolve or re-ask.
2. **Gmail search** — search for the most recent email thread involving this vendor: `from:"[vendor_name]" OR to:"[vendor_name]"` (use quoted vendor name to prevent multi-word false matches). Extract the sender/recipient email from the most recent thread.
3. **User input** — if no address found via either method, ask the user: "I couldn't find an email address for [Vendor Name]. Please provide their billing contact email, or type 'skip' to exclude them."

Present all resolved email addresses to the user for confirmation before drafting:
```
Resolved vendor contacts:
• [Vendor Name] → [email address] (source: task description / Gmail / user-provided)
• [Vendor Name] → ⚠️ Not resolved — will be skipped
```

Require explicit user confirmation of the email list before proceeding.

---

## Step 5: Check Gmail for recent invoices

For confirmed vendors with resolved emails, search Gmail for invoice/billing emails in the past 30 days using the resolved email address (not the vendor name): `from:[resolved_email] newer_than:30d`.

**Note for user**: "This check only covers Gmail. If your AP team uses NetSuite Vendor Portal, Coupa, Tipalti, or EDI, invoices from those systems won't appear here — verify those vendors separately."

- Invoice found → remove from send list, note "Invoice found — skipped"
- No invoice found → keep for outreach

Confirm the final filtered list with the user.

---

## Step 6: Draft confirmation emails

Use the **period end date from `get_workspace_context`** (not a computed "last day of month") as the cutoff date.

Draft one email per vendor:
```
Subject: Services Confirmation — [Company Name] — [Period Name]

Hi [Vendor Name] team,

As part of our [Period Name] close process, we are confirming services through [period_end_date_from_context].

Based on our records, we estimate services of approximately $[controller_approved_amount] 
for this period. Please note this is an internal estimate — your actual invoice will be 
the authoritative figure.

Could you please confirm:
1. Services were performed / goods were delivered through [period_end_date]
2. We can expect your invoice by [invoice_due_date = period_end_date + 10 business days]

If the amount or timing differs significantly, please let us know.

Thank you,
[User name]
```

Present all drafts to the user. Allow individual edits or removal. **Do not send until explicit approval.** Show the recipient email address for each draft so the user can verify.

---

## Step 7: Send emails

After user approval, send each email via Gmail MCP **sequentially** with a 3-second pause between sends. For each send, capture: vendor name, recipient email, timestamp.

On any send failure, stop the sequence and report: "Send failed for [Vendor] — [reason]. [N] sent, [M] remaining. Fix the issue and re-run to send the remainder (the cooldown check will skip already-sent vendors)."

---

## Step 8: Write back to Numeric task comments

After each successful send, call `add_task_comment` on the associated Numeric task:
```
📧 Vendor confirmation email sent to [Vendor Name] <[email]> on [YYYY-MM-DD HH:MM]
Estimated amount confirmed with controller: $[X]
Cutoff date in email: [period_end_date]
Reply status: pending — monitor Gmail for response (manual follow-up required)
```

This comment is the **per-send audit trail** (and the cooldown marker Step 2 reads). It is distinct from the preferences block written next.

---

## Step 8b: Persist preferences to the task description (the "for next time" write-back)

This is what makes the next period's run smarter. Call `edit_task` to create or update the `## Vendor confirmation preferences` block (format in Step 1.5) on the accrual task, merging in everything decided this run:

- **`vendor_contacts`** — add/refresh every email confirmed this period (so next month reuses them instead of re-asking).
- **`excluded_vendors`** — add any vendor the user excluded this run, with the reason and date they gave. Carry forward prior exclusions; don't drop them.
- **`estimate_overrides`** — record any estimate method the user corrected (e.g. "use 3-month average").
- **`recurring_accrual_vendors`** — add vendors confirmed and sent this period so they're tagged high-confidence next time.

Merge, don't overwrite — preserve prior entries the user didn't change. Stamp the block with today's date. If the block is approaching ~10K characters, prune the oldest one-time exclusions and note it.

This write-back is the difference between an audit log and a learning loop: the comment records *what happened*; this block records *what to do next time*.

---

## Step 9: Summary to user

```
Accrual confirmation sweep — [date]

✅ Emails sent: [N]
  • [Vendor] — [email] — $[estimated amount]

⏭ Skipped — invoice found in Gmail: [N]
⏸ Skipped — already sent this period (cooldown): [N]
❌ Skipped — no email address resolved: [N]
  • [Vendor names] — add their contact to the task description and re-run

⚠️ Reminder: replies require manual follow-up. Check Gmail for responses before finalizing accruals.
⚠️ Note: only Gmail inbox was checked for invoices. Verify any AP-platform vendors separately.

Task comments logged for all sent confirmations.
```
