# Gemini Live relay

The browser streams microphone PCM to `ws://localhost:8000/live`. The server
opens a real Gemini Live session using `google-genai`; credentials never enter
the browser. Audio is 16-bit little-endian PCM, mono, 16 kHz input and 24 kHz
output. The AudioWorklet resamples the browser microphone and sends 20 ms frames.
Playback buffers are cleared on interruption. Audio is not saved to disk.

The relay marks speech boundaries explicitly with Gemini's documented
`activity_start`/`activity_end` protocol. A small PCM energy detector retains a
160 ms prefix, starts after 40 ms of speech, and ends after 500 ms of silence.
`GEMINI_LIVE_VAD_RMS` adjusts the default 250/32768 energy threshold. This avoids
relying on provider automatic VAD, which accepted connections but produced no
transcription during our first synthetic-input rehearsals. Browser echo/noise
controls remain enabled. A headset and real-room microphone check are still
required; synthetic audio does not establish microphone usability.

Install the project's cloud dependencies and configure one server-side option:

```sh
export GEMINI_API_KEY=...   # GOOGLE_API_KEY is also supported
export GEMINI_LIVE_MODEL=gemini-3.8-live
```

For a temporary local demo, start the server bound to `127.0.0.1` with
`WAR_ROOM_ENABLE_SETUP=1` and open `http://127.0.0.1:8000/setup`. Its password
form accepts an **existing** key and stores it in the running process environment
only. It does not create credentials, echo them, log request bodies, or persist
them. The endpoint is disabled by default and checks loopback client/server/host,
exact same-origin Origin and Referer headers, and a one-use CSRF nonce. The key
is lost on restart. For ordinary development, use the server environment or the
project's ignored `.env` file and leave this setup endpoint disabled.

For a Google Cloud project with Application Default Credentials:

```sh
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=global
```

Model availability, project permissions, billing and quota are checked by Google
when the session connects. A configured `/health` capability does not assert that
credentials have been tested. Missing credentials disable Live without affecting
the local incident hub. The default maximum session length is 900 seconds,
overridable through `GEMINI_LIVE_MAX_SECONDS`; two concurrent sessions are allowed.

`create_live_router(LiveAdapter(...))` connects four validated functions to the
actual hub: `start_investigation`, `get_status`, `explain`, and `approve_fix`.
Investigations remain background tasks. The approval function requires a recent,
explicit operator confirmation captured from typed input or finalized input transcription,
bound to the current incident and its verified candidates. Background facts never
arm approval. The manager enforces verification again before applying a change.

**Current provider limitation:** the real Gemini 3.8 Live approval rehearsal on
19 September returned the complete spoken command but omitted the SDK's optional
`finished` flag. The relay correctly left the repair unapproved. In the verified
fallback, an affirmative spoken request can open patch review; use typed
“Apply the verified fix” or confirm the review button to apply it. The relay also
supports finalized, incident-bound affirmative speech (`finished=True`), covered
by offline tests but not observed in provider checks.
Spoken questions, transcription, native replies and interruption
are verified; positive spoken approval is not established. We do not treat a
model `turn_complete` as a final user transcript: Google's WebSocket reference
explicitly states that input transcription has no guaranteed ordering relative to
other messages. The separate transcription model's finalized-segment behavior is
not assumed for this conversational model.

Hub `INTERRUPT` facts clear queued browser audio and use the documented Gemini
3.8 `send_client_content(..., turn_complete=True)` interrupt behavior.
`WHEN_IDLE` facts wait for model completion; `SILENT` updates enter context without
requesting a spoken turn. These are client-content updates, not fabricated tool
responses. Actual tool calls receive their matching function-call IDs.

The UI can connect with `{microphone: false}` for a typed conversation with spoken
Gemini replies. Microphone denial also leaves this text path available. The relay
accepts no browser-supplied tools, approval flags, credentials, or injected cues.

Run offline protocol and approval tests:

```sh
python -m pytest live -q
```

## Recorded provider rehearsal

On **19 September 2026, 15:27:45–15:28:08 UTC**, the real `gemini-3.8-live`
relay transcribed two synthetic spoken commands exactly, returned **317,762 bytes
of native 24 kHz PCM** during the speech session, and emitted an interruption
when the second command arrived during its reply. A fresh connection returned
another **144,960 bytes** of native audio. The incident remained `fix_verified`
with no approval before and after the check. All eight recorded checks passed.

The rehearsal used macOS `say` converted to 16 kHz PCM and streamed in real time;
it did not use a person's microphone. It establishes real provider speech input,
transcription, audio output, interruption and reconnect, but does not establish
headset acoustics, perceived playback or positive spoken approval. The relay arms
spoken approval only on the SDK's final transcription flag, which this receipt
does not retain. See the [full execution summary](../docs/verification-evidence.md#synthetic-speech-input-interruption-and-reconnect)
for commands, timings and the evidence boundary.

To repeat the bounded check against an already configured local hub:

```sh
python scripts/check_live_audio.py --hub http://127.0.0.1:8001 --allow-live
```

This makes real provider calls and writes synthetic inputs plus a non-secret
receipt under ignored `.runtime/voice-checks/`. It reads no credentials and sends
only status questions and negative instructions; it does not approve a repair.

An explicitly requested approval rehearsal uses the separate mode below. It
**applies a real repair** to the toy shop and requires a currently verified
recommendation with a source snapshot. Run it without concurrent operator actions.
The script captures the incident, candidate and snapshot, rechecks them before
speaking, watches for drift, and verifies the same repair reaches `resolved`.
The receipt retains the provider's actual final-transcription flag; the relay's
approval gate is unchanged.

```sh
python scripts/check_live_audio.py --hub http://127.0.0.1:8001 --allow-live --approve-verified
```

The current Gemini 3.8 provider omits the final transcript marker. To rehearse
its safe speech-to-review fallback instead, use:

```sh
python scripts/check_live_audio.py --hub http://127.0.0.1:8001 --allow-live --request-review
```

This sends the same synthetic affirmative request and expects a `review_requested`
event for the captured verified incident and candidate, plus actual transcription
and at least 4,800 bytes (100 ms) of native audio after the request. The wait also
requires an uninterrupted assistant response to complete after that request;
the preceding function-call completion does not count. Success requires unchanged incident state and no approval.
It does not click the review dialog or send typed confirmation. This is a test of
the current provider's conservative behavior, not evidence of direct spoken
approval; its checked receipt is stored under `.runtime/voice-checks/`.

Current official references verified for this implementation:

- [Google GenAI SDK Live quickstart](https://ai.google.dev/gemini-api/docs/live-api/get-started-sdk)
- [Gemini 3.8 Live model and migration notes](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live)
- [Audio formats and transcription](https://ai.google.dev/gemini-api/docs/live-api/capabilities)
- [Manual Live tool responses](https://ai.google.dev/gemini-api/docs/live-api/tools)
