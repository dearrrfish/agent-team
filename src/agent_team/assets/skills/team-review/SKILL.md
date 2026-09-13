---
name: team-review
description: Run an independent read-only review with stable findings and a verdict.
---

# Team review

The reviewer must not author or fix the implementation. Inspect requirements,
plan, decisions, reports, diff, and reproducible verification. Assign stable
cycle finding IDs and return `approved`, `changes-requested`, or `blocked`.
Review/fix may repeat no more than the configured cycle limit.
