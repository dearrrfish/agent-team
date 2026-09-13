# agent-team

`agent-team` generates portable, role-based native agent teams for Codex,
Claude Code, and Antigravity CLI. It provides adaptive workflow tiers, durable
run artifacts, strict validation, and preview-first safe installation.

## Quick start

```console
nix develop
agent-team init
agent-team validate
agent-team render --target codex --output ./dist/codex
agent-team install --target codex
```

`install` is a preview unless `--apply` is provided. Existing unmanaged files
and drifted managed files are refused unless `--force` is explicit; forced
replacement creates a backup.

## Workflow tiers

- `solo`: coordinator-only work without required durable artifacts.
- `assisted`: up to two read-heavy workers with serialized writes.
- `team`: file-disjoint or worktree-isolated workers, durable reports, and
  mandatory independent review.

Run `agent-team doctor` for environment checks and `agent-team --help` for the
complete command surface.
