"""Local-only incident hub. Start with ``python3 -m uvicorn core.hub:app``."""

import asyncio
import json
import os
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from agent.fixtures import FIXTURES, apply_edit, patch_for, repro_for
from agent.investigator import investigate
from core.contracts import Alert, IncidentUpdate
from core.config import load_environment
from core.gate import assess_fix, triage_alert, verification_passed
from verification.backend import get_verifier
from verification.runner import copy_shop, probe_shop
from live import LiveAdapter, create_live_router, live_capabilities
from live.setup import create_setup_router
from agent.gemini import investigator_backend, investigator_capabilities
from agent.generation import repair_backend, repair_capabilities

load_environment()

REPO_ROOT = Path(__file__).resolve().parents[1]
MODE = "deterministic-local"
LOCAL_ORIGINS = {
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:4173", "http://127.0.0.1:4173",
    "http://localhost:8000", "http://127.0.0.1:8000",
}
CUES = {"alerted": "INTERRUPT", "cause_found": "INTERRUPT", "reproduced": "WHEN_IDLE", "fix_verified": "INTERRUPT", "no_fix_found": "INTERRUPT", "resolved": "WHEN_IDLE"}


class SayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000)
    incident_id: str | None = Field(default=None, max_length=100)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_id: str = Field(min_length=1, max_length=100)
    candidate_id: str = Field(min_length=1, max_length=100)


