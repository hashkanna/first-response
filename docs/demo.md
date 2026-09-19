# Two-minute demo runbook

The strongest demo follows one real incident from an operator-selected fault to a
verified repair. The two choices are payment timeout and missing coupon. Use the
other fault as a backup or a short follow-up, rather than rushing two complete
investigations into the submission video.

Both faults have completed with actual Gemini-generated repairs, Modal
verification and explicit browser approval. The measured generated timeout run
had two passing repairs and one genuine regression failure; another run need not
produce the same outcomes. See [the generated execution evidence](generated-run-evidence.md).

Gemini Live has received typed input and synthetic speech and returned native PCM
audio and transcripts. An earlier authored-candidate run also completed typed
approval through its tools. Positive spoken approval was safely denied when the
provider omitted the transcription completion flag. On this verified Gemini 3.8
path, a spoken apply request can open review; an explicit UI confirmation or
incident-bound typed command applies the repair. The relay supports finalized,
bound affirmative speech too, but direct spoken approval has not been observed in
provider checks. **No human microphone was tested.** See
[the audio and approval evidence](verification-evidence.md) for the exact scope.

Public source: [hashkanna/first-response](https://github.com/hashkanna/first-response).

## Before recording

1. Install dependencies in the project `.venv` and web workspace as described in
   the root README. Run the project's checks once after final integration.
2. Select `VERIFICATION_BACKEND=modal`, `INVESTIGATOR_BACKEND=gemini` and
   `REPAIR_BACKEND=gemini` for the generated-repair demo. Prepare the image with
   `.venv/bin/python -m scripts.check_modal --prepare-only`. The two complete cloud
   checks have already succeeded; repeating them is optional and consumes credits.
3. Confirm actual Gemini diagnosis/generation requests succeed; a `/health`
   configured flag is not proof. If only Live is unavailable, use hub text controls
   with the generated repair flow. If Gemini generation is unavailable, explicitly
   choose the authored fallback described below and disclose that change.
4. Start the hub on loopback and open the web app. Choose **Live system**, confirm
   **Hub connected**, then open **Operator** and **Reset system**.
5. Connect Gemini Live before injecting the fault. The terminal button connects
   typed input and spoken model output without requesting microphone access.
   Rehearse human microphone/headset use separately with a harmless status question
   before relying on it in a live presentation. Keep text and the review button available.
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
| 0:42–1:03 | Three generated candidate cards and results | “Gemini proposes three bounded source edits. Each gets its own network-disabled Modal sandbox, with the same failing reproduction and unchanged regression suite.” |
| 1:03–1:22 | Actual candidate outcomes | Open real logs. If a candidate failed, explain its actual regression; otherwise acknowledge that several repairs passed. A successful candidate has 25 checks: one reproduction plus 24 regression tests. Read the measured timer only after it has stopped. |
| 1:22–1:43 | Verified diff, explicit approval, resolved state | A spoken “Apply the verified fix” requests review. Inspect the diff, then click **Approve & apply repair**, or send the complete typed command. Explain that generated code is tested and probed again in Modal after approval. |
| 1:43–2:00 | Patch artifact and architecture | “The deliverable is a verified patch and an evidence trail. Today this covers two rehearsed toy-shop faults. The pattern is evidence, isolation, tests, then human approval.” |

These timestamps are an editing plan, not simulated runtime guarantees. If tests
finish early, inspect their evidence. If they take longer, trim narration or edit
the recording with a clearly disclosed cut. Never slow or replace a live number to
make the timing look better.

## Spoken and typed commands

- “What is happening with checkout?” — the current factual milestone.
- “Explain the cause.” — the confirmed cause, once available.
- “What was tried?” — actual candidate outcomes and test counts.
- Spoken “Apply the verified fix.” — requests patch review on the observed Gemini
  3.8 path, which does not supply transcription finality.
- Typed “Apply the verified fix.” — explicit authorization after verification,
  bound to the incident shown when the command was sent.
- **Approve & apply repair** — confirms the candidate and incident shown in the
  review dialog. Reset closes the dialog and invalidates the old request.

A disconnected Live session can be replaced by the text input. Identify this as
typed control; browser speech recognition or synthetic narration is not evidence
that Gemini Live ran. Missing transcription finality is a known provider behavior,
not permission to infer consent from a pause or model response completion. Use
the visible review confirmation or complete typed command.

## Reset and second fault

Return to **Operator**, press **Reset system**, and wait for the reset confirmation.
Choose the other fault and start a new investigation. Reset cancels the active job
and invalidates earlier incident state. Do not approve a candidate from a previous
incident. The hub rejects a second fault while an unresolved incident is active.

## Failure and backup plan

| Situation | Honest response |
| --- | --- |
| No candidate passes | Show the failed checks. Explain that no fix is offered and the shop remains broken. |
| Gemini unavailable | Show the provider error. For an explicitly disclosed fallback, restart with authored repairs and local diagnosis, keeping Modal verification if available. |
| Modal unavailable | Show the provider error. Stop or use a recording of an actual run. A local fallback must explicitly select authored repairs; generated repairs never execute locally. |
| Need a predictable visual walkthrough | Switch to **Rehearsal** and say it is a 45-second replay of illustrative events with no live tests or changes. |
| Approval or post-apply check fails | Show the error and restored runtime state. Do not claim resolution or a created PR. |

Keep a backup two-minute recording of a successful actual run. Rehearsal JSON is a
separate UI aid, not a substitute for cloud execution evidence.

## Five-minute finalist expansion

Use the same two-minute incident story, then spend one minute on the architecture,
one minute on a rejected repair and the approval boundary, and one minute on the
second fault or judge questions. The two-minute submission video remains its own
artifact; a five-minute finalist slot does not change that requirement.
