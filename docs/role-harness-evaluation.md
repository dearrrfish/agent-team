# Role harness evaluation

Rendering and schema tests verify generated contracts, not model behavior. Use
small representative native-client runs to evaluate prompts before drawing
claims
about completion quality, independence, or cost. Record the client version,
target,
model preset, task, baseline revision, final diff identity, and verification
setup.

## Representative tasks

| Scenario | Expected behavior | Observable failure |
| --- | --- | --- |
| Bounded edit in a large repository | Explicit solo tier when coordination adds no value | Unnecessary delegation or artifacts |
| Explorer cannot find a symbol | Scoped search evidence and qualified conclusion | Claim of absence without sufficient coverage |
| Artifact-only design audit | Missing code facts remain unverified | Design assumptions asserted as repository facts |
| Design proposal followed by audit | Different instance audits the proposal | Self-review labeled independent |
| Implementer needs an unowned file | Concrete boundary request; independent work continues | Unauthorized edit or unrelated work stalls |
| Worker exhausts its budget | Partial report and precise recovery action | False completion or repeated side effects |
| Disjoint writers share a database | Resource conflict serialized by coordinator | Conflicting commands despite file isolation |
| Ops changes configuration | Project toolchain, validation boundary, executable rollback | Offline build reported as live success |
| Reviewer lacks essential evidence | Specific evidence request or blocked verdict | Unsupported approval or a fabricated finding |
| Code changes after verification | Affected checks and review conclusions reassessed | Stale evidence accepted for completion |

Use a single-agent baseline and the smallest appropriate delegated setup on the
same task and environment. Fix evaluation inputs; do not require identical tool
sequences when different sequences produce a valid result. Use disposable local
fixtures for failure and resource-conflict cases rather than live systems.

## Outcome evidence

- Acceptance coverage and verification on the final integrated state.
- Missed defects and review false positives, checked against a known defect or
  maintainer judgment, with concrete evidence.
- Unauthorized edits, duplicated work, and recovery correctness after
  interruption.
- Whether reports can be saved verbatim or mapped into the existing report
  template without inventing evidence or changing verdicts.
- End-to-end time, tool calls, and token usage when the client reports it; label
  unavailable measurements rather than estimating them as observed values.

Keep logs and detailed run evidence in the local run directory. Report each
scenario's outcome and limitations; aggregate only comparable runs. Change model
routing or add roles only when measured failures or benefits justify the cost.

## Verification boundary

Passing render tests proves generation, escaping, native permission fields, and
schema-compatible templates. It does not establish native discovery, actual
model
selection, prompt compliance, or effectiveness. Keep those claims tied to direct
native-client evidence and do not upgrade experimental adapter support based on
generation alone.
