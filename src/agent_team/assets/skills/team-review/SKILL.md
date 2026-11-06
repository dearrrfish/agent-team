---
name: team-review
description: Run an independent read-only review with stable findings and a verdict.
---
# Team review

Use a fresh reviewer context with requirements, plan, decisions, reports, diff,
verification evidence, prior findings/dispositions, and `.agent-team/REVIEW.md`
(if present) for tracking. Before dispatching `reviewer` (especially on
read-only targets without shell access), run
`agent-team run prepare-review --slug <slug>` to assemble the workspace-bound
review packet (recommended `review.md` header block with `Review-Mode`,
`Base-Revision`, `Revision`, `Tracked-Diff-SHA256`, and `Untracked-SHA256`,
changed files, prior findings, and verification state). The reviewer must not
author or fix the implementation. Record the reviewed revision and
working-tree or diff identity, and identify who produced verification evidence.

## Convergence rules

- **Cycle 1 (`full-scope` + Bug-Class Sweep)**: Review all changed files against
  the baseline. When a defect is found, identify its **bug class** and sweep all
  in-scope occurrences in the same cycle so the author fixes the whole class at
  once rather than one instance per cycle.
- **Cycle 2+ (`diff-only` re-review)**: Scope re-review to prior open/disputed
  findings plus the corrective diff and its direct call boundaries. Do not open
  new blocking findings on unchanged code already present in Cycle 1.
- **Categories and Nit cap**: Classify findings as `Important` (blocking
  required fix), `Nit` (non-blocking advisory, capped at **at most 2** per
  cycle; drop pure style/cleanup noise), or `Pre-existing` (predates the change
  and is not aggravated by it; record in residual risks without blocking
  approval).
- **Dispositions and no repeats**: Track finding dispositions (`open`, `fixed`,
  `intentional`, `accepted-risk`, `false-positive`, `pre-existing`) backed by
  `decisions.md`, `.agent-team/REVIEW.md`, or code/test evidence. Do not repeat
  resolved or accepted findings across cycles.
- **No re-review on pure advisory fixes**: Once a cycle returns `approved` (with
  only `Nit` advisories or `Pre-existing` notes), do not start another review
  cycle or follow-up review run solely to chase advisories; verify optional
  advisory cleanups locally with `agent-team run verify`.
- **Cycle 3 step-back**: If `Important` findings still do not converge by Cycle
  3, step back to reassess the design or escalate to the user rather than
  looping on incremental point patches.

Give findings cycle IDs, severity, category (`Important`, `Nit`, or
`Pre-existing`), bug class, rationale, exact `file:line` locations, triggers,
impact, evidence, and disposition/required or advisory fixes. Reference the
original finding ID when the same issue persists across cycles; do not invent
findings.

Return `approved` when acceptance and necessary evidence are satisfied with no
open `Important` required fixes; advisory `Nit` suggestions, `Pre-existing`
notes, and documented `intentional` or `accepted-risk` dispositions may remain.
Return `changes-requested` for established `Important` defects requiring fixes,
or `blocked` when missing essential inputs or verification prevent a supported
verdict. Request exact commands and expected evidence from the coordinator when
the reviewer cannot execute them.

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
