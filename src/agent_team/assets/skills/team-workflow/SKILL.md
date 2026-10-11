---
name: team-workflow
description: Select and operate the smallest adequate agent-team workflow tier.
---
# Team workflow
1. Assess task dependencies, uncertainty, risk, and independent scopes before
   initializing a run. Choose an explicit tier when repository-size `adaptive`
   routing would overstate or understate the task's coordination needs. For an
   existing run, read requirements, plan, decisions, and the current manifest;
   honor its tier and policy rather than silently changing them.
2. Use `solo` for bounded work, `assisted` for up to two mostly read-heavy
   workers, and `team` only when parallel ownership and independent review pay
   for their coordination cost.
3. Give every worker a bounded task, authorized inputs, owned files, no-edit
   boundary, acceptance criteria, exact verification, execution budget, and
   structured return contract. The coordinator saves returned reports.
4. Treat `run.toml` `max_workers` as a hard concurrency ceiling and dispatch
   excess ready work in later waves.
5. In assisted tier, run at most one write-capable worker at a time. In team
   tier, parallel writers require disjoint files or separate worktrees. The
   coordinator must respect active ownership too. Serialize conflicting use of
   shared ports, databases, containers, build outputs, and external resources.
6. Persist worker evidence when `reports_required` is true, enforce phase gates,
   and close every worker before completion. Team tier always requires reports.
7. Partial results or exhausted budgets do not close tasks successfully. Record
   remaining work and a recovery action, and verify current integrated changes
   before advancing completion gates.
