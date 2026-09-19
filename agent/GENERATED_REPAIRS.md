# Generated repair implementation

Set `REPAIR_BACKEND=gemini` to generate patches and
`VERIFICATION_BACKEND=modal` to execute them. The hub refuses the generated/local
combination. `REPAIR_BACKEND=authored` keeps the original credential-free fixture
strategies available. Diagnosis remains separately selectable through
`INVESTIGATOR_BACKEND`; the full cloud path uses Gemini for both diagnosis and
repair generation.

The repair agent receives the actual runtime Python application source,
exception evidence, source-change diff, grounded root cause, and already-failing
reproduction. It receives no authored candidate IDs, rationales or fix-library
entries. A Pydantic AI structured output contains exactly three candidate edits,
each intended to repair the observed failure. There is no preselected winner and
no deliberately failing candidate. Zero, one, two or three may pass execution.

Each candidate replaces one existing assignment line in one existing
`app/*.py` module. It retains the assignment target and surrounding structure.
Bounded expressions permit existing identifiers and attributes, scalar constants,
arithmetic, boolean comparisons, conditional expressions and the constrained
form `getattr(existing_object, existing_attribute, None)`. Imports, additional
statements, private attributes, dynamic execution, process/file/network calls,
test changes, probe changes, new files and package initializer changes are
rejected. This is a deliberately narrow edit surface for the two known incident
scenarios. The structural screen is a defense in depth check, not a security
sandbox.

The default generator is `gemini-3.8-flash`, configurable with
`GEMINI_REPAIR_MODEL`. The generation stage is bounded to three model requests
and 60 seconds, including validation retries. Failure stops the incident with
`no_fix_found`; there is no silent fixture or provider fallback. Diagnosis and
generation together use at most six logical model requests with their current
retry budgets.

`verification/generated.py` hashes the complete original Python snapshot,
including the immutable tests, probe and package initializers. Each generated
plan contains this SHA256 fingerprint. The displayed unified diff is derived
from the same validated text replacement. `FixCandidate.origin` is `gemini`, and
`FixCandidate.snapshot_sha` identifies its exact original source snapshot.

All generated test execution occurs inside a fresh, network-disabled Modal
sandbox. It receives only the source snapshot and the exact reviewed
reproduction. The original 24-test regression suite and the probe must match the
checked-in trusted fixtures. The verifier requires one passing reproduction and
24 passing regression tests. A model assertion is never a verification result.

Approval requires the current incident ID and the selected verified candidate
ID. Before changing the runtime, the hub checks both the complete source
fingerprint and the exact displayed patch. It writes the selected edit to
`.runtime/shop/` as data and then runs the reproduction, full suite and twelve
checkout probes together in Modal. The recovery verifier reconstructs the
original snapshot by reversing that exact edit in memory and checks its original
fingerprint. The hub also checks the runtime fingerprint again after the remote
run. A failed or interrupted recovery restores the original edited file and
does not mark the incident resolved.

Generated files are never imported, probed or executed on the host. As a second
barrier, local verification and probe helpers accept only checked-in shop
snapshots or their two reviewed fault variations; local candidate and
reproduction inputs must exactly match the authored fixture library. Reset
restores the clean checked-in shop before any subsequent local fault probe.

A successful generation writes `.runtime/generated-repairs.json` with model
name, logical request count, actual token counts, source SHA256, input/output
payload hashes, proposed edits and candidate IDs. This receipt records the
generation; the subsequent `VerifyResult` records execution. Successful approval
produces the downloadable patch artifact. None of these receipts contains API
credentials, and none implies that a GitHub pull request was opened.

`/status` and `/health` expose `repair_backend`. `/status` also exposes the
currently verified `recommended_candidate_id` for broad verbal approvals.
Explicit candidate buttons continue to submit their exact chosen ID. All
approval paths remain bound to the active incident, and repeated approval of
the same applied candidate returns the existing result.
