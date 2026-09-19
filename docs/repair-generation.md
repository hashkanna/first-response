# Generated repairs

`REPAIR_BACKEND=gemini` enables real model-authored edits. It requires
`VERIFICATION_BACKEND=modal`; the hub refuses to start with generated repairs and
local execution. `REPAIR_BACKEND=authored` preserves the offline development flow.

## What the model sees

With `INVESTIGATOR_BACKEND=gemini`, after actual checkout probes fail, a Pydantic AI investigator analyzes the observed
exception, numbered source and injected deploy diff. A second typed agent receives
that grounded diagnosis, the evidence, the current application source and the
failing reproduction. It receives no candidate library or prewritten repair.

The model proposes exactly three distinct edits intended to repair the behavior.
They can all pass, all fail, or produce mixed results. No failure is staged in
generated mode, and a provider error never selects an authored repair silently.

## Narrow edit surface

Each candidate can replace one existing single-line assignment in `app/*.py`.
The assignment target and surrounding syntax must remain intact. Only bounded
scalar expressions, existing names and attributes, conditionals and a narrowly
validated `getattr(..., ..., None)` are accepted. Tests, probes, imports, package
initializers and new files are outside the editable surface.

This structural screen is defense in depth. **Modal is the execution boundary.**
The host parses and saves source as data; it never imports generated modules or
runs generated recovery probes. Sandboxes have networking disabled, no provider
credentials, bounded CPU/memory, and a 60-second lifetime.

## Verification and approval

1. Confirm the authored reproduction fails on the actual broken snapshot.
2. Fingerprint the complete Python snapshot, including the immutable test suite
   and probe, with SHA256.
3. Validate the typed model output and bind each candidate to that fingerprint.
4. Test each edit independently in Modal: one reproduction and 24 regressions.
5. Offer only candidates with successful application, both suites passing,
   positive executed-test counts and zero failures.
6. On approval, check the incident, candidate, exact diff and source fingerprint
   again. Save the selected validated edit to the runtime copy as data.
7. Re-run tests and 12 checkout probes in Modal against the saved snapshot.
   On failure or cancellation, restore the original runtime file.

The clean checked-in shop is unchanged. Approval creates a downloadable patch,
not a remote pull request or production deployment.

## Evidence

The ignored `.runtime/generated-repairs.json` records the model, request/token
counts, SHA256 digests for the source and input/output payloads, and actual
candidate edits. Incident events expose `origin: "gemini"` and `snapshot_sha`.
The UI shows the origin on every candidate and the source digest in diff review.

The request limit is three model calls, with a 60-second generation timeout.
Provider receipts and actual cloud execution results are separate evidence:
valid model output does not establish that any repair passed tests.

This remains a controlled demonstration of two fault types with authored tests.
It does not establish open-ended production diagnosis or repair safety.
