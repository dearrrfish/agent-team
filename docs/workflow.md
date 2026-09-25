# Workflow operations

## Choosing a tier

`adaptive` counts repository files after excluding Git metadata, generated run
state, worktrees, dependencies, and virtual environments. It selects `solo` for
at most 25 files, `assisted` for 26–200, and `team` above 200. An explicit
`--tier` always wins.

Use `solo` for bounded coordinator work. Use `assisted` when one or two
read-heavy workers reduce uncertainty and serialize any writes. Use `team` only
when tasks can be assigned disjoint files or isolated worktrees and independent
review justifies the coordination overhead.

## Starting and advancing a run

```console
agent-team run init --slug replace-parser --title "Replace parser" --tier team
```

To apply the run's selected cost/quality routing to native agents, pass its slug
when rendering or installing:

```console
agent-team render --target codex --run replace-parser --output ./dist/codex
agent-team install --target codex --run replace-parser --apply
```

The run manifest is authoritative for lifecycle, gates, task dependency state,
the effective `max_workers` concurrency ceiling, `write_isolation` policy,
report persistence, and review counters. Dispatch excess ready tasks in later
waves so the number of `running` tasks never exceeds `max_workers`; assisted
runs may have only one write-capable task running. Markdown is authoritative for
rationale, contracts, evidence, and verdict text. Update `updated_at` whenever
the manifest changes.

New runs start with `live_validation = false`. Set it to true only after the
run's exact verification commands have completed successfully and the evidence
has been recorded in the final report.

Statuses advance through `discovery`, `planned`, `implementing`, `reviewing`,
and `complete`; `blocked` and `cancelled` are terminal. Validation enforces the
gates required by the claimed phase. A team run cannot complete without closed
tasks, reports, resolved required markers, all gates, and an approved review.

Task IDs use `T-NNN`; dependencies must form a DAG, and a task cannot become
`ready`, `running`, or `complete` until every dependency is `complete`. Worker
instance names are unique within a run, neither coordinator nor reviewer can
appear as worker task roles, and solo runs cannot contain worker tasks. Reviewer
output belongs to the lifecycle `review.md` artifact. Completed tasks
must have a contained, structured `reports/` artifact
when `reports_required` is true. Copy
`reports/agent-report-template.md` to the exact task report path and complete
every section without changing its run, task, or role identity. The reusable
template and completed report identity are both validated. Setting
`workflow.persist_agent_reports = false` disables assisted-tier reports, while
solo runs have no worker reports and team runs always persist them as part of
the team-tier contract. Decision records are append-only and use `D-NNN`;
superseding decisions reference the earlier ID.

A required review cannot record an outcome verdict until at least one review
cycle has been counted in `review.used`. The Run, Cycle, and Verdict fields in
`review.md` must match the manifest; a pending cycle uses `review.used + 1`,
while a completed outcome uses `review.used`.
Once `review.used` reaches `review.limit`, another pending cycle is invalid; a
non-approved final cycle leaves the run blocked.

## Rendering and installation

`render` writes deterministic native files beneath an explicit output directory
and refuses to replace different existing output:

```console
agent-team render --target codex --output ./dist/codex
```

`install` renders directly to project or user scope. It only previews unless
`--apply` is present:

```console
agent-team install --target claude
agent-team install --target claude --apply
```

The ownership manifest records SHA-256 content hashes. A later installation may
update an unchanged managed file, but refuses unmanaged content or locally
drifted managed content. `--force` permits replacement only with a timestamped
backup. Installation does not edit client settings or enable experimental
features.

When a previously managed path is absent from the current target output,
installation reports it as `stale` but retains the file and ownership record.
V1 does not prune automatically because native targets can share installed
skills. Inspect each stale path and remove it manually only after confirming no
other target still owns or uses it.

Project and user installation paths follow each native client's discovery
layout. In particular, Antigravity project agents/skills use `.agents/`, while
user agents use `~/.gemini/config/agents/` and Antigravity CLI user skills use
`~/.gemini/antigravity-cli/skills/`.

### Native discovery prerequisites

After a project-scoped Codex install, trust the project and start a fresh Codex
session. Codex loads project `.codex/` layers only for trusted projects; an
untrusted project deliberately hides its custom agents. The installer does not
change trust or other native client settings.

When dispatching, name the custom role separately from its instance or task
name. The native profile is authoritative for model, reasoning effort,
permissions, and role instructions. If a named role is unavailable, stop and
diagnose installation, trust, working directory, and session freshness instead
of substituting a generic child.

### Common usage prompts

`agent-team init` writes these common workflow prompts to
`.agent-team/templates/prompts/` (`plan.md`, `coordinate.md`, `review.md`, and
`discovery.md`). These examples use Codex skill syntax. Other targets should use
their native skill invocation syntax while retaining the explicit roles and
boundaries.

Create a plan before coding:

```text
Act as the main-thread coordinator and use $team-plan for <feature>. Run
agent-team run init --slug <slug> --tier <tier>, complete requirements.md and
plan.md, add design.md and decisions.md when deep discovery is enabled, add
tasks.md for team tier, and propose the first implementation wave before
editing product code.
```

Run parallel implementation:

```text
Act as the main-thread coordinator and use $team-coordinate. Read
.agent-team/runs/<slug>/run.toml and plan.md, plus tasks.md for team tier. For
assisted tier, record bounded task entries in run.toml and serialize writers.
Split the next wave into file-disjoint scopes and spawn implementer or ops custom
agents only where their files do not overlap. Give each worker a unique instance
name, task ID, exact files, acceptance criteria, verification commands, and
report path. Wait for all workers, then consolidate their evidence and update
the run state.
```

Run a focused review:

```text
Use reviewer to review the changes against .agent-team/runs/<slug>/. Keep the
agent read-only. Return findings with file evidence, verification gaps, and an
approve, changes-requested, or blocked verdict. Do not fix findings in the
review agent.
```

Request read-only discovery and design advice:

```text
Use explorer to map the relevant code paths, then use design-agent to audit the
proposed design in .agent-team/runs/<slug>/ for missing decisions, interface
risks, and operational concerns. Wait for both and reconcile their findings in
the main thread.
```

## Deep discovery

When `deep_discovery_default` is enabled, run initialization adds `design.md`
and append-only `decisions.md`, then opens the design gate. The coordinator
checkpoints requirements and decisions, gives a fresh design-agent only those
artifacts, persists the independent audit, asks the user only material
unresolved questions, and updates artifacts before planning. A new coordinator
session can resume from the same durable state.
