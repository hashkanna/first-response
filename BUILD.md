# Voice Incident War-Room — implementation doc

Written 15:15, Saturday 19 September 2026. Opt-in deadline 19:00. Demo 20:00, about 3 minutes.
That leaves about 3 hours 45 minutes. The plan below targets two working fault types, with two more as stretch.

## 1. What we're building

You talk to an on-call agent by voice while it investigates a broken system in the background. It interrupts you when it finds the cause, and it comes back with a fix it has already tested in isolation.

**What the user experiences**

1. An alert fires: checkout is failing.
2. They say, "What's going on with checkout?"
3. The agent answers and keeps talking while an investigation runs in the background.
4. It cuts in: "Found it. The 14:02 deploy changed the payment timeout from 3000 to 3 milliseconds. I tried three fixes in isolation and one passes every test. Want the pull request?"
5. They say yes. It opens the pull request.

**Design decision that keeps this reliable:** Gemini Live is only the voice. It does not run the investigation step by step. It starts one background investigation and receives milestone updates. The investigator is a separate Pydantic AI agent with typed steps. This keeps the voice session simple and the investigation testable without audio.

## 2. Architecture

```
  Browser (mic, speaker, war-room UI)
      │  audio both ways                      ▲ incident events (WebSocket)
      ▼                                        │
  Gemini Live session  ──tool calls──>  Hub (FastAPI)  <──IncidentUpdate──  Investigator
      ▲                                        │                              (Pydantic AI agent,
      └──────── cues (INTERRUPT / WHEN_IDLE) ──┘                               Gemini Pro via Gateway)
                                                                                   │
                        ┌──────────────────────────────┬──────────────────────────┤
                        ▼                              ▼                          ▼
                 Logfire query              git log / diff / files         Modal Sandboxes
             (traces of the broken app)        (the shop repo)        (reproduce, test fixes in parallel)
                        ▲
                        │ traces
                  Toy shop app  <── load generator, fault switches
```

| Part | Job | Tech |
|---|---|---|
| Toy shop | The system that breaks. Small, real, instrumented | FastAPI, pytest, Logfire |
| Fault switches | Apply a rehearsed bug as a real code change ("bad deploy") | Patch files + git commit + reload |
| Load generator | Steady traffic so traces and alerts exist | Small async script |
| Investigator | Finds the cause, writes a reproducing test, proposes fixes, verifies them | Pydantic AI, Gemini Pro through the Pydantic AI Gateway |
| Sandbox harness | Runs the test suite against each candidate fix in isolation, in parallel | Modal Sandboxes |
| Gate | Two quick typed decisions: is this alert worth paging, is this fix safe to auto-apply | Jev, with a rules fallback behind the same interface |
| Live session | The voice. Starts investigations, reports milestones, takes approvals | Gemini Live (`gemini-3.8-live`) |
| Hub | Holds incident state, fans events to the UI and cues to Live | FastAPI + WebSocket |
| War-room UI | Timeline, evidence cards, candidate fixes with live test status, timer, operator panel | Any web stack |

## 3. Repo layout

One folder per builder, so nothing collides.

```
/core      contracts.py, hub.py, gate.py                 (Claude, this chat)
/agent     investigator.py, tools.py, prompts.py          (Claude, this chat)
/shop      app/, tests/, faults/, loadgen.py              (Devin)
/modal     sandbox.py, image.py                           (Claude Code, terminal)
/live      session.py, tools.py                           (Claude Code, terminal)
/web       war-room UI                                    (Codex)
.env       keys. In .gitignore before the first commit.
```

## 4. Contracts

Create `core/contracts.py` from this. Everyone codes against it. Pydantic v2.

