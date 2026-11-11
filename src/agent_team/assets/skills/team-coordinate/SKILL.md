---
name: team-coordinate
description: Coordinate bounded native subagents and integrate evidence-backed results.
---

# Team coordination

If the user explicitly asks for the agent-team coordinator in the main thread,
ask whether to load the coordinator harness into this thread or spawn a dedicated
native coordinator subagent. Explain both options and wait for the choice before
spawning.

Use the initialized run directory for all artifacts and report destinations.
The default is `<project>/.agent-team/runs/<slug>/` relative to the target project
root, unless the user explicitly specifies another location or the effective
`workflow.run_root` config overrides it. Pass that exact directory to workers;
do not invent `docs/runs` or a separate evidence directory. Keep an existing run
in its established directory unless relocation is explicitly requested.

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

## Cross-tool role dispatch (跨工具角色互通)

When the coordinator runs in one client (such as Claude Code or Pi) but specific
roles benefit from another tool's strengths (for example, invoking `codex` for
`implementer` with sandbox isolation, or calling `claude` for `reviewer`):

1. **Configure default runners in `team.toml`**:
   ```toml
   [roles.implementer]
   runner = "codex"

   [roles.reviewer]
   runner = "claude"
   ```

2. **Dispatch via CLI**:
   ```bash
   # Preview execution plan and prompt:
   agent-team dispatch --slug <slug> --role implementer --task T-001 --worktree --dry-run

   # Execute worker:
   agent-team dispatch --slug <slug> --role implementer --task T-001 --worktree

   # Dispatch independent review:
   agent-team dispatch --slug <slug> --role reviewer --runner claude
   ```

3. **Report contract and worktree integration**:
   - `dispatch` constructs role instructions, task context, and review packets automatically.
   - It checks runner exit status and ensures the output report (`reports/<task_id>.md` or `review.md`) is safely written.
   - When `--worktree` is enabled, run evidence is automatically synced back to the main project upon worker completion.

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
environment limitations. When a worker fixes a review finding, require it to
sweep all in-scope instances of that **bug class** and verify that any new
regression test exercises the target code path and fails at the expected assertion
or error site (rather than failing early in fixture setup). After integration or
fixes, rerun invalidated checks and reassess affected review conclusions before
claiming completion; do not open a new review cycle solely for optional `Nit`
advisory cleanups once `approved` is reached.

## Anti-involution circuit breakers (防内卷断路器)

1. **No Recursive Planning & Recovery Loops (禁止套娃复苏)**:
   - When a test, fixture, or environment verification fails, fix it in-place
     within the active task or report directly to the human.
   - Do NOT create new child runs to "plan", "prepare materials for", or "review"
     recovery of the test harness.
   - Maximum 1 direct recovery attempt per failure before human escalation.

2. **Pragmatic Scope & Scaffolding Limits (禁止过度工程)**:
   - Test fixtures and diagnostic scaffolding must not exceed 50% of the
     target feature's code size.
   - Local single-user tools must not construct adversarial kernel-level
     defense architectures (e.g. pidfd namespaces, SCM_RIGHTS brokers,
     synthetic oracles). Rely on OS user isolation.

3. **Consecutive Non-Product Run Halting (零产出停机)**:
   - If two consecutive runs produce 0 lines of product code and only touch
     manifests, test previews, or test fixtures, halt the pipeline immediately
     and escalate to the human via the primary interaction channel (e.g. AskHuman when configured).

4. **Human-First Language Protocol (人话报告规范)**:
   - Strictly forbid telegraphic run-on text without spaces.
   - Forbid defensive boilerplate spam.
   - All reports and reviews must be concise, structured, and understandable:
     1. What was done (plain language summary)
     2. Verification evidence & concrete results
     3. Blockers & real tradeoffs
     4. Concrete next steps.
