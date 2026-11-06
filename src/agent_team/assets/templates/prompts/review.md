Use reviewer to review the changes against .agent-team/runs/<slug>/. Keep the
agent read-only. Return findings with file evidence, verification gaps, and an
approved, changes-requested, or blocked verdict. Do not fix findings in the
review agent.

### Pragmatic Review Rules (实效审查与收敛原则)

- Focus on actual correctness, functionality, regressions, and security risks—NOT procedural formalities.
- Follow `.agent-team/REVIEW.md` (when present) for project-specific assumptions, accepted risks, and skip paths.
- **Cycle 1 (`full-scope` + Bug-Class Sweep)**: Flag the **class of bug** and list all in-scope instances in one pass rather than one location per round.
- **Cycle 2+ (`diff-only` re-review)**: Restrict re-review to prior open findings plus the corrective diff and its direct call boundaries; do not raise new blocking findings on unchanged code already present in Cycle 1.
- Classify findings as `Important` (blocking), `Nit` (advisory, capped at at most 2 per cycle; omit style noise), or `Pre-existing` (non-blocking legacy issue). Respect prior `intentional` and `accepted-risk` dispositions without repeating them.
- Do NOT demand exhaustive full-repository SHA-256 hash baselines of unchanged files, and forbid `changes-requested` or `blocked` verdicts for missing boilerplate disclaimers or procedural hedging.
- Provide clear, actionable findings with exact `file:line` evidence and direct instructions on how to resolve them.