```python
from __future__ import annotations
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field

Service = Literal["catalog", "cart", "checkout", "payments"]
FaultKind = Literal["bad_config", "null_error", "slow_query", "type_error"]

class Alert(BaseModel):
    alert_id: str
    service: Service
    signal: Literal["error_rate", "latency_p95"]
    value: float
    threshold: float
    started_at: datetime

class Evidence(BaseModel):
    evidence_id: str
    kind: Literal["trace", "exception", "deploy_diff", "code", "metric"]
    summary: str                      # one sentence, facts only
    detail: str                       # stack trace excerpt, diff hunk, SQL row...
    source_ref: Optional[str] = None  # trace id, commit sha, file:line

class RootCause(BaseModel):
    service: Service
    file: str
    line: Optional[int] = None
    commit: Optional[str] = None
    explanation: str                  # two sentences max
    evidence_ids: list[str]
    confidence: float = Field(ge=0, le=1)

class ReproTest(BaseModel):
    path: str                         # tests/test_repro_<incident>.py
    code: str
    fails_on_current: Optional[bool] = None   # filled in by the sandbox

class FixCandidate(BaseModel):
    candidate_id: str
    title: str
    rationale: str
    patch: str                        # unified diff against the shop repo
    files_touched: list[str]

class VerifyResult(BaseModel):
    candidate_id: str
    applied: bool
    repro_passed: bool
    suite_passed: bool
    tests_run: int
    tests_failed: int
    duration_s: float
    log_tail: str

class FixRisk(BaseModel):
    action: Literal["auto_apply", "needs_human", "reject"]
    confidence: float = Field(ge=0, le=1)
    source: Literal["jev", "fallback"]

Stage = Literal["alerted", "investigating", "cause_found", "reproduced",
                "fixes_proposed", "verifying", "fix_verified", "no_fix_found",
                "pr_opened", "resolved"]

class IncidentUpdate(BaseModel):
    """Every state change. The hub broadcasts these to the UI and turns some into voice cues."""
    incident_id: str
    stage: Stage
    at: datetime
    message: str                      # short, factual
    evidence: list[Evidence] = []
    root_cause: Optional[RootCause] = None
    candidates: list[FixCandidate] = []
    results: list[VerifyResult] = []
    pr_url: Optional[str] = None

class VoiceCue(BaseModel):
    scheduling: Literal["INTERRUPT", "WHEN_IDLE", "SILENT"]
    facts: str                        # what the voice may say. Facts only, no speculation.

# ---- Gemini Live tool arguments (Live has no structured output; typed data comes in here) ----
class StartInvestigationArgs(BaseModel):
    service: Optional[Service] = None         # None = investigate the active alert

class ApproveFixArgs(BaseModel):
    candidate_id: Optional[str] = None        # None = the verified one

class ExplainArgs(BaseModel):
    topic: Literal["cause", "fix", "evidence", "what_was_tried"]
```

**Stage → voice cue mapping (in the hub)**

| Stage | Scheduling | Example facts |
|---|---|---|
| `alerted` | `INTERRUPT` | "Checkout error rate is 38%, threshold 5%, started 40 seconds ago." |
| `investigating` | `SILENT` | — |
| `cause_found` | `INTERRUPT` | "Cause: commit a1b2c3 changed PAYMENT_TIMEOUT_MS from 3000 to 3 in config.py." |
| `reproduced` | `WHEN_IDLE` | "I reproduced it with a failing test in a sandbox." |
| `verifying` | `SILENT` | — |
| `fix_verified` | `INTERRUPT` | "Three fixes tested. One passes the reproducing test and all 24 suite tests. Want the pull request?" |
| `no_fix_found` | `INTERRUPT` | "None of my three fixes passed. Here's what I know so far." |
| `pr_opened` | `WHEN_IDLE` | "Pull request is open." |

## 5. The toy shop (`/shop`)

Small on purpose. One FastAPI app, four modules named as services: `catalog`, `cart`, `checkout`, `payments`. SQLite. About 20–25 pytest tests that all pass on the clean code. Its own git repo (or a subfolder treated as one) so "deploys" are commits.

- Instrument with Logfire: `logfire.configure()`, `logfire.instrument_fastapi(app)`, plus a span per service call with the service name as an attribute.
- `loadgen.py`: steady mixed traffic (browse, add to cart, checkout), about 5 requests per second, so traces and error rates exist within seconds of a fault.
- An alert checker: every 5 seconds compute error rate and p95 latency per service over the last 30 seconds, and post an `Alert` to the hub when a threshold is crossed.

**Faults.** Each is a patch file in `/shop/faults/` plus a script that applies it, commits it with a realistic message ("tune payment timeout"), and lets uvicorn reload. A reset script reverts to the clean commit.

