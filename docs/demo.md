# Two-minute demo runbook

The strongest demo follows one real incident from an operator-selected fault to a
verified repair. The two choices are payment timeout and missing coupon. Use the
other fault as a backup or a short follow-up, rather than rushing two complete
investigations into the submission video.

Both integrated fault flows have completed with actual Gemini diagnosis, Modal
verification and human approval. The payment-timeout approval ran through the
typed input of a connected Gemini Live session; the coupon approval used the
review modal. Native PCM audio and transcripts reached the browser. A human
microphone was not tested. See [the execution evidence](verification-evidence.md)
for the exact scope.

## Before recording

1. Install dependencies in the project `.venv` and web workspace as described in
   the root README. Run the project's checks once after final integration.
2. Select `VERIFICATION_BACKEND=modal`. Warm the image with
   `.venv/bin/python -m scripts.check_modal --prepare-only`. The two complete cloud
   checks have already succeeded; repeating them is optional and consumes credits.
3. If Gemini diagnosis and Live have passed actual credential/model checks, enable
   those paths. Otherwise use the proved Modal flow with typed commands and identify
   the missing provider connection honestly. A `/health` configured flag is not proof.
4. Start the hub on loopback and open the web app. Choose **Live system**, confirm
   **Hub connected**, then open **Operator** and **Reset system**.
5. If using Gemini Live, connect it before injecting the fault and allow microphone
   permission. Check speaker output and input transcription with a harmless status
   question. Keep the text input and explicit apply button available.
6. Use a headset, readable browser zoom and a clean desktop. Keep the patch diff and
   real Modal logs available. Do not display environment files or credential pages.

The “Live system” view shows the connected hub and its configured backends. The
hub and toy shop run locally while verification can run in Modal. If port 8000 is
occupied, use `WAR_ROOM_PORT=8001 ./scripts/dev.sh`; the launcher pairs the UI with
that hub address. Do not start another launcher over an already running demo.

## Two-minute recording plan

| Time | Show | Say or do |
| --- | --- | --- |
| 0:00–0:12 | Clean war room, no active incident | “When checkout breaks, an explanation is not enough. First Response brings evidence and a tested repair to the on-call operator.” |
| 0:12–0:25 | Operator page, two fault buttons | Let someone choose a fault. Press **Inject fault & investigate**. “This changes actual toy-shop code. These errors come from real checkout probes.” |
| 0:25–0:42 | Evidence and changed line | Ask “What is happening with checkout?” If Gemini Live is connected, use voice. “Conversation is separate from the investigator, so the work continues in the background.” |
| 0:42–1:03 | Three candidate cards and results | “Each repair gets its own network-disabled Modal sandbox. First we establish a failing reproduction; then we run it and the regression suite for every candidate.” |
| 1:03–1:22 | One rejected result, then the passing result | Open actual logs. Point out the rejected shortcut and the successful candidate's 25 checks: one reproduction plus 24 regression tests. Read the measured timer only after it has stopped. |
| 1:22–1:43 | Verified diff, explicit approval, resolved state | Inspect the change. Say “Apply the verified fix” only when a verified fix is visible, or use **Approve & apply repair**. Explain that application triggers another test run and checkout probes. |
| 1:43–2:00 | Patch artifact and architecture | “The deliverable is a verified patch and an evidence trail. Today this covers two rehearsed toy-shop faults. The pattern is evidence, isolation, tests, then human approval.” |

These timestamps are an editing plan, not simulated runtime guarantees. If tests
finish early, inspect their evidence. If they take longer, trim narration or edit
the recording with a clearly disclosed cut. Never slow or replace a live number to
make the timing look better.

## Spoken and typed commands

- “What is happening with checkout?” — the current factual milestone.
- “Explain the cause.” — the confirmed cause, once available.
- “What was tried?” — actual candidate outcomes and test counts.
- “Apply the verified fix.” — explicit authorization after verification.

A disconnected Live session can be replaced by the text input. Identify this as
typed control; browser speech recognition or synthetic narration is not evidence
that Gemini Live ran. If approval transcription is ambiguous, use the explicit
button instead of weakening the confirmation check.

## Reset and second fault

Return to **Operator**, press **Reset system**, and wait for the reset confirmation.
Choose the other fault and start a new investigation. Reset cancels the active job
and invalidates earlier incident state. Do not approve a candidate from a previous
incident. The hub rejects a second fault while an unresolved incident is active.

## Failure and backup plan

| Situation | Honest response |
| --- | --- |
| No candidate passes | Show the failed checks. Explain that no fix is offered and the shop remains broken. |
| Gemini unavailable | Use explicit local diagnosis/typed control and keep real Modal verification; disclose the provider limitation. |
| Modal unavailable | Show the provider error. Either stop, use an existing recorded video, or explicitly restart with the local verifier and label it as local execution. |
| Need a predictable visual walkthrough | Switch to **Rehearsal** and say it is a 45-second replay of illustrative events with no live tests or changes. |
| Approval or post-apply check fails | Show the error and restored runtime state. Do not claim resolution or a created PR. |

Keep a backup two-minute recording of a successful actual run. Rehearsal JSON is a
separate UI aid, not a substitute for cloud execution evidence.

## Five-minute finalist expansion

Use the same two-minute incident story, then spend one minute on the architecture,
one minute on a rejected repair and the approval boundary, and one minute on the
second fault or judge questions. The two-minute submission video remains its own
artifact; a five-minute finalist slot does not change that requirement.
