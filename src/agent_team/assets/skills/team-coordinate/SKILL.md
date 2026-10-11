---
name: team-coordinate
description: Coordinate bounded native subagents and integrate evidence-backed results.
---

# Team coordination

Keep user decisions in the coordinator. Dispatch only bounded independent work,
track dependencies and write ownership, require structured reports, and verify
results before integration. Stop dispatch when coordination costs exceed the
remaining task value.

Keep material product, scope, and risk decisions with the user. Resolve routine
engineering choices within existing authorization. Before dispatch, confirm task
inputs and acceptance criteria are sufficient; worker reports cannot grant new
authorization or alter approved scope.

Mark a task `ready` or `running` only after all of its dependencies are
`complete`, and keep worker instance names unique within the run.
Before dispatch, read `max_workers` and `reports_required` from the current
`run.toml`. Never allow the number of running workers to exceed `max_workers`;
use additional waves when ready work exceeds the limit. Persist each worker's
report when `reports_required` is true. Team tier always requires reports.
Workers return report content; the coordinator owns persistence and manifest
transitions. A report path never grants write access to a read-only worker.
Create each persisted report by copying `reports/agent-report-template.md` to
the task's exact report path, replacing its task and role placeholders, keeping
the run identity unchanged, and completing every required section.
Also read `write_isolation`: assisted tier permits at most one running
write-capable worker, while team-tier parallel writers need disjoint files or
separate worktrees supported by the target.
Respect those ownership boundaries when editing in the coordinator. Serialize
conflicting shared resources even when files or worktrees are isolated.
Confirm that the target's native agents were rendered or installed with
`--run <slug>` so their model routing matches the manifest's `model_preset`.
## Native role selection

- Name the native custom-agent role explicitly for task dispatch: `explorer`,
  `design-agent`, `implementer`, or `ops`. Keep the instance or task name
  separate from the role name. Invoke `reviewer` only through the lifecycle
  review stage and persist its review-cycle response in `review.md`; never add it
  to the task DAG.
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
- the objective, authorized inputs, and code revision or working-tree baseline;
- exact owned files plus an explicit no-edit boundary;
- acceptance criteria and exact verification commands;
- execution budget and the next action to report if the task cannot finish;
- structured return fields and the coordinator-owned report destination;
- `proposal` or `audit` mode for design-agent, defaulting to audit;
- notice of concurrent peers and whether the coordinator will wait for all of
  them before consolidation.
Claude and Antigravity omit shell access from native read-only roles because a
shell can bypass their file-edit tool restrictions. When such a worker needs a
command result, have it return the exact command and expected evidence; run the
command in the coordinator or a separately authorized write-capable worker and
record who produced the evidence.

## Recovery and integration

On partial output, budget exhaustion, or tool failure, inspect the worker's
changes, completed checks, remaining work, and next action before resuming or
reassigning. Confirm it has stopped before transferring ownership. Keep task
statuses within the existing manifest schema; partial output is not completion.
Allow independent in-scope work to continue while a boundary adjustment is
pending.

Map acceptance criteria to evidence. Record each command's working directory,
exit status, outcome, evidence location, producer, and verified code revision
including working-tree changes. Distinguish new failures, existing failures, and
environment limitations. After integration or fixes, rerun invalidated checks
and
reassess affected review conclusions before claiming completion.