| Priority | Fault | Bug | What the trace shows | Correct fix |
|---|---|---|---|---|
| 1 | `bad_config` | `PAYMENT_TIMEOUT_MS = 3` (was 3000) in `config.py` | Timeout exceptions in `payments`, started right after a commit touching `config.py` | Restore 3000 |
| 2 | `null_error` | `checkout` reads `cart.coupon.code` without a None check | `AttributeError: 'NoneType'...` at `checkout.py:NN`, only for carts with no coupon | Guard for None |
| 3 (stretch) | `type_error` | A "refactor" returns price as a string | `TypeError` in total calculation | Cast / fix the serializer |
| 4 (stretch) | `slow_query` | N+1 query in catalog listing | No errors; p95 latency alert; many repeated spans | Batch the query. Needs a timing test to verify |

Build and rehearse faults 1 and 2 first. They are the demo.

## 6. The investigator (`/agent`)

A Pydantic AI agent on Gemini Pro, called through the Pydantic AI Gateway (`gateway/google-cloud:...`, with a fallback provider configured). It runs as one background task per incident and posts an `IncidentUpdate` to the hub after every step.

**Steps, in order**

1. `get_alert()` → the active `Alert`.
2. `query_traces(service, since)` → recent failing spans and exceptions from Logfire → `Evidence`.
3. `recent_deploys(since)` → `git log` and `git diff` for commits near the alert start → `Evidence`.
4. `read_file(path, around_line)` → code around the failing line → `Evidence`.
5. Produce a `RootCause` (typed output, validated; retry on validation error). Post `cause_found`.
6. `write_repro_test()` → a `ReproTest` that should fail on the current code. Verify in a sandbox that it does fail. Post `reproduced`. If it passes on the broken code, regenerate once, then fall back to the pre-written repro test for that fault.
7. `propose_fixes(k=3)` → three different `FixCandidate` diffs. Ask for genuinely different approaches (revert the commit, minimal guard, config validation).
8. `verify_all(candidates, repro)` → Modal Sandboxes in parallel → `VerifyResult` each. Post `verifying`, then `fix_verified` or `no_fix_found`.
9. Gate: `assess_fix(candidate, result)` → `FixRisk`. Only a verified fix is ever offered.
10. On approval: `open_pr(candidate)` → `pr_url`. Post `pr_opened`.

**Reading Logfire.** Use the Logfire query API with a read token (SQL over the records table; the SDK has an async query client). Query for spans in the last few minutes where the service attribute matches and `is_exception` is true, and pull the exception type, message, stack trace and trace id. Check the exact client and column names in the current Logfire docs before writing the query. Ingestion lags by a few seconds, so poll up to three times.

*De-risk:* also write every span to a local JSONL file from a span processor. If the query API costs more than 30 minutes, read evidence from the file and still show the Logfire UI in the demo. Say so if asked.

**Rules that keep it honest**

- The voice only says facts that exist as `Evidence` or `VerifyResult`. No guesses about causes before `cause_found`.
- A fix is never described as working unless `repro_passed and suite_passed`.
- If nothing passes, say so. That outcome is a legitimate demo moment.
- Bulk LLM work never goes to the Gemini API. This design makes about 6–10 Gemini Pro calls per incident, which is normal usage.

## 7. Sandbox harness (`/modal`)

`verify(candidate: FixCandidate, repro: ReproTest, base_commit: str) -> VerifyResult`

1. Image built once: Python, the shop's requirements, git, pytest. Build and warm it before the demo.
2. Create a Modal Sandbox from the image. Put the shop repo in at `base_commit` (bake a tarball into the image, or mount it from a Volume).
3. Write the repro test file. Apply the candidate patch with `git apply`. If it does not apply, return `applied=False`.
4. Run the repro test alone, then the whole suite, with a timeout (60 s). Capture the exit codes and the last 40 lines of output.
5. Terminate the sandbox. Return the `VerifyResult`.

Run the three candidates at once with `asyncio.gather`. Also expose `check_repro_fails(repro, base_commit)` for step 6 of the investigator.

Sandboxes have no network access and a hard timeout, because they run model-written code.

