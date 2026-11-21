---
name: team-plan
description: Convert approved requirements into a decision-complete implementation plan.
---


# Team planning

Map each functional and non-functional requirement ID to implementation changes,
acceptance evidence, and exact verification. Specify interfaces, ownership of
files and shared resources, dependencies, failure behavior, migration or
rollback,
documentation, and assumptions requiring evidence. Resolve routine engineering
choices within existing authorization; ask the user only about material product,
scope, or risk decisions not already settled.

In DeepSeek Harness (DSH), the plan describes work and dependencies. DSH and
its presets decide whether to assign work or spawn agents. `dsh.agentTeams`
tracks the tasks, and `dsh-delivery` owns approval for delivery plans.

Only when the current host is known to be outside DSH and the current workflow
is managed by Agent Teams CLI, read
[the Agent Teams CLI workflow](references/agent-team-workflow.md).
