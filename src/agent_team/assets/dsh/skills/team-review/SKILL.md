---
name: team-review
description: Run an independent read-only review with stable findings and a verdict.
---
# Team review

Focus on correctness, functionality, regressions, and security risks.

## DeepSeek Harness (DSH)

Identify DSH from the current session's runtime context even when Team tools are
hidden. The skill's installation path, available CLIs, and `agent-team status`
do not identify the host.

Use this skill as review guidance. Check the supplied scope against its baseline
and evidence. Return actionable findings with `file:line` references, impact,
and a verdict. Reuse the review context that DSH or its preset supplies.

DSH and its presets own reviewer selection and subagent spawning. `dsh.agentTeams`
owns Team tasks, and `dsh-delivery` owns plan approval, execution receipts, and
final acceptance. Treat a Team task ID as a reference. Loading this skill does not
trigger subagent spawning, shelling out to a reviewer CLI, task updates, or delivery
operations.
A supplied Agent Teams run slug does not change the scope in DSH.

Only when the current host is known to be outside DSH and the current workflow
is managed by Agent Teams CLI, read
[the Agent Teams CLI workflow](references/agent-team-workflow.md).
