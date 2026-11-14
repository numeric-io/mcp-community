---
name: skill-cost-optimizer
description: Measures what another skill costs to run and where the cost goes, step by step, either from a run that already happened in this chat (assess) or by running the skill, testing changes and keeping only those that lower the cost (optimize). Use when the person asks to assess, measure, reduce or optimize the cost of a skill or recurring automation, or for a quarterly cost check on one.
---

# Skill cost optimizer

This skill measures and lowers what a target skill costs per outcome without changing what it produces. A script does every measurement, check, score and keep-or-revert decision. The model makes only three kinds of judgment, and logs each one with `costkit judge` so the report shows it: whether a flagged item is a real finding or a lever applies, whether two outputs that differ in wording are equivalent, and how to word the recommendations.

The tool is `scripts/costkit.py`. Run it; do not read it. Below, `costkit` means `python3 <this skill's folder>/scripts/costkit.py`, WORK is the work folder, and SKILL is the target skill folder.

## Two modes

- **Assess** makes no runs and no changes. It checks the skill's files and measures a run of the skill that already happened earlier in this chat: list-price cost by model and by step, errors, compactions and wasted calls. It saves that run as a real run and ranks the findings by estimated saving. Use it right after the skill has run for a customer.
- **Optimize** runs the skill as a read-only test, applies approved changes to a copy, runs the copy and keeps a change only if the score improves. When an assessment was done first, its findings and cost by step say what to change; the scores still come from test runs only.
- Real runs are scored against the first real run and test runs against the test baseline. A real run includes the interview, corrections and delivery steps that a test run leaves out, so the two series are never compared with each other.

## Rules

