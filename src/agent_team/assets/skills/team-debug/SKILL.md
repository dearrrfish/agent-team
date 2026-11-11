---
name: team-debug
description: Systematic debugging and fault diagnosis with minimal reproduction.
---

# Team debug

Diagnose defects, test failures, performance regressions, and unexpected runtime
behavior using evidence-backed hypothesis testing and minimal reproduction.

## Investigation protocol

1. **Reproduce First (复现优先原则)**:
   - Before modifying any production or test code, construct a minimal,
     deterministic reproduction script or targeted test case that reliably
     demonstrates the failure.
   - Run the reproduction script to capture exact error output, stack traces,
     and failure symptoms.
   - Do not guess root causes or apply speculative patches without a failing
     reproduction.

2. **Evidence-Based Hypothesis & Localization (证据驱动与分层归因)**:
   - Formulate testable hypotheses based on reproduction output, error traces,
     and system evidence.
   - Narrow down the culprit to the single architectural layer responsible for the
     behavior.
   - Fix the defect at the owning layer; do not apply cross-layer defensive
     workarounds or paper over symptoms in calling layers.

3. **Scaffolding Overhead Ceiling (防膨胀红线)**:
   - Diagnostic instrumentation, test fixtures, and reproduction code must not
     exceed 50% of the target feature's code size.
   - Clean up temporary debug probes, prints, and ephemeral test harnesses
     before handing off or requesting review.

4. **Original Input End-to-End Verification (原输入端到端回归)**:
   - After applying the fix, verify that the minimal reproduction now passes.
   - Re-run the exact original failing command, input, or test suite to confirm
     end-to-end resolution.
   - Sweep all in-scope instances of the same bug class to prevent identical
     regressions across related modules.
