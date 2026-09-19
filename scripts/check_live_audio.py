"""Bounded real speech-input rehearsal through the already-running Live relay.

macOS example (uses existing in-memory server credentials; never reads a key):
  .venv/bin/python scripts/check_live_audio.py --hub http://127.0.0.1:8001 --allow-live

By default only status questions and explicit negation are sent. The separate
--approve-verified mode authorizes applying the current verified toy-shop repair
via synthetic speech. Audio comes from macOS say, not a person's microphone.
Each provider session is capped at 60s.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx
from websockets.asyncio.client import connect

SAMPLE_RATE = 16_000
FRAME_BYTES = 640  # Same PCM16/20ms framing as the browser AudioWorklet.
STATUS_QUESTION = "What is the status of checkout?"
BARGE_QUESTION = "Stop. Do not change anything. Give me only one sentence about checkout."
NEGATION_QUESTION = "Do not apply or approve any changes. Just tell me the current checkout status."
RECONNECT_QUESTION = "What is the current checkout status? Do not change anything."
APPROVAL_COMMAND = "Apply the verified fix."


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_audio(text: str, directory: Path, name: str) -> tuple[bytes, dict[str, Any]]:
    aiff = directory / f"{name}.aiff"
    pcm = directory / f"{name}.pcm"
    subprocess.run(["say", "-r", "165", "-o", str(aiff), text], check=True, timeout=20, capture_output=True)
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(aiff), "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", str(pcm)], check=True, timeout=20, capture_output=True)
    audio = pcm.read_bytes()
    return audio, {"text": text, "source": "macOS say (synthetic; no human microphone)", "sample_rate": SAMPLE_RATE, "channels": 1, "format": "PCM16 little-endian", "pcm_bytes": len(audio), "duration_s": round(len(audio) / (SAMPLE_RATE * 2), 3), "sha256": hashlib.sha256(audio).hexdigest()}


class Capture:
    def __init__(self) -> None:
        self.started = time.monotonic()
        self.phase = "connecting"
        self.audio_bytes = 0
        self.audio_chunks = 0
        self.turns = 0
        self.interruptions = 0
        self.model: str | None = None
        self.events: list[dict[str, Any]] = []
        self.transcripts: dict[str, dict[str, Any]] = {}
        self.condition = asyncio.Condition()
        self.failure: str | None = None
        self.speech_reply_audio_bytes = 0
        self.typed_negation_completed = False

    async def receive(self, socket: Any) -> None:
        try:
            async for message in socket:
                async with self.condition:
                    if isinstance(message, bytes):
                        self.audio_bytes += len(message)
                        self.audio_chunks += 1
                        if self.audio_chunks == 1:
                            self.events.append({"type": "first_audio", "phase": self.phase, "elapsed_s": round(time.monotonic() - self.started, 3)})
                    else:
                        event = json.loads(message)
                        event["observed_at"] = utcnow()
                        event["phase"] = self.phase
                        event["elapsed_s"] = round(time.monotonic() - self.started, 3)
                        self.events.append(event)
                        if event.get("type") == "ready":
                            self.model = event.get("model")
                        elif event.get("type") == "turn_complete":
                            self.turns += 1
                        elif event.get("type") == "interrupted":
                            self.interruptions += 1
                        elif event.get("type") == "transcript":
                            key = event["id"]
                            if key in self.transcripts and event.get("delta"):
                                self.transcripts[key]["text"] += event["text"]
                            else:
                                self.transcripts[key] = {field: event.get(field) for field in ("id", "role", "text", "at", "phase")}
                        elif event.get("type") == "error":
                            self.failure = event.get("message", "Live relay error")
                    self.condition.notify_all()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.failure = f"{type(error).__name__}: {error}"
            async with self.condition:
                self.condition.notify_all()

    async def wait_for(self, predicate: Callable[[], bool], timeout: float = 15) -> None:
        async with asyncio.timeout(timeout):
            async with self.condition:
                await self.condition.wait_for(lambda: predicate() or bool(self.failure))
        if self.failure:
            raise RuntimeError(self.failure)

    def summary(self) -> dict[str, Any]:
        return {"model": self.model, "elapsed_s": round(time.monotonic() - self.started, 3), "native_output_pcm_bytes": self.audio_bytes, "speech_reply_audio_bytes": self.speech_reply_audio_bytes, "typed_negation_completed": self.typed_negation_completed, "native_output_chunks": self.audio_chunks, "output_sample_rate": 24_000, "turn_completions": self.turns, "interruption_events": self.interruptions, "transcripts": list(self.transcripts.values()), "events": self.events, "error": self.failure}


async def stream_pcm(socket: Any, pcm: bytes) -> None:
    # Leading/trailing silence provides explicit server VAD boundary context.
    audio = b"\0" * 3_200 + pcm + b"\0" * 16_000
    started = time.monotonic()
    for offset in range(0, len(audio), FRAME_BYTES):
        await socket.send(audio[offset:offset + FRAME_BYTES])
        await asyncio.sleep(max(0, started + (offset + FRAME_BYTES) / (SAMPLE_RATE * 2) - time.monotonic()))
    await socket.send(json.dumps({"type": "audio_stream_end"}))


async def speech_rehearsal(url: str, status_pcm: bytes, barge_pcm: bytes, session_timeout: float, prime_audio: bool = False) -> dict[str, Any]:
    capture = Capture()
    try:
        async with asyncio.timeout(session_timeout):
            async with connect(url, origin="http://localhost:5173", open_timeout=10, max_size=2**22) as socket:
                receiver = asyncio.create_task(capture.receive(socket))
                try:
                    await capture.wait_for(lambda: capture.model is not None, 20)
                    if prime_audio:
                        capture.phase = "typed_primer"
                        await socket.send(json.dumps({"type": "text", "text": "I will ask a read-only status question by audio next. Please say ready."}))
                        await capture.wait_for(lambda: capture.turns > 0, 15)
                    capture.phase = "speech_status"
                    speech_baseline_audio = capture.audio_bytes
                    print("Live session ready; sending synthetic status question.", flush=True)
                    await stream_pcm(socket, status_pcm)
                    await capture.wait_for(lambda: capture.audio_bytes > speech_baseline_audio, 20)
                    capture.speech_reply_audio_bytes = capture.audio_bytes - speech_baseline_audio
                    capture.phase = "barge_in"
                    baseline_audio = capture.audio_bytes
                    baseline_turns = capture.turns
                    print("Native audio received; sending a second speech command during output.", flush=True)
                    await stream_pcm(socket, barge_pcm)
                    await capture.wait_for(lambda: capture.audio_bytes > baseline_audio and capture.turns > baseline_turns, 20)
                    capture.phase = "typed_negation"
                    baseline_turns = capture.turns
                    await socket.send(json.dumps({"type": "text", "text": NEGATION_QUESTION}))
                    await capture.wait_for(lambda: capture.turns > baseline_turns, 15)
                    capture.typed_negation_completed = True
                    await socket.send(json.dumps({"type": "disconnect"}))
                finally:
                    receiver.cancel()
                    await asyncio.gather(receiver, return_exceptions=True)
    except Exception as error:
        capture.failure = f"{capture.phase}: {type(error).__name__}: {error}"
    return capture.summary()


async def reconnect_rehearsal(url: str, session_timeout: float) -> dict[str, Any]:
    capture = Capture()
    try:
        async with asyncio.timeout(session_timeout):
            async with connect(url, origin="http://localhost:5173", open_timeout=10, max_size=2**22) as socket:
                receiver = asyncio.create_task(capture.receive(socket))
                try:
                    await capture.wait_for(lambda: capture.model is not None, 20)
                    capture.phase = "reconnected_read_only_status"
                    await socket.send(json.dumps({"type": "text", "text": RECONNECT_QUESTION}))
                    await capture.wait_for(lambda: capture.audio_bytes > 0 and capture.turns > 0, 20)
                    await socket.send(json.dumps({"type": "disconnect"}))
                finally:
                    receiver.cancel()
                    await asyncio.gather(receiver, return_exceptions=True)
    except Exception as error:
        capture.failure = f"{type(error).__name__}: {error}"
    return capture.summary()


def status_fingerprint(status: dict[str, Any]) -> dict[str, Any]:
    return {key: status.get(key) for key in ("incident_id", "stage", "active_fault", "approval")}


def approval_target(status: dict[str, Any]) -> dict[str, str]:
    """Capture the exact verified recommendation; never infer it from prose."""
    incident_id = status.get("incident_id")
    candidate_id = status.get("recommended_candidate_id")
    if status.get("stage") != "fix_verified" or not incident_id or not candidate_id or status.get("approval"):
        raise ValueError("Spoken approval requires a current, unapproved fix_verified recommendation.")
    candidates, results = {}, {}
    for event in status.get("events", []):
        if event.get("incident_id") == incident_id:
            candidates.update({item["candidate_id"]: item for item in event.get("candidates", [])})
            results.update({item["candidate_id"]: item for item in event.get("results", [])})
    result = results.get(candidate_id, {})
    candidate = candidates.get(candidate_id, {})
    if not all(result.get(field) is True for field in ("applied", "repro_passed", "suite_passed")) or type(result.get("tests_run")) is not int or result["tests_run"] <= 0 or type(result.get("tests_failed")) is not int or result["tests_failed"] != 0:
        raise ValueError("Recommended candidate lacks passing reproduction and nonempty regression evidence.")
    snapshot = candidate.get("snapshot_sha")
    if not isinstance(snapshot, str) or len(snapshot) != 64 or any(char not in "0123456789abcdef" for char in snapshot.lower()):
        raise ValueError("Spoken approval rehearsal requires a recorded source snapshot SHA-256.")
    return {"incident_id": incident_id, "candidate_id": candidate_id, "snapshot_sha": snapshot}


def approval_resolved(status: dict[str, Any], target: dict[str, str]) -> bool:
    if status.get("incident_id") != target["incident_id"]:
        raise ValueError("Incident changed during approval rehearsal; stopping.")
    approval = status.get("approval") or {}
    if status.get("stage") == "resolved":
        if approval.get("approved") is not True or any(approval.get(key) != value for key, value in target.items()):
            raise ValueError("Resolved approval does not match captured incident, candidate and source snapshot.")
        return True
    if approval_target(status) != target:
        raise ValueError("Verified recommendation changed during approval rehearsal; stopping.")
    return False


async def approval_rehearsal(url: str, pcm: bytes, session_timeout: float, client: Any, status_url: str, target: dict[str, str]) -> dict[str, Any]:
    capture = Capture()
    observations = []

    async def current_status() -> dict[str, Any]:
        response = await client.get(status_url)
        response.raise_for_status()
        state = response.json()
        observations.append({"observed_at": utcnow(), **status_fingerprint(state)})
        return state

    try:
        async with asyncio.timeout(session_timeout):
            async with connect(url, origin="http://localhost:5173", open_timeout=10, max_size=2**22) as socket:
                receiver = asyncio.create_task(capture.receive(socket))
                sender = None
                try:
                    await capture.wait_for(lambda: capture.model is not None, 20)
                    if approval_target(await current_status()) != target:
                        raise ValueError("Verified source changed before speaking; no approval audio sent.")
                    capture.phase = "spoken_approval"
                    print("Verified incident and source captured; sending synthetic approval command.", flush=True)
                    sender = asyncio.create_task(stream_pcm(socket, pcm))
                    while not approval_resolved(await current_status(), target):
                        if capture.failure:
                            raise RuntimeError(capture.failure)
                        await asyncio.sleep(0.25)
                    await sender
                    await capture.wait_for(lambda: capture.audio_bytes > 0
                                           and any(event.get("type") == "tool_result" and event.get("name") == "approve_fix" and event.get("ok") is True for event in capture.events)
                                           and any(event.get("type") == "input_transcription_state" and event.get("finished") is True for event in capture.events), 15)
                    await socket.send(json.dumps({"type": "disconnect"}))
                finally:
                    if sender:
                        sender.cancel()
                    receiver.cancel()
                    await asyncio.gather(receiver, *([sender] if sender else []), return_exceptions=True)
    except Exception as error:
        capture.failure = f"{capture.phase}: {type(error).__name__}: {error}"
    return {**capture.summary(), "status_observations": observations}


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hub", default="http://127.0.0.1:8001")
    parser.add_argument("--allow-live", action="store_true", help="Explicitly allow bounded real Gemini sessions using the relay's existing credential")
    parser.add_argument("--session-timeout", type=float, default=60)
    parser.add_argument("--prime-audio", action="store_true", help="Diagnostic: complete a typed turn before streaming audio; its output does not count as an audio-input success")
    parser.add_argument("--approve-verified", action="store_true", help="Explicitly authorize synthetic spoken approval of the current verified toy-shop recommendation; requires a source snapshot and applies a real repair")
    args = parser.parse_args()
    target = urlsplit(args.hub)
    if target.scheme != "http" or target.hostname not in {"127.0.0.1", "localhost", "::1"} or target.username or target.password:
        parser.error("This rehearsal only connects to an existing loopback HTTP hub.")
    if not args.allow_live:
        parser.error("Pass --allow-live to authorize bounded real provider calls.")
    if not 10 <= args.session_timeout <= 60:
        parser.error("Session timeout must be 10–60 seconds.")
    if args.approve_verified and args.prime_audio:
        parser.error("Approval mode does not send a typed primer.")
    directory = Path(__file__).resolve().parents[1] / ".runtime" / "voice-checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory.mkdir(parents=True, exist_ok=True)
    receipt: dict[str, Any] = {"started_at": utcnow(), "hub": args.hub, "uses_human_microphone": False, "uses_existing_server_credentials": True, "credentials_read_by_script": False, "session_timeout_s": args.session_timeout, "limitations": ["Synthetic speech verifies provider audio input, ASR, native output, and relay framing; it does not test a person's microphone, room acoustics, headset, or perceived speaker playback.", "No new credentials, server restart, fault injection, or approval command is performed."]}
    if args.approve_verified:
        receipt["mode"] = "explicit_spoken_approval"
        receipt["limitations"][1] = "Explicit approval mode applies the captured verified toy-shop repair. No credentials are read, server restarted or fault injected. Run without concurrent operator actions."
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            before_response = await client.get(args.hub.rstrip("/") + "/status")
            before_response.raise_for_status()
            before = before_response.json()
            health_response = await client.get(args.hub.rstrip("/") + "/health")
            health_response.raise_for_status()
            health = health_response.json()
            receipt["before"] = status_fingerprint(before)
            receipt["capabilities"] = {key: value for key, value in health.items() if key in {"gemini_live", "gemini_live_model", "investigator_model", "verification", "mode", "capabilities"}}
            url = args.hub.rstrip("/").replace("http://", "ws://", 1) + "/live"
            if args.approve_verified:
                target = approval_target(before)
                receipt["approval_target"] = target
                pcm, audio = await asyncio.to_thread(make_audio, APPROVAL_COMMAND, directory, "approval-input")
                receipt["synthetic_inputs"] = [audio]
                session = await approval_rehearsal(url, pcm, args.session_timeout, client, args.hub.rstrip("/") + "/status", target)
                receipt["approval_session"] = session
                response = await client.get(args.hub.rstrip("/") + "/status")
                response.raise_for_status()
                after = response.json()
                receipt["after"] = status_fingerprint(after)
                receipt["checks"] = {
                    "synthetic_approval_transcribed": any(item["role"] == "user" and item["text"].strip().rstrip(".").lower() == APPROVAL_COMMAND.rstrip(".").lower() for item in session["transcripts"]),
                    "provider_final_transcription_observed": any(item.get("type") == "input_transcription_state" and item.get("finished") is True for item in session["events"]),
                    "approve_tool_succeeded": any(item.get("type") == "tool_result" and item.get("name") == "approve_fix" and item.get("ok") is True for item in session["events"]),
                    "captured_verified_repair_resolved": approval_resolved(after, target),
                    "native_pcm_returned": session["native_output_pcm_bytes"] > 0,
                    "session_errors_absent": not session["error"],
                }
            else:
                await run_read_only_rehearsal(args, directory, receipt, client, url)
    except Exception as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
    receipt["finished_at"] = utcnow()
    path = directory / "receipt.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"receipt": str(path), "checks": receipt.get("checks"), "error": receipt.get("error")}, indent=2), flush=True)
    return 0 if not receipt.get("error") and receipt.get("checks") and all(receipt["checks"].values()) else 1


async def run_read_only_rehearsal(args: Any, directory: Path, receipt: dict[str, Any], client: Any, url: str) -> None:
    status_pcm, status_audio = await asyncio.to_thread(make_audio, STATUS_QUESTION, directory, "status-input")
    barge_pcm, barge_audio = await asyncio.to_thread(make_audio, BARGE_QUESTION, directory, "barge-input")
    receipt["synthetic_inputs"] = [status_audio, barge_audio]
    url = args.hub.rstrip("/").replace("http://", "ws://", 1) + "/live"
    receipt["typed_primer_enabled"] = args.prime_audio
    receipt["speech_session"] = await speech_rehearsal(url, status_pcm, barge_pcm, args.session_timeout, args.prime_audio)
    receipt["reconnect_session"] = await reconnect_rehearsal(url, args.session_timeout)
    after_response = await client.get(args.hub.rstrip("/") + "/status")
    after_response.raise_for_status()
    receipt["after"] = status_fingerprint(after_response.json())
    speech, reconnect = receipt["speech_session"], receipt["reconnect_session"]
    input_texts = [item["text"] for item in speech["transcripts"] if item["role"] == "user" and item["phase"] in {"speech_status", "barge_in"}]
    tools = [item for section in (speech, reconnect) for item in section["events"] if item.get("type") == "tool_result"]
    receipt["checks"] = {
        "synthetic_speech_transcribed": any("checkout" in text.lower().replace(" ", "") for text in input_texts),
        "native_pcm_returned_for_audio_input": speech["speech_reply_audio_bytes"] > 0,
        "relay_audio_frames_acknowledged": any(event.get("type") == "audio_input" and event.get("received_bytes", 0) >= len(status_pcm) and event.get("started_turns", 0) > 0 and event.get("ended_turns", 0) > 0 for event in speech["events"]),
        "barge_in_interruption_observed": any(event.get("type") == "interrupted" and event.get("phase") == "barge_in" for event in speech["events"]),
        "negation_did_not_approve": speech["typed_negation_completed"] and not any(item.get("name") == "approve_fix" and item.get("ok") for item in tools),
        "reconnect_returned_native_audio": reconnect["native_output_pcm_bytes"] > 0,
        "incident_and_approval_unchanged": receipt["before"] == receipt["after"],
        "session_errors_absent": not speech["error"] and not reconnect["error"],
    }


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
