---
name: team-coordinate
description: Coordinate bounded native subagents and integrate evidence-backed results.
---

# Team coordination

Keep user decisions in the coordinator. Dispatch only bounded independent work,
track dependencies and write ownership, require structured reports, and verify
results before integration. Stop dispatch when coordination costs exceed the
remaining task value.

Mark a task `ready` or `running` only after all of its dependencies are
`complete`, and keep worker instance names unique within the run.

Before dispatch, read `max_workers` and `reports_required` from the current
`run.toml`. Never allow the number of running workers to exceed `max_workers`;
use additional waves when ready work exceeds the limit. Persist each worker's
report when `reports_required` is true. Team tier always requires reports.
Create each persisted report by copying `reports/agent-report-template.md` to
the task's exact report path, replacing its task and role placeholders, keeping
the run identity unchanged, and completing every required section.
Also read `write_isolation`: assisted tier permits at most one running
write-capable worker, while team-tier parallel writers need disjoint files or
separate worktrees supported by the target.
Confirm that the target's native agents were rendered or installed with
`--run <slug>` so their model routing matches the manifest's `model_preset`.

## Native role selection

- Name the native custom-agent role explicitly when dispatching: `explorer`,
  `design-agent`, `implementer`, `ops`, or `reviewer`. Keep the instance or task
  name separate from the role name.
- Let the selected native agent profile own its model, reasoning effort,
  permissions, and durable role instructions. Do not repeat or override those
  settings unless the user explicitly requests a one-off override.
- For project-scoped Codex agents, confirm the project is trusted and start a
  fresh Codex session after installation. If the requested role is unavailable,
  stop and report the discovery problem; do not silently spawn a generic agent.

## Worker prompt contract

Give every worker:

- its native role and unique instance name;
- the run artifact path and task or wave ID;
- exact owned files plus an explicit no-edit boundary;
- acceptance criteria and exact verification commands;
- the required report path or structured return fields;
- notice of concurrent peers and whether the coordinator will wait for all of
  them before consolidation.

Claude and Antigravity omit shell access from native read-only roles because a
shell can bypass their file-edit tool restrictions. When such a worker needs a
command result, have it return the exact command and expected evidence; run the
command in the coordinator or a separately authorized write-capable worker and
record who produced the evidence.
