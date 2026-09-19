# Verified execution evidence

## Initial isolated Modal checks

These results came from actual cloud executions on 19 September 2026, using the
project interpreter, the authenticated Modal SDK and pytest 8.4.2. They are
independent of the browser's recorded rehearsal fixtures.

The first verification set used **eight short-lived sandboxes**: one broken-code
reproduction and three concurrent candidate jobs for each of two faults. Every
candidate executed one reproduction plus 24 regression cases. Both faulty
reproductions failed as expected; each scenario produced exactly one passing
repair. Termination and detachment completed for every job.

| Fault | Candidate | Reproduction | Suite | Checks | Failures |
| --- | --- | --- | --- | --- | --- |
| Payment timeout | `timeout-30ms` | Failed | Failed | 25 | 7 |
| Payment timeout | `timeout-unbounded` | Passed | Failed | 25 | 2 |
| Payment timeout | `timeout-restore` | Passed | Passed | 25 | 0 |
| Missing coupon | `coupon-empty-code` | Failed | Failed | 25 | 2 |
| Missing coupon | `coupon-disable` | Passed | Failed | 25 | 2 |
| Missing coupon | `coupon-guard` | Passed | Passed | 25 | 0 |

The payment reproduction raised `PaymentTimeout` because the configured deadline
was 3 ms and the toy provider required 80 ms. The coupon reproduction raised
`AttributeError` while reading `cart.coupon.code` when `coupon` was absent. The
winning changes restored the 3,000 ms deadline and the explicit `None` guard.

The coupon run completed at **14:37:01 UTC / 15:37:01 London**. Its full non-secret
receipt is `.runtime/modal-checks/null_error.json`, including sandbox IDs, exact
pytest output, source digest and measured candidate durations (2.027–2.508 seconds
for that warmed verification batch). These durations describe those individual
jobs, not a guaranteed end-to-end incident response time.

The payment summary receipt was written at **14:37:22 UTC / 15:37:22 London** after
its successful run. That is the receipt-writing timestamp, not the exact cloud
completion timestamp. `.runtime/modal-checks/bad_config.json` contains the observed
candidate outcomes and sandbox IDs; the full output was inspected in the build
session. No completion timestamp is invented for that run.

Raw receipts are kept under ignored `.runtime/` and are not automatically uploaded
or committed. This checked-in summary contains no credentials, private account
identifiers, or customer data. If a judge requests proof, show the actual local
receipt and the corresponding authenticated Modal job records.

These eight initial jobs established the verification runner for the two authored
faults. The separate integrated browser result below establishes additional paths;
the initial jobs alone are not evidence for those integrations.

## Browser, Gemini diagnosis, Live approval and Modal

An actual browser run on 19 September 2026 completed incident
`inc-0201b294375f` with the payment-timeout fault. The following facts were observed
in the running UI/Live session and checked against the runtime diagnosis receipt
and generated patch:

| Step | Observed evidence |
| --- | --- |
| Typed Gemini diagnosis | The then-current `.runtime/investigator.json` recorded Pydantic AI with `gemini-3.8-flash`, one request, 2,892 input tokens and 201 output tokens |
| Diagnosis timestamp | `2026-09-19T14:53:38.516072+00:00` (15:53:38 London) |
| Time to verified fix | The UI displayed **8.6 seconds** for this run; this is one observed result, not a latency guarantee |
| Competing repairs | Three actual Modal candidate jobs; `timeout-restore` passed the reproduction and all regression checks, 25 total |
| Gemini Live | A real connected session with typed input and microphone disabled received model audio, milestone transcripts and a factual response |
| Human approval | At **15:54:28 London**, the operator typed “Apply the verified fix” into that same Live session |
| Applied repair | The model's validated tool call triggered real Modal post-apply verification: 25 passing checks and 12 healthy checkout probes |
| Resolution | The browser showed the incident resolved at **15:54:32 London** |
| Artifact | `.runtime/artifacts/inc-0201b294375f-timeout-restore.patch` exists and changes `PAYMENT_TIMEOUT_MS = 3` back to `3000` |

The typed-input Live session is real provider execution, not the local `/say`
command matcher or recorded rehearsal. This run did **not** test a human speaking
through the microphone. The diagnosis receipt holds the latest incident and was
subsequently replaced by the second run below; the first run's observed values
are preserved in this summary.

## Second complete browser run and native audio bytes

The missing-coupon scenario also completed through the actual cloud UI as
`inc-b9accbd6b783`. Its alert appeared at **15:57:42 London**. The diagnosis receipt
records Pydantic AI using `gemini-3.8-flash` at
`2026-09-19T14:57:42.497379+00:00`, with **one request, 2,991 input tokens and
206 output tokens**. The UI recorded **7.4 seconds** from alert to verified fix.

