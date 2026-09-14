---
name: team-workflow
description: Select and operate the smallest adequate agent-team workflow tier.
---

# Team workflow

1. Read the approved requirements, plan, decisions, and current run manifest.
2. Use `solo` for bounded work, `assisted` for up to two mostly read-heavy
   workers, and `team` only when parallel ownership and independent review pay
   for their coordination cost.
3. Give every worker a bounded task, owned files, no-edit boundary, acceptance
   criteria, exact verification, and report path.
4. Treat `run.toml` `max_workers` as a hard concurrency ceiling and dispatch
   excess ready work in later waves.
5. In assisted tier, run at most one write-capable worker at a time. In team
   tier, parallel writers require disjoint files or separate worktrees.
6. Persist worker evidence when `reports_required` is true, enforce phase gates,
   and close every worker before completion. Team tier always requires reports.
