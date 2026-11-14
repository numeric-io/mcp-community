# Cost checklist

Read the entry for a finding only when costkit marks it `needs_judgment`, or when you write the recommendation for it. The report puts every estimate on one scale: list-price dollars per run at the main model's prices, with a static finding's tokens counted as written to the cache once and read on every later request. Each entry says what the script measured, why it costs tokens, and what to decide.

## Contents

- S1 to S13: the skill's files (from `costkit static`)
- R1 to R6: the run (from `costkit assess` or `costkit measure`)

## The skill's files

- **S1, SKILL.md too long.** The body loads on every run and stays in context for the rest of the session, so every line is a recurring cost. Anthropic's guidance is a body under 500 lines, and the skills overview gives under 5,000 tokens for what loads when the skill is triggered. Move detail that only some runs need into a reference file with a when-to-read cue. (sources: [Skill best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices), [Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview))
- **S2, long description.** The name and description load in every session, even when the skill is not used. The listing cuts the description and `when_to_use` off at 1,536 characters. (source: [Claude Code skills](https://code.claude.com/docs/en/skills))
- **S3, unlinked or nested file.** A file that SKILL.md does not link is either dead weight in the package or found by searching, which costs tool calls. A file linked only from another reference file may be read only partly.
- **S4, long reference file with no contents list.** Without a contents list the model reads the whole file to find one section.
- **S5, development material.** Tests, fixtures and old versions ship with the skill and may be read or searched.
- **S6, duplicated text.** The same rule in two places is read twice and can drift apart. Keep one copy.
- **S7, large code block in the instructions.** Code in a markdown file is read as text. A script that the skill runs costs only its output, because "the script's code never loads into the context window." (source: [Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview))
- **S8, large inline table.** A large table in the instructions is read on every run. Move it to a data file that a script filters.
- **S9, script read instead of run (judgment).** The script flags a line that tells the model to read, open or review a script file. Decide: it is a finding if the step only needs the script's result; it is not a finding if the model must adapt the code.
- **S10, link without a when-to-read cue (judgment).** Decide: it is a finding if the file is needed only on some runs; it is not a finding if every run needs it.
- **S11, no cost ceiling.** Apply with `costkit ceiling`.
- **S12, arithmetic left to the model (judgment).** The script flags lines that ask for calculations without naming a script. Decide: it is a finding if the step computes figures (totals, variances, percentages, thresholds) that a script could compute from the inputs; it is not a finding if the line only describes a figure that a script already produces. Moving calculation into scripts saves tokens and makes the figures repeatable: "sorting a list via token generation is far more expensive than simply running a sorting algorithm." (source: [Equipping agents with skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills))
- **S13, no model or effort in the frontmatter (judgment, Claude Code only).** costkit raises this only when the environment is claude-code. Decide: it is a finding if every step is extraction, formatting or classification. These frontmatter keys make the upload fail on claude.ai and the Skills API, so never add them to a skill that is also uploaded there.

## The run

- **R1, the same file read more than once.** The script estimates the tokens of the repeated reads.
- **R2, the same call with the same input made twice.** Reuse the first result.
- **R3, failed tool calls (judgment).** Read the failed calls in the transcript and decide whether an instruction caused them. If it did, the finding is the instruction to fix.
- **R4, a large tool result.** A result stays in context and is resent, at the cache-read rate, on every later request. Filter at the source: a narrower query, a script that returns only the rows needed, or a sub-agent that returns only the answer. A month-end example is sending only the accounts over threshold rather than the full trial balance.
- **R5, sub-agents started (judgment).** Each sub-agent sends its own requests; costkit adds their usage to the run's totals. Decide whether one step could replace them, or whether they could run on a cheaper model.
- **R6, gaps longer than the cache window.** A request after the cache expires pays the full input price for the whole context. costkit uses the run's own cache window (5 minutes or 1 hour, from its cache writes) and ignores gaps that hold a message from the person, which are reply time.

## Writing recommendations

Use the standard recommendation that costkit attaches to each finding, and add the specific file, section or step it applies to. Keep each recommendation to one full sentence.
