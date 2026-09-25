Act as the main-thread coordinator and use $team-coordinate. Read
.agent-team/runs/<slug>/run.toml and plan.md, plus tasks.md for team tier. For
assisted tier, record bounded task entries in run.toml and serialize writers.
Split the next wave into file-disjoint scopes and spawn implementer or ops custom
agents only where their files do not overlap. Give each worker a unique instance
name, task ID, exact files, acceptance criteria, verification commands, and
report path. Wait for all workers, then consolidate their evidence and update
the run state.
