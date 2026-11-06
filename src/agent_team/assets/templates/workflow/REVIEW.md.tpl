# Project Review Policy (`.agent-team/REVIEW.md`)

This file defines repository-specific review instructions, accepted design
assumptions, skip paths, and noise controls for `reviewer` and `team-review`.
It is created once by `agent-team generate templates` when absent and preserved
across later template updates so project maintainers can customize it safely.

## Architecture assumptions and accepted risks

- Record intentional design trade-offs (for example, trusted single-writer
  assumptions, bounded local concurrency, or explicit CLI trust boundaries) so
  reviewers treat them as `intentional` or `accepted-risk` rather than
  recurring `changes-requested` findings.

## Project-specific failure modes

- List high-value defect classes specific to this repository (for example,
  path containment checks, schema/manifest synchronization, atomic file writes,
  or cross-target rendering parity).

## Skip paths and low-priority areas

- List generated files, vendored assets, lockfiles, or historical run snapshots
  that should not receive line-by-line review comments unless a task explicitly
  targets them:
  - `.agent-team/runs/**`
  - `.agent-team/backups/**`

## Convergence and noise policy

- **Cycle 1 (`full-scope` + Bug-Class Sweep)**: Review all changed files against
  the run baseline. When a defect is found, identify its **bug class** and
  enumerate all in-scope occurrences in one cycle rather than flagging one
  location per round.
- **Cycle 2+ (`diff-only` re-review)**: Scope re-review to prior open/disputed
  findings plus the corrective diff and its direct call boundaries. Do not open
  new blocking findings on unchanged code that was already present in Cycle 1;
  classify unrelated legacy issues as `Pre-existing`.
- **Finding categories and Nit cap**: Classify every finding as `Important`
  (blocking required fix), `Nit` (non-blocking advisory, capped at **at most 2**
  per cycle; omit pure style or cleanup noise), or `Pre-existing` (predates the
  change and is not aggravated by it; record under residual risks without
  blocking approval).
- **Dispositions**: Respect prior finding dispositions (`fixed`, `intentional`,
  `accepted-risk`, `false-positive`, `pre-existing`) backed by `decisions.md`,
  this `REVIEW.md`, or code/test evidence. Do not repeat resolved or accepted
  findings in later cycles.

## Host and verification boundaries

- Distinguish code defects from host or environment limitations (for example,
  unavailable cross-platform builders or GUI display servers). Missing host
  capabilities that are documented in verification evidence must not be
  misclassified as code regressions.
