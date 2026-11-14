# Run levers: batching, caching, model, effort and controls

Read this file only in step 7 or 9, when a lever has status `needs_judgment`, or when the person asks about batching, caching or limits. Prices change, so the figures here are ratios; check the [pricing page](https://platform.claude.com/docs/en/about-claude/pricing) before quoting a price.

## Batching (`lever:batching`)

- The Batch API charges 50% less for input and output tokens, and the discount combines with caching. Results arrive asynchronously; a batch can take up to 24 hours, so it only suits work nobody is waiting on.
- A batch holds independent single requests, so a multi-turn agent run cannot be batched as a whole. One step can be batched when it repeats the same task over many items that do not depend on each other and nobody waits on the answer, for example drafting one flux explanation per account overnight.
- costkit flags a tool (other than general tools such as Read or Bash) called five or more times with the same parameters and different values. Decide "applies" only if the calls are one task per item, no later item depends on an earlier one, and the result can wait. When it applies, the change is a script that sends that step through the Batch API, which needs API access; mark it "needs API access" if the skill runs only in the chat app.

## Caching (`lever:caching`)

- A cache read costs 10% of the input price on most models, 5% on Opus 5.5 and Sonnet 5.5, and 2.5% on Fable 5.1 and 5.2; costkit prices each request from `prices.json`. Writing costs 1.25 times the input price for the 5-minute cache and 2 times for the 1-hour cache, so the 5-minute cache pays for itself after one read and the 1-hour cache after two. (source: [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching))
- Cowork and Claude Code cache the conversation automatically, so the lever is not breaking the cache: keep large reference content stable and loaded early, keep the model and effort setting fixed during a run, and avoid idle gaps longer than the cache window. Changing the tools, thinking or effort invalidates the cache, and a different model starts its own cache.
- costkit measures the hit rate from the transcript, including sub-agents. It is usually already high in Cowork; the status is informational unless R6 found gaps.

## Model per step (`lever:model_per_step`)

- Anthropic's guidance pairs a lower-cost model for simple steps with a stronger model for reasoning, "so that most tokens are billed at the lower rate." (source: [Choosing a model](https://platform.claude.com/docs/en/about-claude/models/choosing-a-model))
- Decide "applies" only for a step that is extraction, formatting or classification with a fixed format. In Cowork and Claude Code, that step can run as a sub-agent with a cheaper `model`. Test it in its own round with `--tested-change model`; rounds are scored in list-price dollars, so a model change is comparable as long as both models are in `prices.json`. The output check must still pass.

## Effort (`lever:effort`)

- Thinking is billed as output tokens. Anthropic notes that "tuning effort is often a better lever than switching models." costkit flags a run where thinking is over half of the output tokens.
- Decide "applies" when the steps are mostly mechanical. In Claude Code, set `effort` in the skill's frontmatter; in Cowork there is no per-skill setting, so mark it "does not apply".

## Controls by environment

- **Agent SDK and command line:** `--max-turns` (or `max_turns`) stops after that many tool-use round trips, and `--max-budget-usd` (or `max_budget_usd`) stops at an estimated spend. Both are enforced, and the budget can overshoot by the cost of one response. (source: [Agent loop](https://code.claude.com/docs/en/agent-sdk/agent-loop#turns-and-budget))
- **API:** `max_tokens` is a hard cap per request. Task budgets are only a hint to the model and are not supported in Cowork or Claude Code. (source: [Task budgets](https://platform.claude.com/docs/en/build-with-claude/task-budgets))
- **Cowork:** no enforced per-run limit was found. The ceiling that costkit writes is an instruction to stop and report, and the `under_ceiling` gate flags any recorded run that went over it.
- costkit sets the tool-call ceiling and `--max-turns` at 1.5 times the main agent's tool calls and requests in the baseline (sub-agents' calls are left out, because the main agent cannot count them). Real runs are not gated by the ceiling. A turn is one request, which can hold several tool calls, so the two numbers differ.
