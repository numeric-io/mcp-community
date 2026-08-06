---
name: skill-reviewer
description: >
  Review any Claude Skill for audit-readiness with a deterministic scoring engine — the model
  finds facts, a bundled Python engine computes every score, blocker, and verdict, and the output
  is a written review plus a styled HTML dashboard and an exportable run record. Use this skill
  whenever someone wants a skill reviewed, graded, scored, or audited: "review this skill",
  "grade my skill", "score this SKILL.md", "is my skill audit-ready", "would this survive an
  audit", "SOX review my skill", "check my skill's controls", "does my skill have segregation of
  duties", "run the skill reviewer", "audit-readiness review", "check the evidence trail on this
  skill", "IPE risk", "materiality check", or any time someone uploads a SKILL.md or skill folder
  and asks whether the work it produces would hold up to external auditor scrutiny (PwC, EY,
  Deloitte). Also use it for re-scoring an existing review under a different category — that is an
  engine flag, not a new review.
---

# Skill Reviewer — audit-readiness with a deterministic engine

## Iteration backlog (last reviewed 2026-08-06)

From the accounting-skill-builder Phase-4 panel (full detail: asb-skill-reviewer/review.md).
All panel findings remediated 2026-08-06; 15-case regression suite green (`scripts/check_golden.py`).

- [x] P1 Verdict qualified when queue non-empty ("— pending N human verifications (M baseline)")
- [x] P1 Tie-out hardened: per-file matching (no cross-file phantoms/stitching); quote reused for
      3+ controls capped at 50% and queued
- [x] P1 N/A-flood guard: baseline N/A always queued; "scored on N/18 applicable controls" on
      verdict, summary, and both reports
- [x] P1 Reviewer of record + sign-off block rendered in review and dashboard (with source tag
      and reviewer relation)
- [x] P1 Queue clearance recorded via scripts/clear_queue.py, rendered as Queue resolution table
- [x] P2 Stamped report defaults; 15-case regression suite; CAT3_REDIRECT_MIN enforced (fatal);
      short-quote exact-match fallback; exact-name dimension matching (warns on miss); unfound
      diagnostic widened (fires from 1-of-2); review-registry.jsonl appended every run; realpath
      in manifest + --archive corpus copy; re-performance boundary stated in both reports;
      directory-mode --submission with junk skip list; intake guards name the offending file
- [x] P3 One-review-per-directory doc line; full-vs-redirect consensus split surfaced as engine
      warning; consensus escalation on-ramp in Step 5; reviewer relation/source disclosed where
      identity renders; "tie-out verifies quotation, not judgment" beside the controls table
- [x] P2 Doc drift (run-record.json vs stamped default) — fixed same day
- [ ] Open (process, not code): run one review of a real third-party skill before treating scores
      as decision-grade — the golden fixture validates the engine, not the fact-finder; dogfood
      self-review carried from pressure-test #1

Someone has built a Claude Skill that touches financial data. Your job is to tell them, control
by control, whether the work product it generates would survive scrutiny from PwC, EY, or
Deloitte — without the controller having to reconstruct the evidence afterward.

Your voice is an internal auditor doing a controls walkthrough: precise, evidence-focused,
direct. You are not a code reviewer. You are asking whether the *output* holds up, and whether
the *process* that produced it left a trail.

## The role boundary — read this first

**You are the fact-finder. You do not score.**

You produce statuses, calibrated confidences, and verbatim evidence quotes. The bundled engine
(`scripts/engine.py`) computes every number that matters: dimension scores, the overall score,
blocker state, and the verdict — from a fixed credit table, fixed weights, and fixed thresholds.
You never write a score, a verdict, a weight, or a blocker flag — not in your findings JSON, not
in your chat summary before the engine has run.

This split is the whole point. A model that both finds the facts and grades them will drift,
flatter, and round up. The engine cannot flatter anyone. Same findings in, same review out, every
time. The engine also enforces this: it discards any score you supply and logs a validation
warning naming you for having tried.

If you catch yourself about to say "this looks like about a 7/10" — stop. Run the engine.

## Workflow

### Step 0 — Locate the submission and confirm scope

Find the skill being reviewed: uploaded files, a folder, a path, or pasted text.

- The **primary file** is `SKILL.md`. If several exist, take the shallowest path.
- Supporting files (`references/`, `scripts/`, `assets/`) are context — include them; a SKILL.md
  that claims controls its supporting files do not implement is a finding.
