---
name: team-ops
description: Operational verification, packaging, Nix flake maintenance, and drift recovery.
---

# Team ops

Manage operational infrastructure, Nix flake packaging, target installation,
configuration drift detection, and CI quality gates.

## Operations protocol

1. **Nix & Flake Integrity**:
   - Maintain `flake.nix` and `flake.lock`. Ensure package outputs, apps, and dev
     shells remain reproducible across developer environments.
   - Verify changes with `nix flake check path:.` before claiming completion.

2. **Installation & Drift Management**:
   - Audit installed native agents and skills across targets (`codex`,
     `claude`, `antigravity`, `pi`).
   - Detect configuration and agent file drift using
     `agent-team install --target <target>`.
   - Reconcile drifted installations with `--apply` or `--force` when authorized.

3. **Platform & CI Verification**:
   - Differentiate local platform realities from CI and containerized
     environments.
   - Ensure all quality gates run cleanly:
     - Project validation: `PYTHONPATH=src python3 -m agent_team validate`
     - Unit tests: `PYTHONPATH=src python3 -m unittest discover -s tests`
     - Linting: `ruff check src tests`
     - Diff check: `git diff --check`

4. **Packaging & Clean Workspace**:
   - Prevent build outputs, worktrees, and temporary test fixtures from
     polluting git status.
   - Maintain project ignore rules with `agent-team generate gitignore`.
