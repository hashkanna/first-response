# Submission and judging preparation

This checklist reflects the organizer rules read in the authenticated
[Tech Europe hackathon dashboard](https://hackathons.techeurope.io/dashboard/hackathons/tech-europe-agentic-ai-hack?tab=rules)
on 19 September 2026. The page may require a participant login. Confirm the final
submission form and its displayed deadline before uploading; this document is not
a submission receipt.

## Organizer requirements

| Requirement | Preparation needed |
| --- | --- |
| Dashboard deadline: **19 September, 19:15 CEST (18:15 London/BST)** | Re-read at 16:26 London; dashboard showed 1h49m remaining. Static Rules copy still says 19:00; use the live organizer deadline and finish early |
| Maximum **5 team members** | List the actual contributors and confirm the roster |
| Use at least **2 partner technologies** | Demonstrate Modal and Pydantic with concrete execution and validation; add Gemini only with an accurate account of the paths used |
| Newly created during the hackathon | Preserve the project's build history and describe any existing libraries or tooling accurately |
| **2-minute demo video** | Record the actual incident flow; use [the timing plan](demo.md) |
| Detailed solution and live walkthrough | Supply architecture, implementation boundaries, setup and reproducible steps |
| Public GitHub repository | Publish the reviewed repository with comprehensive README and API/technical documentation; never include credentials or ignored runtime data |
| Five finalist teams; **5-minute live demo** | Prepare the expanded version without changing the two-minute submission artifact |

The organizer lists separate **€1,500 Modal and €1,500 Pydantic side prizes**.
These are opportunities, not guarantees. No prize, finalist place, public repository
or submission is claimed as completed by these documents.

## The strongest supported pitch

Lead with the decision the operator can make: **“Here is the evidence, here are the
repairs we tested, and here is why this one is eligible for your approval.”**
The strongest visual is real generated diffs next to their independent test results,
followed by human approval and a fresh recovery check. Do not manufacture a losing
candidate: several generated edits may legitimately pass.

- **Modal:** show separate sandbox IDs and actual test logs for all three candidates.
  The cloud execution is essential to the verification boundary, not a background
  logo. The first eight jobs are documented in [the evidence summary](verification-evidence.md).
- **Pydantic:** show the shared incident/tool contracts and the gate rejecting
  unsupported actions. If the Gemini analysis path has run, show its grounded
  output, exact evidence citations and bounded validation retries separately.
- **Gemini:** show actual Live conversation and a real milestone interruption only
  after that connection works. Explain that conversation stays separate from the
  investigation and cannot bypass executable verification or human approval.

Avoid claiming arbitrary production repair, unrestricted production patch generation,
continuous production monitoring, Logfire ingestion, Gateway failover, Jev remote
gating or an opened GitHub PR. They are not established features of this build.
The implementation produces a downloadable patch and repairs a local toy-shop copy.

## Submission draft

Use the [current submission text and fields](submission.md), updated for actual
model-generated repair execution.

## Final evidence checklist

- Record one successful browser-to-hub incident with the chosen execution modes
  visible, then retain the exported incident report and actual cloud receipts.
- Confirm whether Gemini diagnosis and native Live audio have each completed a
  real provider request. Describe implementation and verified execution separately.
- Keep the recorded rehearsal visibly labeled; its 24-test fixture counts are not
  the real runner's 25-check results.
- Capture a no-fix or rejected-candidate result so the approval boundary is visible.
- Verify repository links, setup instructions, API documentation and video duration
  in the final submission form. Publishing the repository and submitting the form
  are separate actions that require successful read-back.
- Preserve the organizer's final submission confirmation rather than treating
  a drafted description, uploaded video or locally prepared repository as submitted.
