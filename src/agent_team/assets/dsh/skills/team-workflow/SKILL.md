---
name: team-workflow
description: Select and operate the smallest adequate agent-team workflow tier.
---
# Team workflow

## DeepSeek Harness (DSH)

In a DSH session, use the smallest useful scope, clear ownership, bounded work,
and evidence-based handoff as planning guidance. DSH and its presets own
subagent spawning and recovery. `dsh.agentTeams` owns task coordination, and
`dsh-delivery` owns the single-task delivery lifecycle.

Only when the current host is known to be outside DSH and the current workflow
is managed by Agent Teams CLI, read
[the Agent Teams CLI workflow](references/agent-team-workflow.md).
