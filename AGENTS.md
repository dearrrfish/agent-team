# Project Agent Instructions

Before changing this repository, read `.local/dev/plan.md` and
`.local/dev/progress.md`. The plan is the approved design contract; progress is
the current implementation state and handoff record.

- Work on the next unblocked milestone recorded in `progress.md`.
- Do not silently change scope, public interfaces, schemas, or lifecycle rules.
- Update `progress.md` after each bounded implementation slice and before any
  handoff. Record changed surfaces, exact verification commands and results,
  blockers, deviations, and the next action.
- Run the applicable tests or checks before claiming a milestone is complete.
- Keep detailed design and historical execution state out of this file.

The recommended Codex lead is `gpt-5.6-sol` with `high` reasoning effort.
Bounded implementation workers may use `gpt-5.6-terra` with `high` effort;
independent review should use `gpt-5.6-sol` with `high` effort.
