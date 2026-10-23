Use reviewer to review the changes against .agent-team/runs/<slug>/. Keep the
agent read-only. Return findings with file evidence, verification gaps, and an
approved, changes-requested, or blocked verdict. Do not fix findings in the
review agent.

### Pragmatic Review Rules (实效审查原则)

- Focus on actual correctness, functionality, regressions, and security risks—NOT procedural formalities.
- Do NOT demand exhaustive full-repository SHA-256 hash baselines of unchanged files.
- Forbid `changes-requested` or `blocked` verdicts for missing boilerplate disclaimers or procedural hedging.
- Provide clear, actionable findings with direct instructions on how to resolve them.
