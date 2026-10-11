---
name: team-review
description: Run an independent read-only review with stable findings and a verdict.
---
# Team review

Use a fresh reviewer context with requirements, plan, decisions, reports, diff,
verification evidence, and prior findings for tracking. The reviewer must not
author or fix the implementation. Record the reviewed revision and working-tree
or diff identity, and identify who produced verification evidence.
Give findings cycle IDs, severity and rationale, exact locations, triggers,
impact, evidence, and required or advisory fixes. Reference the original finding
ID when the same issue persists across cycles; do not invent findings.

Return `approved` when acceptance and necessary evidence are satisfied with no
required fixes; advisory suggestions may remain. Return `changes-requested` for
established defects requiring fixes, or `blocked` when missing essential inputs
or verification prevent a supported verdict. Request exact commands and expected
evidence from the coordinator when the reviewer cannot execute them.

The reviewer returns completed review.md content using the supplied template,
including Run, Cycle, and canonical Verdict. The coordinator persists it
verbatim
and owns manifest changes: increment `review.used` for every completed review
before recording its verdict. Keep the review fields synchronized with run.toml;
when a new cycle is pending, its cycle number is `review.used + 1`.
Do not start another pending cycle when `review.used` has reached `review.limit`;
record the run as blocked if the final allowed cycle does not approve it.
Review/fix may repeat no more than the configured cycle limit.
After fixes or integration changes, reassess which review conclusions still
apply
to the current code; use another permitted cycle when necessary. Do not silently
reuse approval for changed behavior or rewrite the reviewer's verdict.
