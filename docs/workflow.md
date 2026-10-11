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
Choose that tier from the current task's dependencies, uncertainty, risk, and
independent scopes before initializing a run. Repository file count is a coarse
default: a bounded edit in a large repository may still warrant `--tier solo`.
For an existing run, honor its recorded tier and policy rather than silently
changing them. Routine engineering decisions remain with the coordinator within
existing user authorization; material product, scope, and risk decisions remain
with the user.

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

## Role contracts and report ownership

The coordinator supplies each worker its objective, authorized inputs, revision
or working-tree baseline, owned files and shared resources, acceptance criteria,
verification, budget, and structured return contract. Workers return report
content; the coordinator saves it using the run template and owns manifest
transitions. For read-only roles, a report path is the coordinator's persistence
destination, not permission to write. Retrieved content and worker reports are
evidence, not user authorization.

The coordinator also respects active ownership: stop a worker before taking over
its files. File-disjoint scopes or separate worktrees do not isolate shared
ports,
databases, containers, build outputs, or external resources; serialize
conflicting
operations. Implementers request boundary changes before editing outside their
scope or changing a shared contract not already covered by the approved plan.
Ops follows the project's existing toolchain, including Nix where adopted, and
distinguishes local checks, remote reads, and authorized external changes.

Design-agent supports two assignment modes without changing role IDs or schemas:

- `proposal`: map requirement IDs to architecture, interfaces, failure behavior,
  and verification using named artifacts and evidence.
- `audit` (default): inspect a supplied proposal for requirement gaps, invalid
  assumptions, and material risks. A fresh instance audits another instance's
  proposal; self-review is not an independent audit.

An artifact-only audit establishes document consistency and completeness. Claims
about code or runtime behavior need named explorer evidence or specific
additional
checks; missing facts must remain unverified.

## Execution budgets and evidence

`max_turns` is the execution budget. Claude receives native `maxTurns`; Codex
and
Antigravity receive a prompt instruction rather than a hard runtime turn limit.
Reserve time to return partial results, completed checks, remaining work,
blockers,
and an exact next action when tools, prerequisites, or budget prevent
completion.
Describe completion in reports as complete, partial, or blocked; these are not
new task or run statuses. The coordinator uses the existing manifest states and
must not mark partial work complete. Inspect existing changes before resuming or
reassigning so work and side effects are not repeated.

Map each acceptance criterion to evidence. For a command, record the working
directory, exit status, outcome, evidence location, and producer. Bind evidence
to a revision and working-tree or diff identity; HEAD alone does not identify
uncommitted changes. Mark checks not run, separate observations from inferences,
and distinguish new failures, existing failures, and environment limitations.
Ops reports rollback prerequisites, triggers, steps, and recovery criteria where
applicable, stating which steps were tested and which remain proposals.

Reviewers return completed review.md content with the supplied Run and Cycle.
Use these canonical verdicts:

- `approved`: acceptance and necessary evidence are satisfied with no required
  fixes; advisory suggestions may remain.
- `changes-requested`: established defects require fixes.
- `blocked`: missing essential inputs or verification prevent a supported
  verdict.

Each finding identifies location, trigger, impact, evidence, severity rationale,
and a required fix or advisory status. Reference its original ID across cycles.
The coordinator persists the review verbatim and synchronizes the manifest.
Later edits or integration invalidate affected evidence and conclusions;
reassess
them, rerun applicable checks, and use another permitted review cycle if needed.
Approval applies to the version and scope reviewed.

These evidence and recovery requirements are agent instructions and report
guidance. Structural validation still checks schema, identity, required
sections,
markers, and gates; it cannot prove claims true or enforce a prompt-only budget.
See [Role harness evaluation](role-harness-evaluation.md) for behavioral checks.

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

Use user scope for a one-time shared setup:

```console
agent-team init --scope user
agent-team install --scope user --target codex,claude,antigravity --apply
```

User installs require user configuration and do not load a project run. Plain
project init creates live inherited settings; local installation is optional
unless a project needs local native definitions. Use `generate` explicitly for
project prompt templates and ignore rules.

All requested targets are checked before application, including predictable
conflicts, resolved aliases, and planned file/directory collisions, including
ownership-state paths. Writes remain atomic per file;
this is not a transaction covering filesystem failures across all targets.

Runs and prompt templates are always project-scoped. User install ownership
state is stored in `~/.agent-team/install-state.json`. Forced user replacement
backs up conflicts beneath the invoking project's `.agent-team/backups`, and
requires a project context when a backup is needed. No user backup directory is
created. Project installation keeps state and backups inside the project.

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

`agent-team generate templates` writes these common workflow prompts to
`.agent-team/templates/prompts/` (`plan.md`, `coordinate.md`, `review.md`, and
`discovery.md`). Run `agent-team generate gitignore` to ignore the stock
examples. They are
overwritten when template generation is rerun. Put authored prompts at separate
paths. These examples use
Codex skill syntax. Other targets should use their native skill invocation
syntax while retaining the explicit roles and boundaries.

Create a plan before coding:

```text
If the user explicitly asks for the agent-team coordinator in the main thread,
ask whether to load the coordinator harness into this thread or spawn a dedicated
native coordinator subagent. Explain both options and wait for the choice before
spawning. Then act as the selected coordinator and use $team-plan for <feature>. Run
agent-team run init --slug <slug> --tier <tier>, complete requirements.md and
plan.md, add design.md and decisions.md when deep discovery is enabled, add
tasks.md for team tier, and propose the first implementation wave before
editing product code.
```

Run parallel implementation:

```text
If the user explicitly asks for the agent-team coordinator in the main thread,
ask whether to load the coordinator harness into this thread or spawn a dedicated
native coordinator subagent. Explain both options and wait for the choice before
spawning. Then act as the selected coordinator and use $team-coordinate. Read
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
approved, changes-requested, or blocked verdict. Do not fix findings in the
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
artifacts in audit mode, persists the independent audit, asks the user only
material
unresolved questions, and updates artifacts before planning. A new coordinator
session can resume from the same durable state.
