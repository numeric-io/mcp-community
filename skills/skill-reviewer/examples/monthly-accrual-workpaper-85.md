---
name: monthly-accrual-workpaper
description: >
  Builds the month-end accrual workpaper (.xlsx) from vendor spend history for a user-selected
  period and entity, with preparer/reviewer sign-off and a confirmation-gated NetSuite JE export.
  Trigger on "monthly accruals", "build the accrual workpaper", or "accrual support for the close".
---

# Monthly Accrual Workpaper

Builds the accrual estimate workpaper for the close: vendor-by-vendor accrual candidates from
spend history, a reviewable estimate for each, and a gated JE export.

## Step 0 — Scope

The skill asks the user to select the close period and the entity before any data is pulled, and
records both in the workpaper header. The preparer is the user running the skill; their name and
email are recorded in the workpaper sign-off block.

## Step 1 — Data pull

Vendor spend history is pulled from the GL and the pull is timestamped (UTC) in the workpaper
header. Each vendor line on the Detail tab carries the source transaction IDs used to compute the
estimate. The Summary tab presents one row per vendor without repeating the transaction detail.

Re-running the skill for the same period pulls fresh data and rebuilds the workpaper, so the
latest GL activity is always reflected.

## Step 2 — Completeness check

Before estimating, the skill verifies the pulled row count matches the number of rows returned by
the source query and reports the count on the Checks tab.

## Step 3 — Estimation judgments

For each accrual candidate the estimation method (three-month average, contract-based, or manual)
is written to the Judgments tab with a one-line rationale, and the user must approve the
Judgments tab before the workpaper is finalized. Approvals are recorded with name and timestamp.

## Step 4 — Materiality

The skill applies the documented threshold from the entity's materiality memo: 5% of performance
materiality, basis and memo reference stated on the Checks tab. Vendors above the threshold are
flagged on the Review tab for human review before sign-off. Vendors below the threshold are
excluded from the accrual population; the Cover tab discloses how many vendors were excluded
under the threshold.

## Step 5 — The workpaper artifact

Output is a formatted xlsx workpaper with Cover, Summary, Detail, Judgments, Checks, and Review
tabs. The Detail tab computes with live Excel formulas; the Summary tab presents the final
accrual per vendor as stated values carried over from Detail. GL-sourced numbers are blue font;
computed numbers are black.

The Cover tab carries the sign-off block: preparer name and timestamp, a reviewer line that must
be completed before the workpaper is marked final, and a run metadata footer (run ID, UTC
timestamp, period, entity, skill version). The workpaper is watermarked DRAFT until the named
reviewer signs the Cover tab; the skill never marks its own work final.

## Step 6 — JE export (gated)

The skill drafts the accrual JE and shows the user the complete entry — every line, both sides,
DR=CR check — and requires the user to type CONFIRM before the NetSuite import CSV is written.
The confirmation, the user who gave it, and the timestamp are recorded on the Cover tab.
