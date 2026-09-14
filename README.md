# agent-team

`agent-team` generates portable, role-based native agent teams for Codex,
Claude Code, and Antigravity CLI. It provides adaptive workflow tiers, durable
run artifacts, strict validation, and preview-first safe installation.

## Quick start

```console
nix develop
agent-team init
agent-team validate
agent-team run init --slug my-change --model-preset balanced
agent-team render --target codex --run my-change --output ./dist/codex
agent-team install --target codex --run my-change
agent-team install --target codex --run my-change --apply
```

`install` is a preview unless `--apply` is provided. Existing unmanaged files
and drifted managed files are refused unless `--force` is explicit; forced
replacement creates a backup. Passing `--run <slug>` to `render` or `install`
applies that run's model preset; without it, the project default is used.

For project-scoped Codex installs, trust the project in Codex and start a fresh
session after `--apply`. Codex intentionally skips project `.codex/` agents in
untrusted projects. Name the desired custom role explicitly in workflow prompts;
the selected agent file supplies its model, reasoning effort, permissions, and
role instructions.

## Workflow tiers

- `solo`: coordinator-only work without required durable artifacts.
- `assisted`: up to two read-heavy workers with serialized writes.
- `team`: file-disjoint or worktree-isolated workers, durable reports, and
  mandatory independent review.

Each run records the selected tier's `max_workers` as a hard concurrency limit.
`workflow.persist_agent_reports` controls optional assisted-tier reports, while
solo runs have no worker reports and team runs always require them.

Run `agent-team doctor` for environment checks and `agent-team --help` for the
complete command surface.

## Common usage prompts

These Codex examples follow the same explicit role-naming pattern as the AWS
sample. For another target, use that client's native skill invocation syntax
while keeping the role names and task boundaries.

Plan before editing:

```text
Act as the main-thread coordinator and use $team-plan for this feature. Run
agent-team run init --slug <slug> --tier <tier>, capture requirements and
complete requirements.md and plan.md, add design.md and decisions.md when deep
discovery is enabled, add tasks.md for team tier, and propose the first
implementation wave before editing product code.
```

Run a bounded implementation wave:

```text
Act as the main-thread coordinator and use $team-coordinate. Read
.agent-team/runs/<slug>/run.toml and plan.md, plus tasks.md for team tier. For
assisted tier, record bounded task entries in run.toml and serialize writers.
Spawn implementer and ops custom agents only for independent, file-disjoint
scopes. Give each agent its role, instance name, task ID, exact files,
acceptance criteria, verification commands, and report path. Wait for the wave,
then consolidate the evidence.
```

Run focused discovery or design review:

```text
Use explorer for read-only repository evidence and design-agent for an
independent architecture gap review of .agent-team/runs/<slug>/. Keep both
agents read-only, wait for them, and summarize agreements and conflicts.
```

Run independent review:

```text
Use reviewer to review the current changes against
.agent-team/runs/<slug>/. Return findings with evidence, verification gaps, and
an approve, changes-requested, or blocked verdict. Do not fix findings in the
review agent.
```
