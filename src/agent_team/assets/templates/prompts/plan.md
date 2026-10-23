If the user explicitly asks for the agent-team coordinator in the main thread,
ask whether to load the coordinator harness into this thread or spawn a dedicated
native coordinator subagent. Explain both options and wait for the choice before
spawning. Then act as the selected coordinator and use $team-plan for <feature>. Run
agent-team run init --slug <slug> --tier <tier>, complete requirements.md and
plan.md, add design.md and decisions.md when deep discovery is enabled, add
tasks.md for team tier, and propose the first implementation wave before
editing product code.

### Lean Planning Rules (精简规划原则)

- Keep plans focused on user value and working software. Do not subdivide straightforward tasks into dozens of micro-runs.
- Disallow planning runs whose sole purpose is to plan or preview another test harness.
- Set clear acceptance criteria based on runnable end-to-end behavior, not formalistic document gates.