Three real Modal candidates each ran 25 checks. `coupon-guard` passed all of them;
`coupon-empty-code` and `coupon-disable` each reported two failures. The operator
inspected the actual source diff and test logs, then used the explicit review
modal to approve the change at approximately **15:58:18 London**. The incident
resolved at **15:58:21 London** after another 25 passing post-apply checks and
12 healthy checkout probes.

The generated `.runtime/artifacts/inc-b9accbd6b783-coupon-guard.patch` exists and
restores the explicit `None` guard without removing valid coupon behavior. The
connected Gemini Live session answered a typed question about rejected repairs
through its tools and delivered spoken milestones with transcripts.

Browser instrumentation (`data-audio-bytes`) recorded **1,077,604 native PCM bytes
received** in the connected session. This establishes actual model audio reaching
the browser in addition to transcript text. **No microphone was used**, so these
runs do not establish human speech capture, room acoustics or speech recognition
quality. The 8.6- and 7.4-second observations are individual runs, not a benchmark
or promised response time.

The tested system remains a local toy shop with authored repair strategies. It
does not establish production traffic, Logfire ingestion, arbitrary repair
generation or a remote GitHub pull request.

## Synthetic speech input, interruption and reconnect

A separate real-provider rehearsal ran on **19 September 2026 from
15:27:45.968 UTC to 15:28:08.593 UTC** (16:27:45–16:28:08 London), using
`gemini-3.8-live` through the running local relay at `127.0.0.1:8001`. The command
was:

```sh
.venv/bin/python scripts/check_live_audio.py --hub http://127.0.0.1:8001 --allow-live
```

The script used existing server credentials without reading them. It synthesized
two benign commands with macOS `say`, converted them to mono 16 kHz PCM16
little-endian with FFmpeg, and streamed 20 ms frames at real-time speed. It did
not use a human microphone, a typed primer, a new fault or an approval command.
The exact local receipt is
`.runtime/voice-checks/20260919T152745Z/receipt.json`.

| Observation | Recorded evidence |
| --- | --- |
| First spoken command | “What is the status of checkout?” — 58,774 PCM bytes, 1.837 seconds; provider input transcription matched exactly |
| Second spoken command | “Stop. Do not change anything. Give me only one sentence about checkout.” — 156,876 PCM bytes, 4.902 seconds; provider input transcription matched exactly |
| Audio framing | Relay acknowledged 254,050 received bytes including leading/trailing silence, 240,000 forwarded bytes and two explicit speech starts/ends |
| Speech session | 16.377 seconds; **317,762 native output PCM bytes**, 22 chunks at 24 kHz; no session error |
| Barge-in | One provider interruption at `15:27:51.964627 UTC`, during the second command, approximately 142 ms after first response audio reached the test client |
| Typed negative instruction | “Do not apply or approve any changes. Just tell me the current checkout status.” completed without approval |
| Final first-session response | “Two candidates have been verified for checkout, and approval is required to apply the recommended fix.” |
| Fresh connection | A read-only typed status question returned **144,960 native PCM bytes**, eight chunks at 24 kHz, in a 4.469-second session without errors |
| Reconnected response | “The fix has been verified and is awaiting approval.” |
| State before and after | Incident `inc-fdfec64eadbf`, fault `bad_config`, stage `fix_verified`, approval `null`; all remained unchanged |

All eight receipt checks passed: synthetic speech transcription, native audio for
spoken input, acknowledged input frames, interruption, negative instruction
without approval, reconnected audio, unchanged incident/approval state and no
session errors. The original synthetic PCM files and their SHA-256 digests remain
beside the ignored receipt. The relay's explicit activity boundaries corrected
the earlier rehearsal failure in which provider automatic activity detection
produced no input transcription; the passing run used `server_vad` and no primer.

The second spoken transcription arrived just after the script sent its typed
negative instruction. The final spoken answer therefore followed those
overlapping inputs; this run does not establish an isolated answer to the second
spoken command. The interruption itself and both exact input transcriptions are
independently present in the receipt.

This evidence establishes synthetic speech reaching the real provider and native
audio returning through the relay. It does **not** establish human microphone
capture, room acoustics, headset echo handling, perceived speaker playback or
positive spoken approval. The installed `google-genai` 2.24.0 SDK exposes an
optional `Transcription.finished` flag, and the relay requires it before arming
approval from speech. The saved browser-facing transcript envelopes omit that
flag, so this receipt cannot confirm its actual delivery. Offline tests cover
the rejection of a partial “Yes” before transcription finishes.

After the successful run, **19 focused Live tests passed** with the locked local
dependencies using `.venv/bin/python -m pytest live -q`. They cover the relay,
approval gates, local credential setup and PCM activity boundaries. One upstream
Starlette/AnyIO deprecation warning was emitted; no test failed.
