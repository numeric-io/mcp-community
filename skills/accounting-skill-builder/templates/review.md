# Review — {workflow_name}

**Run ID:** {run_id}
**Reviewed:** {date}

## Verdict
**Cleared for production** | **Cleared with conditions** | **Blocked**

[One paragraph: what the panel found and what the verdict means in practice for this user this cycle.]

## Headline metrics
- Run time: T sec  (cold-start: X, data pull: Y, parse: Z, build: W, output: V)
- Approx token cost: K
- Human-time saved per cycle: M min  (baseline: B, run: T)
- Human-time saved annually: H hours/year  (M × R runs/year)

## Per-reviewer headlines

| Reviewer | Headline | Lens |
|---|---|---|
| Controller skeptic | yes / with_conditions / no | Would I sign |
| Accounting process expert | well_shaped / with_caveats / reshape | Workflow shape |
| Auditor | fully / with_remediation / not_reliable | Evidence chain |
| Adversarial | K constructed failures, top: [title] | Constructed breaks |
| Production on-call | operable / with_runbook / not_operable | Recovery |

## P1 — must fix before production

1. [title]
   Source reviewer(s): [list]
   What's wrong: [evidence]
   What to do: [fix pattern]

[More P1s...]

## P2 — should fix before production

[Same structure]

## P3 — nice to fix

[Same structure]

## Test scope

[From dry-run-runner.]
- Test data: [closed period / open period / sample / synthetic]
- Result: [completed / partial / failed]
- Files produced: [list]
- Failures captured: [count, summary]

## Iteration backlog

[From the synthesizer. Lives here in this review doc — internal. Never written into the delivered skill's SKILL.md.]

- [ ] [item] — [effort] / [impact]
- [ ] ...

## End of run

Audit trail at `{run_id}/`. The iteration backlog stays in this review doc (`{run_id}/review.md`) — internal, never shipped in the skill.
