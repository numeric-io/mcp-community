# Running a test

Read this file in optimize mode before each test run (the baseline, each round and a quarterly test check). Assess mode never runs the skill and does not need it.

- Make an empty folder `WORK/runs/ROUND/stage/` and copy into it only the skill being run: the original for the baseline and checks, `WORK/candidate/<skill>` for a round. A folder holding two versions gives the agent two SKILL.md files to choose between.
- In Cowork or Claude Code, start a fresh `general-purpose` sub-agent with the Agent tool, passing the same `model` value on every run of the comparison. Use this prompt, filled in: "You are running the skill at STAGE_PATH for the first time. The person's request is: REQUEST. Follow the skill exactly. Connected sources may be read but never changed: do not call any tool that creates, edits, submits or posts anything. Write every deliverable into OUT_PATH instead. Do not use anything outside the skill, the request and those sources." OUT_PATH is `WORK/runs/ROUND/out/`. Note the agent id the tool returns; it is what `costkit measure --agent-id` and `costkit check --agent-id` take.
- Through the Agent SDK or the command line, run `claude -p --output-format json` with the same request, save the result JSON, and pass `--sdk-result FILE` in place of `--agent-id`.
- Count the outcomes in `OUT_PATH` with a command (for example the number of data rows in the output file), not by reading the output.
- If a run is stopped by something outside the skill, such as a lost connection, run it again and do not record the failed run.
