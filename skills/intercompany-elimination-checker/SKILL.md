---
name: intercompany-elimination-checker
user-invocable: true
description: >
  Detects and resolves intercompany balance mismatches across entities in a consolidated
  Numeric workspace. Queries transaction lines across entities to identify intercompany
  receivables and payables, surfaces unmatched pairs, generates separate correcting and
  elimination journal entries for review, and posts findings to relevant Numeric tasks.
  Trigger when the user says: intercompany reconciliation, IC elimination, intercompany
  check, eliminate intercompany, intercompany balances, IC rec, match intercompany entries,
  consolidation elimination, find intercompany mismatches, intercompany journal entries,
  IC balances don't tie, reconcile intercompany, elimination entries, check intercompany,
  or any request to identify or resolve intercompany balance discrepancies across entities.
---

# Intercompany Elimination Checker

Scans transaction lines across all entities in a consolidated workspace, surfaces
unmatched IC payable/receivable pairs, and generates **separate** correcting and
elimination JE files. Every counterparty inference is shown to the user for confirmation
before any JE is generated.

---

## Step 0: Load tools and workspace

**0a. Load tool schemas upfront** (Claude Code: batch them in one `ToolSearch` call. Other agents — Gemini CLI, Codex — expose tools directly, so skip to 0b.)

Load tools:
`list_workspaces, set_workspace, get_workspace_context, list_financial_accounts, list_reports, get_report_data, query_transaction_lines, list_tasks, get_task_comments, add_task_comment, edit_task, create_task`

**0b. Workspace setup**

Check memory for `workspace_id`. If found, call `set_workspace`. Otherwise call `list_workspaces`, ask which workspace to use, call `set_workspace`, save to memory.

**Multi-entity check**: from `get_workspace_context`, if only 1 entity is returned, warn the user: "Only 1 entity detected in this workspace. This skill requires a consolidated workspace with multiple entities. If your entities are in separate workspaces, this skill cannot cross-workspace match — IC reconciliation requires all entities to be visible in the same workspace." Ask whether to continue or stop.

**0c. Parallel cold-start (max 3)**

After `set_workspace`, fire in parallel:
- `get_workspace_context` — all entities, current period, period end date
- `list_financial_accounts` — full chart of accounts across all entities

---

## Step 0.5: Load saved mappings from the task description (the "next time" memory)

Find the IC/consolidation task (via `list_tasks`, `name_contains: intercompany,consolidation,IC`) and read its description for an `## Intercompany mappings` block written by a prior run. This carries forward everything you confirmed last period so this run **auto-matches the known and only asks about the new**:

```
## Intercompany mappings
<!-- Maintained by intercompany-elimination-checker — updated [YYYY-MM-DD] -->

ic_accounts:                      # confirmed IC accounts (don't re-prompt)
  - "1305 — Due from Affiliates"
  - "2105 — Due to Affiliates"
counterparty_rules:               # confirmed inference rules — auto-apply
  - memo_contains "GlobalCo"      -> Entity B
  - reference_prefix "IC-ENTB"    -> Entity B
  - memo_contains "Stellar"       -> Entity C
confirmed_pairs:                  # known IC partner pairs
  - Entity A <-> Entity B
  - Entity A <-> Entity C
mismatch_threshold: 1000          # confirmed materiality floor for flagging
```

If no block exists (first run), proceed with defaults — the block gets created in Step 6b.

**Precedence:** defaults < saved mappings (this block) < the user's explicit overrides during this run.

---

## Step 1: Identify intercompany accounts

Start from the saved `ic_accounts` (Step 0.5). For anything not already saved, scan `list_financial_accounts` for IC accounts by name patterns: "intercompany", "due to", "due from", "IC", "interco", "related party" (plus common GL code ranges, e.g. 13xx receivables, 21xx payables).

Present the list — **saved accounts pre-checked, newly-detected ones flagged ⭐ for review** — and confirm. The user can add/remove here. (Do not re-ask about accounts already confirmed in a prior period unless the chart of accounts changed.)

