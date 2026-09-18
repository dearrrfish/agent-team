# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- SHA-pinned GitHub Actions release checks and contributor, security, conduct,
  issue, pull request, and ownership guidance for the public repository.

## [0.1.0] - 2026-09-18

### Added

- Portable native agent and skill generation for Codex, Claude Code, and
  Antigravity CLI.
- Coordinator, explorer, design-agent, implementer, ops, and reviewer roles with
  explicit delegation, write, capability, turn, and report boundaries.
- Adaptive `solo`, `assisted`, and `team` workflow tiers with enforced worker
  ceilings and write-isolation policies.
- Durable requirements, design, plan, task, decision, worker-report, review, and
  final-report artifacts with strict lifecycle validation.
- Economy, balanced, and quality model-routing presets owned by target profiles.
- Deterministic rendering and preview-first project or user installation with
  ownership hashes, atomic writes, drift refusal, and forced-replacement backups.
- Nix package, app, development shell, unit/Ruff gate, ShellCheck, and installed
  cross-target release smoke coverage.
- Operator documentation, common coordination prompts, support status, and an
  agent-team topology diagram.
- Canonical GitHub project metadata and remote Nix run/install instructions.

### Compatibility

- Codex native role discovery and model-backed selection are verified.
- Claude Code and Antigravity adapters are experimental pending complete
  model-backed native validation.
- `x86_64-linux` is built and tested. `aarch64-linux` outputs evaluate but still
  require native build and runtime verification.

### Safety

- The installer never modifies native client settings or enables experimental
  features.
- Stale managed files are reported and retained instead of being pruned without
  shared-ownership evidence.
- Claude Code and Antigravity read-only roles omit shell access because those
  clients cannot guarantee a non-mutating command boundary in every parent mode.

[Unreleased]: https://github.com/dearrrfish/agent-team/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/dearrrfish/agent-team/releases/tag/v0.1.0
