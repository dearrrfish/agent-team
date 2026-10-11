---
name: team-plan
description: Convert approved requirements into a decision-complete implementation plan.
---


# Team planning

Map each functional and non-functional requirement ID to implementation changes,
acceptance evidence, and exact verification. Specify interfaces, ownership of
files and shared resources, dependencies, failure behavior, migration or
rollback,
documentation, and assumptions requiring evidence. Resolve routine engineering
choices within existing authorization; ask the user only about material product,
scope, or risk decisions not already settled.

When design help is needed, explicitly assign `proposal` or `audit` mode to
design-agent; audit is the default. Use a fresh instance to independently audit
a proposal produced by another instance. Artifact-only audits establish document
consistency and completeness, not unverified repository or runtime facts.
Supply named explorer evidence or obtain it before accepting those assumptions.
Do not delegate implementation while material decisions remain open.