**Idempotency check**: search the task comments for `🔄 IC Elimination Check — [Period Name]`. If a prior-run comment for *this* period is found, warn the user: "An IC elimination run appears to have been performed for this period already (see comment from [date]). Re-running will generate new JE files — ensure prior JEs have NOT been posted before continuing."

---

## Step 2: Balances first, lines only for mismatches (the query funnel)

**2a. Aggregate pass — no transactions yet.** Pull the IC account **balances per entity** from report data (a balance sheet report keyed by org × account, or a counterparty-pivoted report if one exists). One aggregate call replaces N×M transaction pulls.

**2b. Pair the balances.** Entity A's "due from B" balance vs Entity B's "due to A" balance, at the aggregate level:
- **Pair ties at aggregate** → balanced. Generate the elimination JE from the balances — **no transaction drill needed at all.**
- **Pair doesn't tie** → mismatch. Only these descend to line level.
- **Account can't be paired at aggregate** (one generic IC account serving multiple counterparties, and no counterparty-pivoted report available) → treat it like a mismatch: drill its lines and let Step 3's counterparty inference attribute them.

**2c. Drill mismatched pairs only.** For each mismatched pair, call `query_transaction_lines` on the relevant IC account rows (batched **max 3 in parallel**, narrowest window) to diagnose the difference. Build the ledger only for these:
```
entity | account_type | amount | memo | transaction_date | reference_number | transaction_id
```

In a typical close most pairs tie — meaning most periods never touch transaction lines at all.

**Note on currency**: if the workspace has entities in multiple currencies, flag: "⚠️ Multi-currency workspace detected. Transaction amounts are shown in local currency. IC comparisons require functional currency conversion — this skill does not perform FX translation. Review amounts carefully or normalize to functional currency before using this output."

---

## Step 3: Infer counterparty entity — with mandatory user confirmation for EVERY transaction

For each IC transaction, attempt to infer the counterparty entity, in this order:
0. **Saved `counterparty_rules` (from Step 0.5)** — if a transaction matches a confirmed rule (memo contains X, reference prefix Y), **auto-assign the counterparty — do not re-ask.** These were confirmed in a prior period.
1. **Reference number match** — if the reference number appears in another entity's IC transaction in the same period and amount, link them
2. **Memo text pattern** — look for entity names in the memo (e.g., "Due from Entity B")
3. **Unknown** — no inference possible

**Confirm only the deltas** — auto-matched transactions are shown for awareness but don't require re-approval; new/changed/unknown ones require it:
```
━━━ Counterparty Inference ━━━

Auto-matched by saved rules ([N] — no action needed):
  Entity A | $125,000 | memo "GlobalCo" → Entity B  (rule: memo_contains "GlobalCo")

⭐ NEW / unmatched — please confirm:
  Entity A | $80,000 | Reference: IC-2024-03-001 → inferred Entity C
    ✅ Confirm (save as rule) / ❌ Correct to: [entity] / ❓ Unknown
```

When the user confirms a NEW inference, ask whether to **save it as a reusable rule** (e.g. "always map memo containing 'Stellar' → Entity C") so it auto-matches next period. Capture confirmed rules for write-back in Step 6b. Only after the full counterparty map is confirmed does the skill proceed to match calculations.

---

## Step 4: Match and compute differences

For each confirmed entity pair, compute:
- Entity A "due from" Entity B = sum of A's IC receivable transactions attributed to B
- Entity B "due to" Entity A = sum of B's IC payable transactions attributed to A
- Difference = due_from_A - due_to_B

**Mismatch materiality threshold** (configurable, defaulting to workspace tier):
- Small: flag if |difference| > $500
- Medium: flag if |difference| > $1,000
- Large: flag if |difference| > $5,000

Differences below the threshold: log as "FX/rounding — investigate" (never silently dismiss). Do not characterize as noise — small differences may indicate systematic errors.

