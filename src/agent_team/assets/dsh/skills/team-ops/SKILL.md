---
name: team-ops
description: Operational verification, packaging, Nix flake maintenance, and drift recovery.
---

# Team ops

Manage operational infrastructure, Nix flake packaging, target installation,
configuration drift detection, and CI quality gates.

In DeepSeek Harness (DSH), use the verification and packaging guidance for the
repository at hand. Manage DSH presets and installed skills through the host's
own process. For explicitly requested Agent Teams CLI maintenance, see
[the Agent Teams CLI workflow](references/agent-team-workflow.md).

## Operations protocol

1. **Nix & Flake Integrity**:
   - Maintain `flake.nix` and `flake.lock`. Ensure package outputs, apps, and dev
     shells remain reproducible across developer environments.
   - Verify changes with `nix flake check path:.` before claiming completion.

2. **Platform & CI Verification**:
   - Differentiate local platform realities from CI and containerized
     environments.
   - Ensure all quality gates run cleanly:
     - Project validation: `PYTHONPATH=src python3 -m agent_team validate`
     - Unit tests: `PYTHONPATH=src python3 -m unittest discover -s tests`
     - Linting: `ruff check src tests`
     - Diff check: `git diff --check`

3. **Packaging & Clean Workspace**:
   - Prevent build outputs, worktrees, and temporary test fixtures from
     polluting git status.