- Measure from session records with `costkit assess` or `costkit measure`, never from the usage line the Agent tool returns, which is only the size of the last request.
- A real run can be assessed only in the chat where it ran, because each chat keeps its own session file.
- Every test run in one comparison uses the same model and effort; costkit reads both from the transcript and does not score a run that differs unless that difference is the change being tested.
- Never edit the target skill itself. All changes go into `WORK/candidate/`, and the person decides whether it replaces the original.
- Do not do arithmetic in your own reasoning. Every figure comes from costkit or from a command.
- Costs are list prices from `prices.json` in this skill. When costkit names a model with no price, add the model from the [pricing page](https://platform.claude.com/docs/en/about-claude/pricing) before reporting dollars.

## Setup (both modes)

1. **Confirm the inputs.** From the conversation, work out the target skill and the mode. Ask the person once, in one AskUserQuestion call, only for what is still missing: the mode, the outcome unit (for example "account drafted"), and, for optimize, one fixed, realistic request the skill handles every month. If the person has a run-diagnosis account file for the skill (`accounts/<skill>.json`), use it: its `steps` map gives the cost by step. Without one, costs are grouped by tool name.
2. **Set up the work folder.** WORK is `<skill>-cost` beside the skill. If it already has a `config.json` with the right mode and account file, reuse it. Otherwise run `costkit init WORK --skill SKILL --request "..." --outcome-unit "..." --mode assess|optimize [--account ACCOUNT.json]`, adding `--force` when WORK already exists; that archives the old session's working files and keeps the metrics history and the candidate copy. costkit detects the environment.
3. **Run the static checks.** Run `costkit static WORK/candidate/<skill> --save WORK`. It prints the findings ranked by estimated saving and marks with J the ones that need judgment.

## Assess

4. **Find the run.** Run `costkit turns --skill <skill folder name>`. It lists the person's messages in this chat and suggests `--start` and `--end` from the first and last tool calls that touched the skill. Use the suggestion unless the list shows a better boundary; if it gives no end, use the message that asked for this assessment. If the chat holds several runs of the skill, assess the latest and say that earlier runs were left out.
5. **Measure and record it.** Count the outcomes in what the run delivered (the files it sent or wrote to the outputs folder) with a command, then run `costkit assess WORK --skill SKILL --outcomes N --start S [--end E]`. Add `--reviewer-edits N` only when the person gave a count. It prints the cost by step and saves the run as `real-<date>`.
6. **Judge and report.** Make the judgment calls in step 7, run `costkit ceiling WORK` (in assess mode the ceiling goes into the candidate copy as a recommendation), then go to step 14.

## Optimize

7. **Make the judgment calls.** Judge the items marked J by `static`, and, once a run has been measured, the run findings marked `needs_judgment` and the levers with status `needs_judgment` in `WORK/findings_run.json`. For each, read its entry in [reference/checklist.md](reference/checklist.md), or [reference/run-levers.md](reference/run-levers.md) for a lever, and log `costkit judge WORK --id ID --decision "confirmed|not a finding|applies|does not apply" --note "one sentence"`. Lever ids are `lever:batching`, `lever:caching`, `lever:effort` and `lever:model_per_step`.
8. **Run and record the test baseline.** Before each test run, read [reference/running-tests.md](reference/running-tests.md). Run the original skill with round `baseline`, then run `costkit measure --agent-id ID --save WORK --round baseline`, `costkit record WORK --round baseline --skill SKILL --outcomes N` and `costkit ceiling WORK`. If no assessment was done, judge the run findings now (step 7).
9. **Get approval.** Show the person the open findings, ranked by estimated saving, one line each in the same format, and ask once which to apply. Record the answer with `costkit mark WORK --id ... --status approved`, `--status "declined by the person"`, or `--status "needs API access"` for a change the chat app cannot make.
10. **Apply one group of approved changes.** Round 2 applies the changes to the skill's files: context changes (size, links, duplication, data) and moving calculations or filtering into scripts. Round 3 applies run-mode changes (model or effort for a step). Make the changes in `WORK/candidate/<skill>/`, then run `costkit mark WORK --id ... --status applied --round ROUND`.
11. **Run and score the round.** Run the candidate (see running-tests.md), then `costkit measure --agent-id ID --save WORK --round ROUND` and `costkit compare-outputs WORK/runs/baseline/out WORK/runs/ROUND/out --save WORK --round ROUND`. If the verdict is `needs_judgment`, read both versions of each file it lists and log `costkit judge WORK --id output:ROUND --decision equivalent` (or `"not equivalent"`) with a note. Then run `costkit record WORK --round ROUND --skill WORK/candidate/<skill> --outcomes N`, adding `--tested-change model` or `--tested-change effort` in a round that changes the model or effort on purpose.
12. **Decide and loop.** Run `costkit decide WORK`. It keeps or reverts the round, restores the candidate on a revert (keeping the ceiling), and says whether to stop: after three test runs, after a kept round that saved under 10%, or when nothing is left open. If it does not stop, run step 3 on the candidate again and go to step 10. If a reverted round held several changes, the next round retries the one with the largest estimated saving alone.

## Later checks and the report

13. **Quarterly check.** Preferably, assess the next real run in the chat where it happens (steps 4 and 5). If there is no real run, run the current skill as a test (see running-tests.md) and run `costkit check WORK --skill SKILL --outcomes N --agent-id ID`, which scores it against the test baseline.
14. **Report.** Run `costkit report WORK`, which writes `WORK/report.html`. Send it with SendUserFile, and tell the person in two or three sentences the cost per outcome, the most expensive step, the largest finding or the best kept score, and that any optimized copy is in `WORK/candidate/` for them to approve.

## What the score means

Each request is priced at list price from its own usage: model, cache writes and reads, fast mode, US-only inference, Haiku's long-prompt tier and web searches. The score is cost per outcome as an index against the reference run's 100, with both runs priced at today's `prices.json`, so a price change moves neither side and runs on different models can be compared; lower is better. In the cost by step, each request's cost counts under the step of the tool call it made, and the first matching pattern in the account file's step map decides the step. A test run that fails a gate (output check, reviewer edits above the baseline's, over the ceiling, or stopped by a limit) is recorded as failed rather than scored.