Install Modal's skills for your coding agent first (`modal skills install --global --claude`, or without `--claude` for Codex) so it has the current Sandbox API.

## 8. Live session (`/live`)

- Model `gemini-3.8-live`. Audio in and out. Function calling is asynchronous by default on this model.
- System prompt: you are an on-call incident commander. Be brief. Only state facts you are given. Never guess a cause. When a cue arrives, say it plainly. Ask for approval before any change.
- Tools (arguments validated with the Pydantic models above; on a validation error return the error text so the model asks again):
  - `start_investigation(service?)` → returns at once with "started". The work continues in the background.
  - `get_status()` → current stage and the latest facts.
  - `explain(topic)` → the relevant evidence, in words.
  - `approve_fix(candidate_id?)` → triggers the pull request.
- Cues from the hub are injected into the session as tool responses or client content with the scheduling from the table in section 4. Check the exact field names in the Live API tools guide.
- Tool responses are handled manually in client code. Live does not do it for you.
- Add a text box that sends typed input into the same session, as a fallback for a noisy room or a strained voice.

## 9. War-room UI (`/web`)

Driven entirely by `IncidentUpdate` events from the hub's WebSocket.

- **Timer**, large, from `alerted` to `fix_verified`.
- **Timeline** of stages, each lighting up as it completes.
- **Evidence cards**: the trace excerpt, the deploy diff with the guilty line highlighted, the code around the failing line.
- **Fix candidates**, three cards side by side, each with a spinner that turns into pass or fail with test counts. This is the visual centre of the demo.
- **Pull request link** when opened.
- **Operator panel** (can be a separate page): buttons to apply each fault and to reset.
- **Transcript** of what the voice said, and the text-input fallback.

## 10. Gate (`/core/gate.py`)

One interface, two implementations.

- `triage_alert(alert) -> page | ignore`
- `assess_fix(candidate, result) -> FixRisk`. Inputs as text: files touched, lines changed, whether it touches config or code, tests run and passed, fault category.

Jev first, rules fallback behind the same function (for example: auto-apply only if one file, fewer than 10 lines, all tests pass). Test Jev's API shape before relying on it. If it costs more than 30 minutes, ship the fallback and say so.

## 11. Sponsor fit, stated honestly

- **Gemini Live:** conversation continues while the investigation runs; results interrupt the speaker; approvals by voice.
- **Best use of Modal:** Sandboxes run model-written tests and patches in isolation, several at once. Without them there is no verified fix.
- **Best use of Pydantic:** Logfire is the evidence source; Pydantic AI runs the investigator with validated typed outputs; the Gateway carries the LLM calls with failover; Live tool arguments are validated with the ask-again loop. Optional: Pydantic Evals over the four faults (did it find the right file and line).
- **Jev:** the two fast typed decisions, with calibrated confidence.

## 12. Timeline

| Time | Goal |
|---|---|
| 15:15–15:35 | Repo, `contracts.py`, keys in `.env` and Modal Secrets, `.gitignore`. Briefs out to Devin, Codex and the terminal session. |
| 15:35–16:50 | Parallel build. Devin: shop, tests, faults 1–2, loadgen, alerts. Codex: UI against a recorded event file. Terminal: sandbox harness first, then the Live loop with `start_investigation` and one cue. This chat: hub, investigator, gate. |
| 16:50–17:45 | Join up fault 1 end to end without voice, then with voice. |
| 17:45–18:15 | Fault 2. Fix whatever broke. |
| 18:15–18:50 | Rehearse three times. Record the backup video. Write the submission. |
| 19:00 | Opt in. |

This is tight. Protect the 16:50 integration start. Anything not working by then gets cut, not debugged.

## 13. Cut order

1. Faults 3 and 4.
2. Jev (use the rules fallback).
3. Opening a real pull request (show the verified diff in the UI instead).
4. Model-written reproducing test (use the pre-written repro test per fault; still run it in the sandbox).
5. Logfire query API (read the local span file; show the Logfire UI).

Never cut: sandbox verification of fixes, the voice interrupt at `cause_found` and `fix_verified`, the rule that only verified fixes are offered.

## 14. The three-minute demo

