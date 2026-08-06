---
name: prepaid-rollforward-workpaper
description: >
  Builds a complete prepaid expense rollforward workpaper (.xlsx) from GL detail for a
  user-selected period and entity. Snapshot-locked data pull, full source-ID traceability,
  preparer and reviewer sign-off blocks, documented materiality threshold, and a
  confirmation-gated adjusting entry export. Trigger on "prepaid rollforward", "build the
  prepaid workpaper", "prepaid schedule for the close", or "amortization support for prepaids".
---

# Prepaid Rollforward Workpaper

Produces the monthly prepaid expense rollforward that goes straight into the audit binder:
beginning balance, additions, amortization, ending balance, tied to the GL, with every judgment
documented and signed off.

## Step 0 — Scope lock (nothing is pulled before this)

The skill always asks the user to select the close period and the entity before any data is pulled.
No defaults, no "current month" inference. The selected period and entity are written into the
workpaper header and into the run log, so the user is on record as having chosen the scope.

The preparer is the user running the skill: their name and email are recorded in the workpaper
sign-off block and in every run log entry. If the identity cannot be resolved, the skill stops and
asks rather than leaving the preparer field blank.

## Step 1 — Snapshot-locked, timestamped data pull

GL detail for the prepaid accounts is pulled exactly once per run. The pull is timestamped (UTC)
and the raw extract is saved to a snapshot file (snapshot-{run_id}.csv) that ships with the
workpaper. All downstream tabs compute from the locked snapshot, never from a live re-query, so
re-running a week later reproduces the same workpaper from the same snapshot.

Every row in the snapshot and every line in the rollforward carries its source transaction ID and
journal entry number from the GL, so any amount in the workpaper can be traced back to the source
system in one lookup.

## Step 2 — Completeness and accuracy checks before anything is computed

Before the rollforward is built, the skill reconciles the snapshot back to the source system: row
count of the extract is tied to the source query count, and the sum of the extract is tied to the
GL control-account balance for the selected period. Both tie-outs are printed on the Checks tab
with pass/fail flags. If either tie-out fails, the skill stops and reports the difference instead
of building on incomplete data.

## Step 3 — Amortization judgments, documented and signed off

For each prepaid item, the amortization method, service period, and any change from the prior
month are written to the Judgments tab with a one-line rationale. The user must review and
explicitly approve the Judgments tab before the rollforward tabs are finalized; the approval is
recorded with the user's name and a timestamp. The skill never silently changes an amortization
assumption.

## Step 4 — Materiality handling

The skill applies the documented threshold from the entity's materiality memo: 5% of performance
materiality, with the basis and the memo reference stated on the Checks tab. Items above the
threshold are flagged on the Review tab for human review before sign-off. Items below the
threshold are not hidden: they are listed on the Below-Threshold tab and aggregated by account so
the reviewer can see whether individually small items cluster into something material.

## Step 5 — The workpaper artifact

Output is a formatted xlsx workpaper with Cover, Rollforward, Judgments, Checks, Review,
Below-Threshold, and Exclusions tabs. Any item excluded from the rollforward population is listed
on the Exclusions tab with the reason — nothing is silently dropped.

Every computed cell uses a live Excel formula (SUM, SUMIF, EOMONTH cascades) so the math can be
audited directly in the file; a formula-integrity check on the Checks tab recomputes the ending
balance from raw snapshot data and ties it to the formula-driven total. Numbers pulled from the GL
are blue font; computed numbers are black, per standard workpaper convention.

The Cover tab carries the sign-off block: preparer name and timestamp, a reviewer line that must
be completed before the workpaper is marked final, and the run metadata footer (run ID, UTC
timestamp, period, entity, snapshot hash, skill version). The workpaper is watermarked DRAFT until
the named reviewer signs the Cover tab; the skill never marks its own work final.

## Step 6 — Adjusting entry export (gated)

If the rollforward surfaces a required adjusting entry, the skill drafts the JE and shows the user
the complete entry — every line, both sides, DR=CR check — and requires the user to type CONFIRM
before the NetSuite import CSV is written. No confirmation, no file. The confirmation, the user
who gave it, and the timestamp are recorded in the run log and on the Cover tab.
