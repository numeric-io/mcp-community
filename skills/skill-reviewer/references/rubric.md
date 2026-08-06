# The Audit-Readiness Rubric — full detail (rubric v3.0)

This file is the fact-finder's field guide. The engine (`scripts/engine.py`) owns every number —
weights, credit, thresholds, blocker gates. This file explains the *judgment* side: what each
dimension is really asking, how to classify, how to calibrate confidence, and what the reference
skills look like.

## Contents

1. [Confidence calibration](#confidence-calibration)
2. [The evidence rule](#the-evidence-rule)
3. [Categories](#categories)
4. [The six dimensions in depth](#the-six-dimensions-in-depth)
5. [IPE workflow patterns A–D](#ipe-workflow-patterns)
6. [The five materiality concepts](#the-five-materiality-concepts)
7. [The 18 controls](#the-18-controls)
8. [Baseline controls and blockers](#baseline-controls-and-blockers)
9. [Reference skills (directional exemplars)](#reference-skills)

---

## Confidence calibration

Applies to **every** confidence field, 0–100:

| Range | Meaning |
|---|---|
| 95–100 | The submission states it explicitly; you can quote the exact text. |
| 80–94 | Strongly implied by specific text you can point to. |
| 60–79 | Reasonable inference from the skill's structure or behavior. |
| 40–59 | Weak inference — could plausibly go either way. |
| 0–39 | Essentially cannot tell. Prefer status `unverifiable` instead of guessing. |

Calibrate honestly: the engine enforces a **60% reliance floor** — anything below it is routed to
a human-verification queue, and that is the *correct* outcome for a shaky judgment. An
overconfident wrong answer is far worse than an honest "unverifiable".

## The evidence rule

`evidence` must be a **verbatim quote copied exactly from the submission** (≤30 words; you may
join two fragments with `...`). The engine string-matches every quote against the submission
text:

- A quote that does not appear in the submission is flagged `quote_not_found` and the control's
  confidence is **capped at 40%**.
- A `pass` or `partial` with no verifiable quote is **capped at 50%**.
- When you judge by **absence** (the control is missing), use an empty string `""` and explain
  the absence in the note.

Do not paraphrase into the evidence field. Do not reconstruct a quote from memory. Copy it.

## Categories

**CATEGORY 1 — AUDIT EVIDENCE PRODUCER.** Output is directly reviewed by auditors: workpapers,
journal entries, reconciliations, evidence packages, sign-off artifacts. Full rubric applies.

**CATEGORY 2 — PROCESS ENABLER.** Output feeds an auditable process but is not itself the audit
artifact: import generators, migration tools, setup/config workflows. Judge O1–O3 against
"structured and traceable output", not workpaper formatting.

**CATEGORY 3 — WORKFLOW ORCHESTRATOR.** No financial output and no audit-facing artifact:
meeting prep, SM requests, Slack drafts, checklist diagnostics. Out of scope for this rubric.

Also decide `performs_review_function`: **true** when the skill reviews, validates, reconciles,
clears, or approves financial data — i.e. it *operates as a control* rather than merely preparing
data. Give it its own confidence. This flag makes M1 a baseline control for Category 1 skills.

**Category 3 handling.** If you are ≥75% confident it is Category 3, return the short redirect
schema and stop. If you lean Category 3 with less confidence, classify it 3 but return the
**full** schema anyway (judge all 18 controls) — the engine lets the user flip the category with
`--override-category` and rescore your findings instantly, with no second model pass.

## The six dimensions in depth

You do not score these — the engine does. This is context for your findings.

### 1. Evidence Trail & Sourcing (weight 25) — "Traceability"

Explicit period, timestamped pulls, source IDs cited. Without traceability nothing else holds up.

**Failure mode:** numbers land in output with no traceable source; the auditor cannot tie out.

### 2. Attribution & Sign-Off (weight 30) — segregation of duties, highest stakes

Preparer identified, reviewer required before final state, write-back gated behind confirmation,
draft vs. final distinguished.

**Failure mode:** one person prepares, approves, and posts in a single shot with no breakpoint.

**Do NOT award reviewer credit for a control that lives entirely outside the skill** (e.g. "the
platform will route it to a reviewer"). The control must be in the skill's own logic.

### 3. IPE Risk & Evidence Sufficiency (weight 20) — Information Produced by the Entity

Classify the workflow pattern (see below) and judge whether the skill's evidence design matches
it. A Pattern C or D skill whose evidence design ignores completeness / transformation / judgment
sign-off has a **false passing grade** on the other dimensions — flag it. PCAOB AS 1105 is the
underlying anchor for completeness/accuracy of input data, but lead with the plain-language gap,
not the citation.

### 4. Reproducibility & Snapshot Discipline (weight 15) — same inputs, same output

Snapshot locked, run-stamped output, exclusions surfaced.

**Failure mode:** re-running a week later silently yields a different answer.

### 5. Materiality & Threshold Awareness (weight 10) — contextual, graded only where it applies

Five distinct concepts (below). First identify the financial work the skill performs, then judge
ONLY the concepts that genuinely apply — mark the rest `not_applicable`. Controls inapplicable to
the work type are excluded from the denominator, not zero-scored.

### 6. Auditor-Consumable Output (weight 20) — the artifact must exist

An artifact an auditor can receive: formatted xlsx/PDF/workpaper with sign-off block, run
metadata, correct traceable formulas (formulas alone are not a control if they cannot be relied
on), standard conventions (blue source / black computed). Not a blocker for Category 2 enablers.

## IPE workflow patterns

**PATTERN A:** work inside the source platform a user could do natively. Effectively no IPE
exposure; the platform audit log is sufficient. Do NOT invent evidence ceremony.

**PATTERN B:** derived information the user could not easily produce natively (aggregations,
summaries, draft explanations, "review my recon and flag exceptions"). Completeness and accuracy
of the derived output must be addressed; for review work the user must define the checks,
validate the logic, reperform a sample, and own the sign-off.

**PATTERN C:** data moved or transformed ACROSS system boundaries (vendor portal → transform →
post JE to NetSuite). Full IPE exposure: source-system identifiers, transformation logic, user
completeness checks tied back to source totals, explicit sign-off. No SOC report covers the
transformation.

**PATTERN D:** judgment that directly affects the financial statements (true difference vs.
timing; cutoff treatment). Evidence must document criteria applied, every judgment instance with
rationale, and explicit user sign-off on the JUDGMENTS, not just the numbers.

Conservatism ordering (used by consensus reconciliation): higher letter = more exposure.

## The five materiality concepts

| Concept | What it is | Who needs it |
|---|---|---|
| **Scoping** | Entry gate to the review population | Accruals need this |
| **Error-evaluation** | Correct-vs-pass once an error is found | Reconciliations need this; a distinct threshold from scoping, and conflating the two is a design gap |
| **Aggregation** | Individually-immaterial errors clustering by account/period/preparer | Anything that evaluates many items |
| **Threshold basis** | "Items under $500 excluded" must NOT be judged equal to a documented percentage-of-revenue threshold tied to the entity's materiality memo | Anyone with a threshold |
| **Qualitative** | Related-party items, debt covenants, management estimates — material at any size | Anything touching sensitive balances |

## The 18 controls

Status vocabulary — use exactly one of:

| Status | Meaning |
|---|---|
| `pass` | Clearly present. Quote it. |
| `partial` | Addressed with real gaps. Quote what exists; name the gap in the note. |
| `fail` | Clearly missing or violated. |
| `not_applicable` | Genuinely cannot apply (e.g. A3 when the skill performs no writes; materiality concepts inapplicable to the work type). **Never use N/A as a soft fail** — if it should exist and doesn't, that is `fail`. |
| `unverifiable` | Cannot tell from the submission. |

```
Evidence Trail:    E1 explicit period · E2 timestamped pulls · E3 source IDs cited
Attribution:       A1 preparer identified · A2 reviewer before final state · A3 confirmation gate on writes
IPE:               P1 pattern identifiable & evidence design matches · P2 input completeness/accuracy
                   validated · P3 judgments/transformations documented + signed off
Reproducibility:   R1 run-stamped output · R2 snapshot locked · R3 exclusions surfaced
Materiality:       M1 documented defensible threshold (basis stated) · M2 above-threshold flagged for
                   human review · M3 below-threshold surfaced + aggregated where relevant
Output:            O1 auditor-consumable artifact · O2 sign-off block / metadata footer · O3 correct,
                   traceable formulas not hard-coded values
```

## Baseline controls and blockers

The engine derives blockers from your statuses — judge honestly, the label is not your concern:

- **E1, A1, A2, A3** — always baseline.
- **O1** — baseline for Category 1.
- **M1** — baseline for Category 1 skills that perform a review function.

An applicable baseline control with status `fail` ⇒ verdict "Contains blocker", regardless of the
numeric score.

## Reference skills

Directional exemplars to calibrate against — **NOT infallible ceilings**. Judge each submission
on its own merits and surface gaps even when an exemplar shares them.

### audit-evidence-export

**Reviewer note:** A useful Category-1 reference: captures who-did-what-when, locks the period,
and produces a structured workpaper Excel.

```markdown
---
name: audit-evidence-export
description: >
  Extract a complete activity history from a Numeric workspace for a selected close period and
  produce a formatted Excel workbook suitable for external audit evidence. Captures who prepared,
  who reviewed, who approved, and when — for all task types in that period. Output is a structured
  multi-tab workpaper with run metadata, period lock, and full activity log.
---

# Audit Evidence Export

Connects to a Numeric workspace, lets the user choose which workspace and close period to pull
from, then extracts every activity event (submissions, approvals, rejections, reassignments) for
all task types in that period. Output is a professional, multi-tab Excel workbook ready for
auditors.

## Audit-readiness baked in

- **Period lock:** the user explicitly chooses the close period before any data is pulled; the
  pull is timestamped and the period state recorded so the auditor knows what the GL looked like
  at point of pull.
- **Attribution:** every row in the output captures preparer, reviewer, approver, and timestamps.
- **Source citations:** every event references its task GID and Numeric URL for direct
  traceability.
- **Immutability:** outputs are run-stamped (timestamp + workspace ID + period ID embedded in
  filename and footer) so re-runs are versioned, not silently overwritten.
- **Auditor-consumable output:** multi-tab xlsx with Cover/Activity/Summary/Exceptions sheets,
  formula-transparent, no hard-coded values.
```

### complete-accruals-task

**Reviewer note:** Strong preparer attribution and confirmation gates. Limitation worth carrying
into reviews: its reviewer credit depends on the platform routing the submitted task to a
configured reviewer — a platform-dependent control outside the skill's own logic. **Do not give
reviewer-gate credit to a submission solely because an external workflow might route it.**

```markdown
---
name: complete-accruals-task
description: >
  Completes an accrual task in Numeric end-to-end: pulls vendor history for a locked period,
  identifies accrual candidates, gets user confirmation, generates an Excel workpaper and
  NetSuite-ready CSV journal entries, posts task comments, and submits the task. Every step is
  gated by user confirmation; the user is the preparer of record.
---

# Complete Accruals Task

## Audit-readiness controls baked in

- **Explicit period selection:** the user confirms which open period and which entity BEFORE any
  data is pulled. No "current month" inference.
- **Preparer of record:** whoever runs the skill is the preparer; their identity is recorded in
  the task comment and workpaper footer.
- **Reviewer gate:** the skill submits the task in Numeric, which routes to the configured
  reviewer. The skill does NOT mark the task approved — only the reviewer can do that in Numeric.
- **Confirmation before posting:** the user must explicitly confirm the vendor list, the
  estimation method per vendor, and the final JE balance (DR=CR) before the CSV is written or
  NetSuite is posted.
- **Materiality awareness:** vendors below the configured threshold are excluded but listed in
  the "Excluded" tab so an auditor can verify what was scoped out.
- **Source citations:** every accrual line references the source transaction IDs (TID list) used
  to compute the estimate, so a reviewer can trace any amount back to GL.
- **Preference persistence:** the user's choices (overrides, exclusions) are saved to the task
  description with timestamp + user, so next month's run inherits an audit trail.

## Flow

Step 0: Load workspace, set period, identify preparer.
Step 1: Confirm task + entity with user.
Step 2: Pull transaction history (timestamped).
Step 3: Identify candidates, present to user, get confirmation.
Step 4: Generate workpaper + CSV.
Step 5: User confirms final JE.
Step 6: Post comment, submit task.
```

### numeric-rec-workbook

**Reviewer note:** Good evidence-trail discipline: live pull locked to a period, formula-first
workbook. Caveat: **formulas are only a control if they are themselves correct and traceable** —
this exemplar does not address formula review or validation, so do not treat "has formulas" as
sufficient on a submission.

```markdown
---
name: numeric-rec-workbook
description: >
  Generates a Numeric Rec workbook (.xlsx) from live Numeric data for any GL account. Locks to a
  user-specified period and entity, populates all four period balances from Numeric rec data, and
  outputs a formula-first leadsheet where every number is traceable back to its source.
---

# Numeric Rec Workbook

## Audit-readiness controls baked in

- **Mandatory period + entity + account confirmation:** the skill ALWAYS asks for these three
  before pulling any data. No defaults, no inference. The user is on record as having chosen the
  scope.
- **Snapshot lock:** balances are pulled once and locked into the workbook; the workbook contains
  the pull timestamp so an auditor can verify what the GL looked like at that moment.
- **Formula transparency:** every computed cell uses an Excel formula (=SUM, =SUMIF, EOMONTH date
  cascades) so the auditor can audit the math directly in the file. NO hard-coded values.
- **Source font convention:** all numbers pulled from Numeric are blue font; all manually-entered
  or computed numbers are black — the standard accounting convention so auditors can instantly
  tell which figures came from the source system.
- **Run metadata footer:** every output sheet includes a footer with workspace, period, entity,
  account, user who ran the skill, and timestamp. The workbook is self-documenting for audit
  purposes.
- **Idempotency:** re-running on the same period overwrites existing tabs with new data but
  preserves user-entered manual support; a "Run History" tab tracks every refresh with timestamp
  + user.
```