class Hub:
    def __init__(self, runtime: Path):
        self.runtime = runtime.resolve()
        self.shop = self.runtime / "shop"
        self.runs = self.runtime / "runs"
        self.incident_id: str | None = None
        self.active_fault: str | None = None
        self.history: list[dict] = []
        self.candidates = {}
        self.results = {}
        self.plans = {}
        self.approval: dict | None = None
        self.task: asyncio.Task | None = None
        self.subscribers: set[asyncio.Queue] = set()
        self.operation_lock = asyncio.Lock()
        self.probe: dict | None = None
        self.deploy_diff = ""
        self.backend_name, self.verifier = get_verifier()
        self.investigator_backend = investigator_backend()
        self.repair_backend = repair_backend()
        if self.repair_backend == "gemini" and self.backend_name != "modal":
            raise ValueError("REPAIR_BACKEND=gemini requires VERIFICATION_BACKEND=modal; generated code cannot execute locally.")
        self.mode = f"gemini-{self.backend_name}" if self.investigator_backend == "gemini" else "deterministic-modal" if self.backend_name == "modal" else MODE

    @property
    def stage(self) -> str | None:
        return self.history[-1]["stage"] if self.history else None

    def broadcast(self, payload: dict) -> None:
        for queue in tuple(self.subscribers):
            # Each incident emits fewer than 32 events. The cap protects abandoned clients.
            if queue.full():
                self.subscribers.discard(queue)
                continue
            queue.put_nowait(payload)

    async def emit(self, update: IncidentUpdate) -> None:
        if update.incident_id != self.incident_id:
            return  # A canceled investigation cannot publish into a new incident.
        payload = update.model_dump(mode="json")
        self.history.append(payload)
        self.candidates.update({candidate.candidate_id: candidate for candidate in update.candidates})
        self.results.update({result.candidate_id: result for result in update.results})
        self.broadcast(payload)
        if scheduling := CUES.get(update.stage):
            self.broadcast({"type": "voice_cue", "scheduling": scheduling, "facts": update.message})

    def status(self) -> dict:
        return {"mode": self.mode, "verification_backend": self.backend_name, "investigator_backend": self.investigator_backend, "repair_backend": self.repair_backend, "recommended_candidate_id": self.verified_candidate(), "incident_id": self.incident_id, "stage": self.stage, "active_fault": self.active_fault, "events": self.history, "approval": self.approval}

    async def stop(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.task = None

    def restore_shop(self) -> None:
        self.runtime.mkdir(parents=True, exist_ok=True)
        if self.shop.exists():
            shutil.rmtree(self.shop)
        copy_shop(REPO_ROOT / "shop", self.shop)

    async def reset(self) -> dict:
        async with self.operation_lock:
            self.incident_id = None  # invalidate all in-flight events before cancellation
            await self.stop()
            self.restore_shop()
            self.active_fault = None
            self.history = []
            self.candidates = {}
            self.results = {}
            self.plans = {}
            self.approval = None
            self.probe = None
            self.deploy_diff = ""
            self.broadcast({"type": "reset"})
            return {"ok": True, "message": "Runtime shop restored. Incident state cleared."}

    async def apply_fault(self, fault: str) -> dict:
        if fault not in FIXTURES:
            raise HTTPException(status_code=404, detail="Unknown fault. Choose bad_config or null_error.")
        async with self.operation_lock:
            if self.incident_id and self.stage != "resolved":
                raise HTTPException(status_code=409, detail="An incident is already active. Reset before applying another fault.")
            await self.stop()
            self.restore_shop()
            fixture = FIXTURES[fault]
            self.deploy_diff = patch_for(self.shop, fixture.edit)
            apply_edit(self.shop, fixture.edit)
            self.probe = await probe_shop(self.shop)
            self.incident_id = f"inc-{uuid.uuid4().hex[:12]}"
            self.active_fault = fault
            self.history = []
            self.candidates = {}
            self.results = {}
            self.plans = {}
            self.approval = None
            self.broadcast({"type": "reset"})
            now = datetime.now(timezone.utc)
            alert = Alert(alert_id=f"alert-{self.incident_id}", service="checkout", signal="error_rate", value=self.probe["error_rate"], threshold=0.05, started_at=now)
            if triage_alert(alert) != "page":
                raise HTTPException(status_code=500, detail="Fault did not trigger the expected alert.")
            with (self.runtime / "spans.jsonl").open("w") as stream:
                for index, record in enumerate(self.probe["records"]):
                    stream.write(json.dumps({"incident_id": self.incident_id, "at": now.isoformat(), "trace_id": f"{self.incident_id}-{index:02}", "service": "checkout", **record}) + "\n")
            from core.contracts import Evidence
            await self.emit(IncidentUpdate(
                incident_id=self.incident_id, stage="alerted", at=now,
                message=f"Checkout failed on {self.probe['failed']} of {self.probe['requests']} local probe requests ({alert.value:.0%}); alert threshold is {alert.threshold:.0%}.",
                evidence=[Evidence(evidence_id="checkout-error-rate", kind="metric", summary=f"{alert.value:.0%} checkout error rate in {self.probe['requests']} probe requests.", detail=json.dumps({"requests": self.probe["requests"], "failed": self.probe["failed"], "error_rate": alert.value, "threshold": alert.threshold}, indent=2), source_ref=".runtime/spans.jsonl")],
            ))
            self.start(internal=True)
            return {"incident_id": self.incident_id, "fault": fault, "mode": self.mode, "message": "Fault applied to the runtime shop. Investigation started."}

    def start(self, *, internal: bool = False) -> bool:
        if self.operation_lock.locked() and not internal:
            return False
        if not self.incident_id or not self.active_fault or not self.probe:
            return False
        if self.task is not None:
            return False
        self.task = asyncio.create_task(investigate(self.incident_id, FIXTURES[self.active_fault], self.shop, self.probe, self.deploy_diff, self.runs, self.emit, self.verifier, self.backend_name, self.investigator_backend, self.repair_backend, self.plans))
        return True

    def verified_candidate(self) -> str | None:
        if self.approval:
            return self.approval["candidate_id"]
        # Proposal order is stable; network completion order is not a ranking.
        return next((candidate_id for candidate_id in self.candidates if candidate_id in self.results and verification_passed(self.results[candidate_id])), None)

    async def approve(self, request: ApprovalRequest) -> dict:
        async with self.operation_lock:
            if request.incident_id != self.incident_id:
                raise HTTPException(status_code=409, detail="Approval belongs to a stale incident.")
            if self.approval:
                if request.candidate_id == self.approval["candidate_id"]:
                    return {"text": "This verified fix has already been applied to the runtime shop.", "role": "assistant", **self.approval}
                raise HTTPException(status_code=409, detail="A different candidate was already approved.")
            candidate = self.candidates.get(request.candidate_id)
            result = self.results.get(request.candidate_id)
            if self.stage != "fix_verified" or not candidate or not result or assess_fix(candidate, result).action == "reject":
                raise HTTPException(status_code=409, detail="Only a verified candidate from the current completed investigation can be approved.")
            fixture = FIXTURES[self.active_fault]
            plan = self.plans.get(request.candidate_id)
            if plan is None:
                raise HTTPException(status_code=409, detail="The current incident has no stored execution plan for that candidate.")
            generated = candidate.origin == "gemini"
            if generated:
                from verification.generated import GeneratedPlan, apply_generated_plan, generated_patch, snapshot_sha256, validate_generated_plan
                if self.backend_name != "modal" or not isinstance(plan, GeneratedPlan):
                    raise HTTPException(status_code=409, detail="Generated repairs require their original Modal verification plan.")
                if candidate.snapshot_sha != plan.base_sha256:
                    raise HTTPException(status_code=409, detail="Candidate source fingerprint does not match the verified plan.")
                try:
                    validate_generated_plan(self.shop, plan)
                    current_patch = generated_patch(self.shop, plan)
                except ValueError as exc:
                    raise HTTPException(status_code=409, detail="Runtime source changed since verification. Reset and investigate again.") from exc
            else:
                from agent.fixtures import CandidatePlan
                if not isinstance(plan, CandidatePlan):
                    raise HTTPException(status_code=409, detail="Candidate provenance does not match its execution plan.")
                current_patch = patch_for(self.shop, plan.edit)
            # Bind approval to the exact proposed diff, not merely its display ID.
            if current_patch != candidate.patch:
                raise HTTPException(status_code=409, detail="Runtime code changed since verification. Reset and investigate again.")
            target = self.shop / plan.edit.path
            original = target.read_text()
            filename = f"{self.incident_id}-{candidate.candidate_id}.patch"
            artifacts = self.runtime / "artifacts"
            artifact = artifacts / filename
            try:
                if generated:
                    # Writing validated text is the only host operation on model
                    # output. Tests, imports, and probes execute remotely in Modal.
                    apply_generated_plan(self.shop, plan)
                    applied_sha = snapshot_sha256(self.shop)
                    post_apply, healthy = await self.verifier.verify_generated_recovery(self.shop, plan, repro_for(fixture), self.runs)
                    if snapshot_sha256(self.shop) != applied_sha:
                        raise RuntimeError("Runtime source changed during remote recovery verification.")
                else:
                    apply_edit(self.shop, plan.edit)
                    post_apply = await self.verifier.verify_candidate(self.shop, plan, repro_for(fixture), self.runs, apply=False)
                    healthy = await probe_shop(self.shop)
                if not (post_apply.candidate_id == candidate.candidate_id and verification_passed(post_apply) and healthy["failed"] == 0 and healthy["requests"] > 0):
                    raise RuntimeError("Post-apply verification failed; original broken runtime restored.")
                artifacts.mkdir(parents=True, exist_ok=True)
                artifact.write_text(candidate.patch)
            except BaseException:
                target.write_text(original)
                artifact.unlink(missing_ok=True)
                raise
            artifact_url = f"/artifacts/{filename}"
            self.approval = {"incident_id": self.incident_id, "candidate_id": candidate.candidate_id, "approved": True, "artifact_url": artifact_url, "origin": candidate.origin, "snapshot_sha": candidate.snapshot_sha}
            location = "Modal recovery" if generated else "Recheck"
            await self.emit(IncidentUpdate(incident_id=self.incident_id, stage="resolved", at=datetime.now(timezone.utc), message=f"Approved patch saved to the runtime toy shop. {location} passed {post_apply.tests_run} tests and all {healthy['requests']} checkout probes. Download the verified patch at {artifact_url}.", candidates=[candidate], results=[post_apply]))
            return {"text": "Verified fix applied to the local toy shop. All post-apply tests and checkout probes passed. The patch is ready to download.", "role": "assistant", **self.approval}

    async def say(self, text: str, incident_id: str | None = None) -> dict:
        words = text.strip().lower()
        if not words:
            raise HTTPException(status_code=422, detail="Enter a command or question.")
        if re.fullmatch(r"(?:yes|yes please|approve|approve fix|approve the fix|apply|apply fix|apply the fix|ship it)[.!?]*", words):
            if self.incident_id and incident_id != self.incident_id:
                raise HTTPException(status_code=409, detail="Approval text must be bound to the incident currently shown. Refresh the incident and approve again.")
            winner = self.verified_candidate()
            if winner and self.incident_id and self.stage in {"fix_verified", "resolved"}:
                return await self.approve(ApprovalRequest(incident_id=self.incident_id, candidate_id=winner))
            answer = "There is no verified fix ready for approval. I will only apply a candidate after both the reproduction and regression suite pass."
        elif not self.incident_id:
            answer = "No incident is active. Apply the payment-timeout or missing-coupon fault in the operator controls, then I will investigate."
        elif re.search(r"\b(start|investigate|investigation)\b", words):
            started = self.start()
            answer = "Investigation started." if started else f"The investigation is already at {self.stage.replace('_', ' ')}. {self.history[-1]['message']}"
        elif re.search(r"\b(tried|candidate|candidates|tests|verification)\b", words):
            if self.results:
                facts = [f"{candidate_id}: {'passed' if verification_passed(result) else 'failed'}, {result.tests_run} tests, {result.tests_failed} failures" for candidate_id, result in self.results.items()]
                location = "network-disabled Modal sandbox" if self.backend_name == "modal" else "separate local copy"
                answer = "; ".join(facts) + f". Each result comes from a {location} running pytest."
            else:
                answer = "Verification results are not available yet. " + self.history[-1]["message"]
        elif re.search(r"\b(cause|why|explain|evidence|wrong|happened)\b", words):
            cause = next((event["root_cause"] for event in reversed(self.history) if event["root_cause"]), None)
            answer = f"{cause['explanation']} Evidence points to {cause['file']}:{cause['line']}." if cause else "I have not confirmed the cause yet. " + self.history[-1]["message"]
        elif re.search(r"\b(fix|patch)\b", words):
            winner = self.verified_candidate()
            answer = f"{self.candidates[winner].title}: {self.candidates[winner].rationale} It passed the reproduction and regression suite. Say 'approve the fix' to apply it to the runtime toy shop." if winner else "No candidate is verified yet. " + self.history[-1]["message"]
        elif re.search(r"\b(status|happening|checkout|progress|update|going)\b", words):
            answer = self.history[-1]["message"]
        else:
            answer = "I can report status, explain the cause, list the tested candidates, or approve the verified fix. " + self.history[-1]["message"]
        return {"text": answer, "role": "assistant"}


def create_app(runtime: Path | None = None) -> FastAPI:
    hub = Hub(runtime or Path(os.environ.get("WAR_ROOM_RUNTIME", str(REPO_ROOT / ".runtime"))))
    origins = set(LOCAL_ORIGINS)
    # Optional origins are explicit; wildcard CORS is intentionally unsupported.
    origins.update(origin.strip().rstrip("/") for origin in os.environ.get("WAR_ROOM_ALLOWED_ORIGINS", "").split(",") if origin.strip() and origin.strip() != "*")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await hub.stop()

    app = FastAPI(title="Voice Incident War Room", version="1.0.0", lifespan=lifespan)
    app.state.hub = hub
    app.add_middleware(CORSMiddleware, allow_origins=sorted(origins), allow_methods=["GET", "POST"], allow_headers=["Content-Type"], allow_credentials=False)

    async def live_start(service: str | None) -> dict:
        if service and service not in {"checkout", "payments"}:
            return {"started": False, "message": f"There is no active {service} alert in this toy-shop scenario."}
        started = hub.start()
        return {"started": started, "incident_id": hub.incident_id, "stage": hub.stage, "message": hub.history[-1]["message"] if hub.history else "No alert is active. Apply a fault in the operator controls first."}

    async def live_explain(topic: str) -> dict:
        question = {"cause": "explain the cause", "fix": "describe the fix", "evidence": "explain the evidence", "what_was_tried": "what was tried"}[topic]
        return {"topic": topic, "answer": (await hub.say(question))["text"], "incident": compact_status(hub.status())}

    async def live_approve(candidate_id: str, incident_id: str) -> dict:
        return await hub.approve(ApprovalRequest(candidate_id=candidate_id, incident_id=incident_id))

    def live_subscribe() -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=128)
        hub.subscribers.add(queue)
        return queue

    app.include_router(create_live_router(LiveAdapter(
        get_status=hub.status, start_investigation=live_start, explain=live_explain,
        approve_fix=live_approve, subscribe=live_subscribe, unsubscribe=hub.subscribers.discard,
    ), allowed_origins=origins))
    app.include_router(create_setup_router())

    @app.middleware("http")
    async def local_mutations(request: Request, call_next):
        if request.method == "POST" and request.headers.get("origin") and request.headers["origin"].rstrip("/") not in origins:
            return JSONResponse(status_code=403, content={"detail": "Origin is not allowed to mutate this local demo."})
        return await call_next(request)

    @app.get("/health")
    async def health():
        capabilities = live_capabilities()
        return {"ok": True, "mode": hub.mode, "verification": hub.backend_name, "integrations": {"gemini": capabilities["gemini_live"], "modal": hub.backend_name == "modal", "logfire": False, "github": False}, **capabilities, **investigator_capabilities(), **repair_capabilities()}

    @app.get("/status")
    async def status():
        return hub.status()

    @app.post("/say")
    async def say(body: SayRequest):
        return await hub.say(body.text, body.incident_id)

    @app.post("/faults/reset")
    async def reset():
        return await hub.reset()

    @app.post("/faults/{name}/apply")
    async def apply_fault(name: str):
        return await hub.apply_fault(name)

    @app.post("/approve")
    async def approve(body: ApprovalRequest):
        return await hub.approve(body)

    @app.get("/artifacts/{filename}")
    async def artifact(filename: str):
        if not re.fullmatch(r"inc-[a-f0-9]{12}-[a-z0-9-]+\.patch", filename):
            raise HTTPException(status_code=404, detail="Artifact not found.")
        path = hub.runtime / "artifacts" / filename
        if not path.is_file() or path.is_symlink():
            raise HTTPException(status_code=404, detail="Artifact not found.")
        return FileResponse(path, media_type="text/x-diff", filename=filename)

    @app.websocket("/ws")
    async def websocket(websocket: WebSocket):
        if websocket.headers.get("origin") and websocket.headers["origin"].rstrip("/") not in origins:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        queue: asyncio.Queue = asyncio.Queue(maxsize=128)
        hub.subscribers.add(queue)
        replay = list(hub.history)

        async def send_events():
            await websocket.send_json({"type": "reset"})
            for event in replay:
                await websocket.send_json(event)
            while True:
                await websocket.send_json(await queue.get())

        sender = asyncio.create_task(send_events())
        try:
            while True:
                # The websocket is receive-only from the browser's perspective.
                # Client messages are ignored and can never inject incident events.
                await websocket.receive_text()
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            hub.subscribers.discard(queue)
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)

    return app


app = create_app()