---

## Step 5: Generate JEs — in two completely separate files

**File 1: Correcting entries** (`ic_corrections_[period_id].csv`) — for entity-level posting to fix mismatches
These post at the individual entity level and adjust IC account balances.

**File 2: Elimination entries** (`ic_eliminations_[period_id].csv`) — for consolidation-level posting only
These post at the consolidation parent level and should NEVER be posted at the entity level.

Each file has a prominent header comment:
- Corrections file: `# ENTITY-LEVEL POSTING — post to each subsidiary separately`
- Eliminations file: `# CONSOLIDATION-LEVEL POSTING ONLY — do NOT post to individual entities`

Both CSVs include External IDs in format `IC-[period_id]-[entity_pair]-[type]-[DR/CR]` for idempotency.

Present all entries for user review before generating files:
```
━━━ Correcting entries (entity-level) ━━━
Entity A: Dr IC Receivable from C $7,500 / Cr [Correction account]
Entity C: Dr [Correction account] / Cr IC Payable to A $7,500

━━━ Elimination entries (consolidation-level only) ━━━
Eliminating Entity A ↔ Entity B:
Dr IC Payable to B (A's books) $125,000
Cr IC Receivable from A (B's books) $125,000
```

---

## Step 6: Log findings to Numeric

Search `list_tasks` for IC-related tasks (server-side filter `name_contains: intercompany,consolidation,IC rec`). For each match, call `add_task_comment`:
```
🔄 IC Elimination Check — [Period Name] — [YYYY-MM-DD HH:MM]
Auto-generated by intercompany-elimination-checker

[N] entity pairs analyzed
✅ [N] balanced — elimination JEs in: ic_eliminations_[period_id].csv
⚠️  [N] mismatched — correcting JEs in: ic_corrections_[period_id].csv
   • [Entity pair] — $[difference] — [diagnosis]

⚠️ IMPORTANT: ic_corrections → post at entity level. ic_eliminations → consolidation parent only.
[Multi-currency warning if applicable]
Period: [period_id]
```

If no IC task exists, offer to create one.

This comment is the **per-run audit trail**. It is distinct from the mappings block written next.

---

## Step 6b: Persist mappings to the task description (the "for next time" write-back)

This is what stops the skill from re-asking you to identify the same counterparties every month. Call `edit_task` to create or update the `## Intercompany mappings` block (format in Step 0.5) on the IC task, merging in everything confirmed this run:

- **`ic_accounts`** — the confirmed IC account list (replaces the old session-memory approach so it survives across sessions and users).
- **`counterparty_rules`** — add every rule the user confirmed this run ("memo contains X → Entity B", "reference prefix Y → Entity C"). Carry forward prior rules; don't drop them.
- **`confirmed_pairs`** — the entity pairs found to transact intercompany.
- **`mismatch_threshold`** — the materiality floor used, if the user adjusted it.

Merge, don't overwrite — preserve prior entries the user didn't change. Stamp with today's date. If a rule stops matching anything for several periods, note it for the user rather than deleting silently.

Next period, Step 0.5 reads this block and Step 3 auto-applies the rules — so the user confirms only genuinely new transactions instead of re-approving the whole ledger.

---

## Step 7: Summary to user

```
Intercompany check complete — [Period Name]

[N] entity pairs analyzed
✅ [N] balanced — elimination JEs ready
⚠️  [N] mismatched — correcting entries required first:
   • [Entity pair] — $[difference] — [diagnosis]

Files created (keep these separate — different posting levels):
📄 ic_corrections_[period_id].csv → POST AT ENTITY LEVEL
📄 ic_eliminations_[period_id].csv → CONSOLIDATION PARENT ONLY

[⚠️ Multi-currency: amounts in local currency — normalize before comparing]

Next: Post corrections to each entity, re-run to confirm all pairs balance, then post eliminations.

Saved [N] counterparty rules for next period — future runs will auto-match these.
```
