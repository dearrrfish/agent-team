---
name: team-review
description: Run an independent read-only review with stable findings and a verdict.
---

# Team review

The reviewer must not author or fix the implementation. Inspect requirements,
plan, decisions, reports, diff, and reproducible verification. Assign stable
cycle finding IDs and return `approved`, `changes-requested`, or `blocked`.
Increment `review.used` for every completed review before recording its verdict.
Keep the `review.md` Run, Cycle, and Verdict fields synchronized with `run.toml`;
when a new cycle is pending, its cycle number is `review.used + 1`.
Do not start another pending cycle when `review.used` has reached `review.limit`;
record the run as blocked if the final allowed cycle does not approve it.
Review/fix may repeat no more than the configured cycle limit.
