# Review: ${title}

- Run: `${slug}`
- Cycle: ${cycle}
- Review-Mode: full-scope
- Updated: `${updated_at}`
- Verdict: pending


## Scope and evidence

<!-- REQUIRED: Record review mode (`full-scope` for Cycle 1 or `diff-only` for
Cycle 2+), optional workspace fingerprint headers (`- Base-Revision:`,
`- Revision:`, `- Tracked-Diff-SHA256:`, `- Untracked-SHA256:`), reviewed
artifacts, `.agent-team/REVIEW.md` policy if present, and verification evidence
with its producer and applicability. -->

## Findings

| ID | Severity / Category | Bug class & finding | Disposition & required fix |
| --- | --- | --- | --- |
| C${cycle}-F001 | <!-- REQUIRED: severity (`critical`, `high`, `medium`, `low`), category (`Important`, `Nit`, or `Pre-existing`), and rationale, or `None`. Cap `Nit` findings at 2 per cycle. --> | <!-- REQUIRED: bug class (and all in-scope occurrences swept in Cycle 1), exact `file:line` location, trigger, impact, and evidence, or `None`. Reference the original ID for recurring findings. --> | <!-- REQUIRED: disposition (`open`, `fixed`, `intentional`, `accepted-risk`, `false-positive`, or `pre-existing`) and required fix or advisory status, or `None`. --> |

## Residual risks and gaps

<!-- REQUIRED: Record residual risks, accepted risks (`intentional` /
`accepted-risk`), `Pre-existing` issues, and verification gaps, or `None`. Use
approved when acceptance and necessary evidence are satisfied with no open
`Important` required fixes; changes-requested for established `Important`
defects requiring fixes; blocked when missing essential inputs or verification
prevent a supported verdict. -->
