# Qualitative review

Read this file before the review. The review judges whether each step of the run and each part of the skill was needed, in the right place and the right size. It needs no token counts, so it works where cost cannot be measured.

Review the run from what is in this chat: the person's request, every tool call and its result, the replies, the person's corrections and what was delivered. If the chat was compacted or the run is no longer in view, say so and review only what you can see. Review the skill from its files.

## Items

The item list is fixed, so two reviewers of the same run list the same items:

- **Run:** one item per tool call, numbered in order from the first call of the run. Consecutive calls to the same tool for one job (for example three reads of reference files) are one item, named by their range: "calls 3-5, view of three reference files".
- **Skill:** one item per `##` section of SKILL.md (the text before the first `##` is "SKILL.md, top"), and one per other file in the skill. Add one item "SKILL.md, missing: <what>" for each instruction the run needed and the skill did not give.

In Claude Code and Cowork, skip anything a run finding (R1 to R6) already reports; refer to its id in the note of the matching item instead.

## Verdicts

Give each item the first verdict in this list that fits.

1. **failed**: a call that errored, was retried or was undone, or a step the person corrected. A skill item is failed when its instruction, or its absence, caused that. The note names the call or message; the fix is the instruction or input that would have prevented it.
2. **unnecessary**: the outcome would be the same without it. A file or result that nothing later used; a second read of a file already in view; a question the request or the skill already answered.
3. **misplaced**: needed, but done the expensive way. Arithmetic, filtering or reformatting the model did in its reply that a script could do; a table or code block in SKILL.md that a script could read; detail this run did not use that sits in SKILL.md instead of a reference file read only when needed.
4. **excessive**: needed, but larger than the step used. A query or read whose result the step used only part of; a reply that repeated earlier output in full; instructions that say the same thing in several places (the repeat is the item, the first statement is appropriate).
5. **appropriate**: everything else, including anything whose verdict would depend on other runs. Say so in the note: "not used in this run; other runs may need it".

## Evidence

Every verdict other than appropriate states in its note what was observed in this run, not an opinion:

- what was returned against what was used ("returned 400 rows; the reply used 3"),
- which call repeated which ("call 7 read the file call 2 had already read"),
- which message corrected what ("the person corrected the total in their second message"),
- or which reply did the work by hand ("the model added 12 amounts in its reply").

If you cannot point to something like that, the verdict is appropriate.

## Saving the review

Write all items to one JSON file and save them in one call: `costkit review WORK --file ITEMS.json`. Each item is `{"kind": "run" or "skill", "item": "...", "verdict": "...", "note": "one sentence", "fix": "one sentence"}`; fix may be left out only for appropriate. Saving again replaces the whole review.
