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
4. Serialize overlapping writes. For team-tier parallel writers, use disjoint
   files or separate worktrees.
5. Persist worker evidence, enforce phase gates, and close every worker before
   completion.