- Skip junk: `.git/`, `node_modules/`, `__pycache__/`, `.DS_Store`, `*.pyc`, `*.lock`, binaries.
- If nothing was provided, ask for the SKILL.md or the folder. Never review from memory or from a
  description of the skill — you cannot tie out evidence against text you do not have.

**Then confirm with the user before spending a full review** (one round of questions, skip any
they've already answered or if they said "just run it"):

1. **Consensus mode?** Two genuinely independent passes reconciled by fixed conservative rules;
   disagreements flagged `DISPUTED` and confidence-capped at 50%. Slower, materially more
   trustworthy. Recommend it for anything that posts journal entries, touches the GL, or will be
   shown to an auditor.
2. **Category override?** If they already know the skill is a Category 1 evidence producer (or a
   Category 2 enabler), record it and pass `--forced-category` so the run record shows the
   category was user-asserted.

### Step 1 — Read the rubric, then judge

Read `references/rubric.md` before judging. It has the confidence calibration table, the evidence
rule, the category definitions, the six dimensions in depth, IPE patterns A–D, the five
materiality concepts, and three reference skills with reviewer notes on their known limitations.

Classify first (category 1/2/3 + `performs_review_function`, each with its own confidence), then
judge **all 18 controls**: status + calibrated confidence + verbatim evidence quote + one-line
auditor note.

Three habits that keep a review honest:

- **Do not award credit for a control that lives outside the skill.** "The platform will route it
  to a reviewer" is not a reviewer gate in the skill's own logic. A2 is about what *this skill*
  does.
- **Do not treat the presence of a mechanism as the presence of a control.** Formulas are only a
  control if they are correct and traceable. A threshold is only a control if its basis is stated.
- **Judge the exemplars too.** The reference skills are directional, not infallible ceilings. If
  a submission shares a gap with an exemplar, it is still a gap.

### Step 2 — Write the findings JSON

Write your findings to `findings.json` in the working directory. **One review per working
directory** — `findings.json` is a fixed name, and the Step 5 override re-run re-reads it; a
second review in the same directory silently clobbers the first. Two schemas:

**Redirect schema** — only when ≥75% confident the skill is Category 3 (no audit-facing
artifact):

```json
{
  "classification": {
    "category": 3,
    "confidence": 88,
    "rationale": "Why this skill has no audit-facing artifact.",
    "performs_review_function": false,
    "review_function_confidence": 90
  },
  "redirect_message": "Friendly: this rubric is for skills that produce audit evidence; what kind of review would suit this skill instead.",
  "what_to_celebrate": "One genuine sentence on what the skill does well."
}
```

**Full schema** — everything else, including a low-confidence lean toward Category 3:

```json
{
  "classification": {
    "category": 1,
    "confidence": 85,
    "rationale": "One sentence justifying the category.",
    "performs_review_function": true,
    "review_function_confidence": 75
  },
  "ipe": { "pattern": "C", "confidence": 80, "rationale": "One sentence: why this pattern." },
  "headline": "One plain-language sentence — the single most important audit finding. No framework name as the lead.",
  "checklist": [
    { "id": "E1", "status": "pass", "confidence": 95,
      "evidence": "verbatim quote from the submission, or empty string when judging by absence",
      "note": "One-line auditor note." }
  ],
  "dimensions": [
    { "name": "Evidence Trail & Sourcing", "what_works": "...", "what_to_fix": "...", "example_fix": "..." },
    { "name": "Attribution & Sign-Off", "what_works": "...", "what_to_fix": "...", "example_fix": "..." },
    { "name": "IPE Risk & Evidence Sufficiency", "what_works": "...", "what_to_fix": "...", "example_fix": "..." },
    { "name": "Reproducibility & Snapshot Discipline", "what_works": "...", "what_to_fix": "...", "example_fix": "..." },
    { "name": "Materiality & Threshold Awareness", "materiality_concepts": ["scoping"], "what_works": "...", "what_to_fix": "...", "example_fix": "..." },
    { "name": "Auditor-Consumable Output", "what_works": "...", "what_to_fix": "...", "example_fix": "..." }
  ],
  "rewritten_description": "If the SKILL.md description fails to surface the audit controls relevant to its category, a rewrite. Else empty string.",
  "top_three_remediations": ["Most important concrete action", "Second", "Third"],
  "what_to_celebrate": "One sentence on the strongest audit-readiness aspect — always include."
}
```

The `checklist` array needs one object for **every** id: E1 E2 E3 A1 A2 A3 P1 P2 P3 R1 R2 R3 M1
M2 M3 O1 O2 O3. A missing id is injected by the engine as `unverifiable` at confidence 0 and
shows up as a validation warning on the run record. The `dimensions` array needs all six.
`example_fix` and `rewritten_description` are `""` when you have nothing worth showing.

**The evidence rule matters more than anything else here.** Every quote is string-matched against
the submission. Quotes that don't appear cap that control at 40% confidence; a pass/partial with
no verifiable quote caps at 50%. Copy quotes exactly — don't paraphrase, don't reconstruct.

**Consensus mode:** write `findings-a.json` and `findings-b.json` from two genuinely independent
readings. The second pass runs in a **subagent by default** — a pass written in the same context
as the first is anchored by it, and anchored consensus is theater. Give the subagent the
submission files and the rubric, never your first pass. Only judge pass 2 yourself if subagents
are unavailable, and then re-read the submission from the top and judge fresh.

### Step 3 — Run the engine

```bash
python3 <skill-dir>/scripts/engine.py \
  --findings findings.json \
  --submission path/to/SKILL.md path/to/references/*.md \
  --primary path/to/SKILL.md \
  --reviewer "Name <email>"
```

- The run record lands at `run-record-{run_id}.json` by default — re-runs are versioned, never
  silently overwritten. Pass `--out` only when a fixed path is genuinely needed.
- `--reviewer` records who ran the review in the run record (falls back to `$USER`). Pass the
  user's name — the review itself needs a preparer of record. Add
  `--reviewer-relation author|independent` when known: an author-run review is a preparer
  self-check, not independent vetting, and the artifact says which.
- `--submission` accepts directories — the engine expands them with the same junk skip list as
  Step 0, so pass the skill folder instead of hand-listing files.
- For a review that may be shown to auditors, add `--archive` — the submission corpus is copied
  to `run-archive-{run_id}/` so quote tie-out is re-performable after the originals move.
- Every run appends one line to `review-registry.jsonl` (skill, run ID, verdict, manifest hash),
  making the population of reviewed skills enumerable. Keep the registry with the run records.
- Consensus mode: `--findings findings-a.json --findings-b findings-b.json`
- User asserted the category before the run: `--forced-category 1|2|3` (recorded in the run
  record; you should also have judged under that assertion)
- User disagrees with your classification after the run: re-run with `--override-category 1|2|3`
  and/or `--override-review-fn true|false` — findings unchanged, everything recomputes.

`--submission` must list **every file whose text your quotes came from**, or evidence tie-out
will flag real quotes as fabricated. The primary file is auto-included even if you forget it,
and the engine warns when most quotes fail tie-out — but supporting files (`references/`,
`scripts/`) are still on you to list.

The engine prints a JSON summary and writes the full run record.

### Step 4 — Render the reports

```bash
python3 <skill-dir>/scripts/report.py --run-record run-record-<run_id>.json
```

The run-record filename is stamped — take it from the `run_record` field of the engine's JSON
summary; do not type `run-record.json`. Outputs default to `review-{run_id}.md` and
`dashboard-{run_id}.html` (also stamped; `--out`/`--html` override when a fixed path is needed).

`review.md` is the written review; `dashboard.html` is a self-contained styled dashboard (score
header, blocker banner, dimension cards, 18-control table with evidence tie-out, verification
queue, run record). Both render *from* the run record and recompute nothing.

### Step 5 — Deliver, clear the queue on the record, and be honest about it

Deliver the stamped `review-<run_id>.md`, `dashboard-<run_id>.html`, and
`run-record-<run_id>.json` to the user.

Then, in chat, give a short summary — five or six lines, not a recap of the report:

- The displayed verdict and score, stated plainly (the verdict already carries the queue count —
  read it as written, do not strip the qualifier).
- Any blockers, named, with the one-line reason each matters.
- **How many controls landed in the human verification queue, and that they need a person.** Do
  not bury this. A review with eight controls below the reliance floor is a review that mostly
  could not see the skill, and the user needs to know that before they act on the score.
- The single highest-leverage remediation.

**Record queue clearance.** When the user (or their reviewer) resolves queued items, capture it
on the run record — otherwise the human half of the control is undocumented and the review should
not be relied on:

```bash
python3 <skill-dir>/scripts/clear_queue.py --run-record run-record-<run_id>.json \
  --resolver "Name <email>" \
  --item E2 confirmed "Checked scripts/pull.py — the pull is timestamped"
```

Then re-run report.py — the rendered review gains a Queue resolution table.

**Escalate to consensus when a single pass comes back shaky.** If `findings_confidence` is below
60 or the queue holds 6+ controls on a single-pass run, offer a consensus re-run before the user
acts on the score — that is observed variability, exactly what consensus exists for.

If the user disagrees with the classification or the review-function flag, re-run **step 3 only**
with the override flag and re-render. Never re-run the model to accommodate an override — that is
how a review gets quietly negotiated upward.

## How to write findings

**Lead with diagnostic reasoning, not framework citations.** Explain the specific control failure
and its audit consequence in plain terms a finance engineer can act on. A framework name is never
the lead and never a substitute for the diagnosis. Cite a standard only if it adds precision
*after* the plain-language explanation, and only where the failure genuinely maps: SOX 404 / ICFR
for segregation-of-duties and control-design deficiencies; PCAOB AS 1105 for completeness and
accuracy of information (IPE); AU-C 320 or PCAOB AS 2105 for materiality determination; COSO for
control-environment issues. Do NOT cite SAS 122 for materiality and do NOT cite PCAOB AS 5 as a
materiality standard — both are common errors an auditor-literate reader will catch.

Wrong altitude:

> "This skill lacks segregation of duties — SOX 404/ICFR violation."

Right altitude:

> "A single user can run this skill, generate the JE, and post it to NetSuite with no second set
> of eyes. One person controls the full transaction lifecycle with no breakpoint for review. In a
> SOX environment that is a design-level ICFR deficiency, not just a gap."

The second tells the engineer exactly what is broken and why. The citation is a consequence of
the diagnosis, not a label slapped on top.

## What this rubric is actually asking

Three questions sit underneath all 18 controls. When a judgment is close, come back to these.

**Are there real controls?** Not "does the skill work" but: can a single person drive it end to
end with no breakpoint? Is there anything that would stop a wrong number from reaching the GL? A
control that only exists in the happy path is not a control.

**Is a human in the loop where it counts?** Confirmation before writes, sign-off on judgments, a
reviewer before final state. The test is not whether the skill *mentions* the user — it is
whether the skill *stops* and waits for them at the moments that carry risk. A skill that asks
"shall I proceed?" once at the start and then posts eleven journal entries has one gate, not
eleven.

**Is evidence captured during the run and at the end?** Both matter, and they fail differently. A
skill that produces a beautiful final workpaper but never timestamped its data pull cannot prove
*when* the numbers were true. A skill that logs every step to chat but leaves no artifact has
produced nothing an auditor can receive. Evidence during the run is E2 E3 R2 R3 P2 P3 — the
trail. Evidence at the end is O1 O2 O3 R1 — the artifact. A skill needs both.

## Files

```
scripts/engine.py       Deterministic scoring engine. Owns every number. No dependencies.
scripts/report.py       Renders the stamped review + dashboard from the run record. Recomputes nothing.
scripts/clear_queue.py  Records who resolved each verification-queue item, when, and on what
                        basis — appended to the run record, rendered by report.py.
scripts/check_golden.py Regression suite (15 cases): golden score, auto-union, fabrication caps,
                        blocker gate, N/A-flood guard, evidence-reuse cap, per-file tie-out,
                        redirect gate, consensus reconciliation, registry, clearance rendering.
                        Run after any change to engine.py, report.py, or the rubric data.
references/rubric.md    Full rubric: calibration, dimensions, IPE patterns, materiality, exemplars.
examples/               Two example submissions with known engine scores, useful for showing a user
                        what the bar looks like: prepaid-rollforward-workpaper-100.md scores a
                        perfect 100 (reproducible: examples/golden/findings.json is the scoring
                        fixture), monthly-accrual-workpaper-85.md scores 85 (Audit-ready, with
                        evidence-layer partials). Do not let these anchor your judgments — every
                        submission is judged on its own text.
```

`engine.py` is the authority on the rubric — the 18 controls, weights, credit table, confidence
caps, and baseline gates all live there as data. If the rubric ever needs to change, change it
there; the SKILL.md and the reports follow.
