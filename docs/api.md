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
| WS | `/live` | Gemini relay; binary PCM16 input/output, JSON controls, streamed transcripts and tool notices. |
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

Voice cues use `{type:"voice_cue", scheduling:"INTERRUPT"|"WHEN_IDLE"|"SILENT", facts:string}`. The Live client cannot inject incident updates, tools, server credentials, or approval flags. Tool approval requires a recent explicit operator utterance bound to the same incident; the hub independently validates all test results.

The local `/say` handler recognizes status, cause, evidence, repairs/tests, start/investigate, and a narrow set of explicit approval phrases. For unrestricted conversation, connect Gemini Live; typed input then uses the same model session as voice.

Errors use normal HTTP status codes and a `detail` field. WebSocket reconnect is capped exponential backoff. The UI displays network/provider errors and never substitutes recorded fixtures for a disconnected live feed.

`FixCandidate.origin` is `authored` or `gemini`. Generated candidates include a
64-character `snapshot_sha` binding the complete Python source and tests. Approval
checks this digest and the exact displayed diff again. `/health` reports
`repair_backend` and `repair_model`; generated repairs require Modal execution.