1. Ten seconds: "Everyone here has been paged at 3am."
2. Someone in the audience picks fault 1 or 2. You press the button. The timer starts. Error rate climbs on screen.
3. A judge asks the agent what's happening. It answers and keeps chatting.
4. It interrupts with the cause. The guilty diff line lights up.
5. Three fix cards spin in parallel. One goes green. It interrupts again: one verified fix, want the pull request?
6. The judge says yes. The link appears. Stop the timer and read the number.
7. Close: Logfire trace of the whole incident, Modal Sandboxes fanning out, and the line "it only ever offers a fix it has already proven."

Have ready: a backup video, a phone hotspot, a headset, the text box. A judge does the talking, so your voice can rest.

## 15. Risks

- **The fix loop fails live.** Only two rehearsed faults. Pre-written repro tests as a fallback. "No fix passed" is handled gracefully.
- **Logfire ingestion delay.** Poll. Keep the local span file.
- **Sandbox cold start.** Build the image early. Run one throwaway sandbox ten minutes before the demo.
- **Noisy room.** Headset, push-to-talk, text box.
- **Gemini account rules.** Never push the key to a public repo. No bulk calls. The account is deleted about a day after the event, so keep code in your own GitHub.
- **Overclaiming.** It fixes rehearsed faults in a toy app. Say that. The pattern is the pitch: investigate from traces, reproduce, verify in isolation, then ask.

## 16. Paste-ready briefs

**Devin — `/shop`**

```
Build a small FastAPI "toy shop" in /shop as its own git repo. Modules: catalog, cart, checkout,
payments. SQLite. 20–25 pytest tests, all passing. Instrument with Logfire (configure,
instrument_fastapi, one span per service call with a "service" attribute). Also append every
span to spans.jsonl via a span processor.
Add loadgen.py: ~5 req/s of mixed browse / add-to-cart / checkout traffic.
Add alerts.py: every 5 s compute error rate and p95 latency per service over the last 30 s and
POST an Alert (see /core/contracts.py) to http://localhost:8000/alerts when error rate > 5% or
p95 > 800 ms.
Add /shop/faults/: a patch file + apply script for each fault, committed with a realistic message,
and reset.sh to return to the clean commit. Faults, in priority order:
 1. bad_config: PAYMENT_TIMEOUT_MS 3000 -> 3 in config.py, so payments time out.
 2. null_error: checkout reads cart.coupon.code with no None check.
 3. type_error: a serializer returns price as a string.
 4. slow_query: N+1 in the catalog listing.
For each fault also write tests/repro_<fault>.py.txt: a test that fails with the fault and passes
when fixed (kept out of the suite). Keys come from env vars only. Commit small and often.
```

**Codex — `/web`**

```
Build a single-page war-room UI in /web. It connects to ws://localhost:8000/ws and receives
IncidentUpdate JSON events (schema in /core/contracts.py). Develop against /web/sample_events.json
replayed on a timer, so you don't need the backend.
Show: a large timer from stage "alerted" to "fix_verified"; a stage timeline; evidence cards
(trace excerpt, deploy diff with the changed line highlighted, code snippet); three fix-candidate
cards side by side, each with a spinner that becomes pass/fail with test counts from VerifyResult;
the PR link; a transcript panel; a text input that POSTs to /say as a voice fallback.
Separate /operator page: buttons that POST /faults/{name}/apply and /faults/reset.
Readable on a projector: large type, high contrast, no clutter.
```

**Claude Code (terminal) — `/modal` then `/live`**

```
First /modal/sandbox.py: verify(candidate, repro, base_commit) -> VerifyResult and
check_repro_fails(repro, base_commit) -> bool, per section 7 of BUILD.md, using Modal Sandboxes.
No network in the sandbox, 60 s timeout, three candidates in parallel with asyncio.gather.
Prove it with a hand-written patch for fault 1 before moving on.
Then /live/session.py: a Gemini Live session (gemini-3.8-live) per section 8. Tools:
start_investigation, get_status, explain, approve_fix, with arguments validated by the Pydantic
models in /core/contracts.py. Inject VoiceCue objects from the hub with the right scheduling.
Keys from env vars only.
```