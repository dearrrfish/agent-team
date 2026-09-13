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

The run manifest is authoritative for lifecycle, gates, task dependency state,
and review counters. Markdown is authoritative for rationale, contracts,
evidence, and verdict text. Update `updated_at` whenever the manifest changes.

Statuses advance through `discovery`, `planned`, `implementing`, `reviewing`,
and `complete`; `blocked` and `cancelled` are terminal. Validation enforces the
gates required by the claimed phase. A team run cannot complete without closed
tasks, reports, resolved required markers, all gates, and an approved review.

Task IDs use `T-NNN`; dependencies must form a DAG. Completed tasks must have a
contained `reports/` artifact. Decision records are append-only and use `D-NNN`;
superseding decisions reference the earlier ID.

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

## Deep discovery

When `deep_discovery_default` is enabled, run initialization adds `design.md` and
opens its gate. The coordinator checkpoints requirements and decisions, gives a
fresh design-agent only those artifacts, persists the independent audit, asks
the user only material unresolved questions, and updates artifacts before
planning. A new coordinator session can resume from the same durable state.
