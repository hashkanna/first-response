# Hub API

Default origin: `http://127.0.0.1:8000`. Interactive OpenAPI: `/docs`.
`WAR_ROOM_PORT=8001 ./scripts/dev.sh` moves the hub to port 8001 and points the
launched frontend at it; all HTTP and WebSocket endpoints use that same port.

| Method | Path | Contract |
|---|---|---|
| GET | `/health` | Current mode, verification backend, model names, configured capabilities. Configuration is not proof of provider availability. |
| GET | `/status` | Current incident ID, stage, active fault, accumulated events, approval artifact metadata. |
| WS | `/ws` | Receive-only event stream. Sends `{type:"reset"}` then full incident replay on connection, followed by new bare `IncidentUpdate` objects and voice-cue envelopes. |
| POST | `/faults/bad_config/apply` | Apply timeout fault to runtime copy and start investigation; 409 while an unresolved incident exists. |
| POST | `/faults/null_error/apply` | Apply optional-coupon fault and start investigation. |
| POST | `/faults/reset` | Cancel investigation, restore clean runtime shop, clear incident, broadcast reset. |
| POST | `/say` | `{text, incident_id?}`; factual text commands. `incident_id` is mandatory and must match for approval phrases. |
| POST | `/approve` | `{candidate_id, incident_id}`; both must match a currently verified candidate. Repeated approval is idempotent. |
| GET | `/artifacts/{filename}` | Download approved `.patch`; only generated filenames are accepted. |
| WS | `/live` | Gemini relay; binary PCM16 input/output, incident-bound typed commands, transcripts, tool notices and non-executing review requests. |
| GET / POST | `/setup` | Development-only ephemeral key configuration when explicitly enabled; loopback and same-origin CSRF checks. |

The primary event schema is [core/contracts.py](../core/contracts.py), mirrored in [TypeScript](../web/src/lib/contracts.ts). Every event includes `incident_id`, `stage`, `at`, `message`, and optional evidence/root-cause/candidate/result data. Arrays are incremental; the frontend merges by entity ID. Events for retired incidents cannot overwrite the current incident. An early or inconsistent success message cannot mark a repair verified.

```json
{
  "incident_id": "inc-example",
  "stage": "verifying",
  "at": "2026-09-19T15:00:00Z",
  "message": "Checking candidate repairs.",
  "evidence": [], "candidates": [], "results": []
}
```

Voice cues use `{type:"voice_cue", scheduling:"INTERRUPT"|"WHEN_IDLE"|"SILENT", facts:string}`. The Live client cannot inject incident updates, tools, server credentials, or approval flags. Background cues never authorize changes; the hub independently validates the current incident, selected repair and test results.

## Live control and approval

Browser text uses `{type:"text", text:string, incident_id:string|null}`. Informational
questions remain available without an incident ID. An approval phrase arms a grant
only when the supplied ID matches the current incident and verified repairs exist.
The browser captures this ID when it sends the command. The grant is recent,
bound to already verified candidates and consumed once by a validated tool call.

Speech input is PCM16 mono at 16 kHz; model output is PCM16 at 24 kHz. Other browser
controls are `{type:"audio_stream_end"}` and `{type:"disconnect"}`. The server
captures approval context at actual audio activity start. New speech revokes an
older grant, and reset invalidates the captured speech context.

The observed Gemini 3.8 provider omits the optional transcript completion flag.
Missing finality cannot grant spoken approval; neither local silence nor model
`turn_complete` substitutes for it. An affirmative spoken request may instead emit:

```json
{
  "type": "review_requested",
  "request_id": "unique-request-id",
  "incident_id": "inc-example",
  "candidate_id": "verified-candidate-id"
}
```

This event opens review only. The UI requires the same current incident and a
verified candidate before showing the diff. The final button sends `/approve`
with the incident and candidate captured by that dialog; reset closes it. A
complete typed “Apply the verified fix” also confirms approval for this fallback.
Separately, the relay can arm a grant from affirmative speech when
`input_transcription.finished=True` and the captured incident/candidate context
still matches. That direct path is tested offline but has not been observed in
the Gemini 3.8 provider checks.
Provider input transcription and model response completion can arrive out of
order, so negative continuations remain in the same audio utterance.

The local `/say` handler recognizes status, cause, evidence, repairs/tests, start/investigate, and a narrow set of explicit approval phrases. For unrestricted conversation, connect Gemini Live; typed input then uses the same model session as voice.

Errors use normal HTTP status codes and a `detail` field. WebSocket reconnect is capped exponential backoff. The UI displays network/provider errors and never substitutes recorded fixtures for a disconnected live feed.

`FixCandidate.origin` is `authored` or `gemini`. Generated candidates include a
64-character `snapshot_sha` binding the complete Python source and tests. Approval
checks this digest and the exact displayed diff again. `/health` reports
`repair_backend` and `repair_model`; generated repairs require Modal execution.
