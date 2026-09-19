"""Protocol/approval tests: no credentials, network, microphone, or paid calls."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from live.session import LiveRelay, _safe_error, create_live_router, live_capabilities, session_config
from live.tools import ApprovalLatch, LiveAdapter, compact_status, execute_tool, verified_ids


def make_adapter():
    state = {
        "incident_id": "inc-1", "stage": "fix_verified", "mode": "local",
        "events": [{"incident_id": "inc-1", "message": "One candidate passed.",
                    "candidates": [{"candidate_id": "fix-1"}],
                    "results": [{"candidate_id": "fix-1", "applied": True, "repro_passed": True, "suite_passed": True, "tests_run": 24, "tests_failed": 0}]}],
    }
    queue = asyncio.Queue()
    adapter = LiveAdapter(
        get_status=lambda: state,
        start_investigation=AsyncMock(return_value={"started": True}),
        explain=AsyncMock(return_value="Known facts only."),
        approve_fix=AsyncMock(return_value={"approved": True}),
        subscribe=lambda: queue,
        unsubscribe=lambda unused: None,
    )
    return adapter, state, queue


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.incoming = asyncio.Queue()

    async def send_json(self, data):
        self.sent.append(data)

    async def send_bytes(self, data):
        self.sent.append(data)

    async def receive(self):
        return await self.incoming.get()


class FakeSession:
    def __init__(self):
        self.messages = asyncio.Queue()
        self.send_realtime_input = AsyncMock()
        self.send_client_content = AsyncMock()
        self.send_tool_response = AsyncMock()

    async def receive(self):
        while True:
            message = await self.messages.get()
            yield message
            if getattr(getattr(message, "server_content", None), "turn_complete", False):
                return


def test_approval_requires_recent_operator_confirmation_and_is_single_use():
    async def scenario():
        adapter, state, _ = make_adapter()
        latch = ApprovalLatch()
        refused = await execute_tool("approve_fix", {}, adapter, latch)
        assert "approval" in refused["error"]
        adapter.approve_fix.assert_not_awaited()
        latch.observe("Yes, apply the verified fix.", state)
        assert await execute_tool("approve_fix", {}, adapter, latch) == {"approved": True}
        adapter.approve_fix.assert_awaited_once_with("fix-1", "inc-1")
        assert "error" in await execute_tool("approve_fix", {}, adapter, latch)
    asyncio.run(scenario())


def test_negative_conditional_unverified_and_stale_approval_are_rejected():
    adapter, state, _ = make_adapter()
    latch = ApprovalLatch()
    for text in ("Don't apply it", "yes but do not apply", "if it passes apply it", "what does approve mean?"):
        latch.observe(text, state)
        assert not latch.consume("fix-1", state)
    latch.observe("yes", state)
    state["incident_id"] = "inc-2"
    assert not latch.consume("fix-1", state)
    assert verified_ids(state) == set()
    state["incident_id"] = "inc-1"
    state["events"][0]["results"][0]["applied"] = False
    latch.observe("apply the verified fix", state)
    assert not latch.consume("fix-1", state)


def test_tool_validation_and_actual_adapter_routing():
    async def scenario():
        adapter, _, _ = make_adapter()
        latch = ApprovalLatch()
        assert "error" in await execute_tool("start_investigation", {"service": "unknown"}, adapter, latch)
        assert "error" in await execute_tool("approve_fix", {"approved": True}, adapter, latch)
        assert "error" in await execute_tool("run_shell", {"command": "bad"}, adapter, latch)
        await execute_tool("start_investigation", {"service": "checkout"}, adapter, latch)
        adapter.start_investigation.assert_awaited_once_with("checkout")
        assert await execute_tool("explain", {"topic": "cause"}, adapter, latch) == {"facts": "Known facts only."}
        assert (await execute_tool("get_status", {}, adapter, latch))["verified_candidate_ids"] == ["fix-1"]
    asyncio.run(scenario())


def test_empty_or_failed_suite_is_never_eligible_even_with_true_booleans():
    _, state, _ = make_adapter()
    result = state["events"][0]["results"][0]
    result["tests_run"] = 0
    assert verified_ids(state) == set()
    result["tests_run"] = 24
    result["tests_failed"] = 1
    assert verified_ids(state) == set()


def test_multiple_passing_model_repairs_use_only_verified_hub_recommendation():
    async def scenario():
        adapter, state, _ = make_adapter()
        state["events"][0]["candidates"].append({"candidate_id": "fix-2"})
        state["events"][0]["results"].append({"candidate_id": "fix-2", "applied": True, "repro_passed": True, "suite_passed": True, "tests_run": 25, "tests_failed": 0})
        state["recommended_candidate_id"] = "fix-2"
        latch = ApprovalLatch()
        latch.observe("Apply the verified fix", state)
        assert await execute_tool("approve_fix", {}, adapter, latch) == {"approved": True}
        adapter.approve_fix.assert_awaited_once_with("fix-2", "inc-1")
        state["recommended_candidate_id"] = "unverified-candidate"
        latch.observe("Apply the verified fix", state)
        assert "error" in await execute_tool("approve_fix", {}, adapter, latch)
        assert adapter.approve_fix.await_count == 1
    asyncio.run(scenario())


def test_conversation_has_latest_candidate_failures_from_current_incident_only():
    _, state, _ = make_adapter()
    state["events"][0]["candidates"][0].update(title="Five-second timeout", origin="gemini")
    state["events"].append({"incident_id": "inc-1", "results": [{"candidate_id": "fix-1", "applied": True, "repro_passed": True, "suite_passed": False, "tests_run": 25, "tests_failed": 1, "log_tail": "x" * 3000 + "AssertionError: deadline must be <= 3000"}]})
    state["events"].append({"incident_id": "retired", "message": "stale secret", "candidates": [{"candidate_id": "other"}], "results": []})
    facts = compact_status(state)
    assert len(facts["candidate_verifications"]) == 1
    result = facts["candidate_verifications"][0]
    assert result["title"] == "Five-second timeout"
    assert result["tests_failed"] == 1
    assert len(result["failed_log_tail"]) == 2200
    assert result["failed_log_tail"].endswith("deadline must be <= 3000")
    assert "stale secret" not in str(facts)
    assert "patch" not in result


def test_browser_audio_and_typed_input_use_documented_sdk_calls():
    async def scenario():
        adapter, _, _ = make_adapter()
        socket, session = FakeSocket(), FakeSession()
        relay = LiveRelay(socket, session, adapter)
        voice = b"\xdc\x05" * 640
        await socket.incoming.put({"type": "websocket.receive", "bytes": voice})
        await socket.incoming.put({"type": "websocket.receive", "bytes": b"\x00"})
        await socket.incoming.put({"type": "websocket.receive", "text": '{"type":"text","text":"What is happening?"}'})
        await socket.incoming.put({"type": "websocket.receive", "text": '{"type":"audio_stream_end"}'})
        await socket.incoming.put({"type": "websocket.disconnect"})
        await relay.browser_to_model()
        session.send_realtime_input.assert_any_await(audio={"data": voice, "mime_type": "audio/pcm;rate=16000"})
        session.send_realtime_input.assert_any_await(activity_start={})
        session.send_realtime_input.assert_any_await(text="What is happening?")
        session.send_realtime_input.assert_any_await(activity_end={})
        assert any(item.get("type") == "error" for item in socket.sent)
        assert any(item.get("role") == "user" for item in socket.sent)
    asyncio.run(scenario())


def test_audio_transcript_and_tool_call_in_same_model_event_are_all_processed():
    async def scenario():
        adapter, _, _ = make_adapter()
        socket, session = FakeSocket(), FakeSession()
        relay = LiveRelay(socket, session, adapter)
        content = SimpleNamespace(
            input_transcription=SimpleNamespace(text="What is the status?"),
            output_transcription=SimpleNamespace(text="One candidate passed."),
            model_turn=SimpleNamespace(parts=[SimpleNamespace(inline_data=SimpleNamespace(data=b"\x01\x00"))]),
            turn_complete=True, interrupted=False,
        )
        await session.messages.put(SimpleNamespace(server_content=content, tool_call=SimpleNamespace(function_calls=[SimpleNamespace(name="get_status", args={}, id="call-1")]), go_away=None))
        task = asyncio.create_task(relay.model_to_browser())
        for _ in range(20):
            if session.send_tool_response.await_count:
                break
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert b"\x01\x00" in socket.sent
        transcripts = [item for item in socket.sent if isinstance(item, dict) and item.get("type") == "transcript"]
        assert {item["role"] for item in transcripts} == {"user", "assistant"}
        assert session.send_tool_response.await_args.kwargs["function_responses"][0]["id"] == "call-1"
    asyncio.run(scenario())


def test_cues_interrupt_or_remain_silent_without_arming_approval():
    async def scenario():
        adapter, state, _ = make_adapter()
        socket, session = FakeSocket(), FakeSession()
        relay = LiveRelay(socket, session, adapter)
        await relay.send_cue({"scheduling": "INTERRUPT", "facts": "One candidate is verified. Ask for approval."})
        assert session.send_client_content.await_args.kwargs["turn_complete"] is True
        assert socket.sent[0] == {"type": "interrupted"}
        assert not relay.approval.consume("fix-1", state)
        await relay.send_cue({"scheduling": "SILENT", "facts": "yes apply the fix"})
        assert session.send_client_content.await_args.kwargs["turn_complete"] is False
        assert not relay.approval.consume("fix-1", state)
    asyncio.run(scenario())


def test_partial_voice_yes_cannot_approve_before_transcription_finishes():
    async def scenario():
        adapter, _, _ = make_adapter()
        socket, session = FakeSocket(), FakeSession()
        relay = LiveRelay(socket, session, adapter)
        partial = SimpleNamespace(server_content=SimpleNamespace(input_transcription=SimpleNamespace(text="Yes", finished=False)), tool_call=SimpleNamespace(function_calls=[SimpleNamespace(name="approve_fix", args={}, id="call-1")]))
        await session.messages.put(partial)
        task = asyncio.create_task(relay.model_to_browser())
        for _ in range(20):
            if session.send_tool_response.await_count:
                break
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        adapter.approve_fix.assert_not_awaited()
        assert "error" in session.send_tool_response.await_args.kwargs["function_responses"][0]["response"]
    asyncio.run(scenario())


def test_empty_final_transcription_marker_is_exposed_and_arms_completed_speech():
    async def scenario():
        adapter, _, _ = make_adapter()
        socket, session = FakeSocket(), FakeSession()
        relay = LiveRelay(socket, session, adapter)
        await session.messages.put(SimpleNamespace(server_content=SimpleNamespace(input_transcription=SimpleNamespace(text="Apply the verified fix.", finished=False))))
        await session.messages.put(SimpleNamespace(
            server_content=SimpleNamespace(input_transcription=SimpleNamespace(text=None, finished=True)),
            tool_call=SimpleNamespace(function_calls=[SimpleNamespace(name="approve_fix", args={}, id="call-final")]),
        ))
        task = asyncio.create_task(relay.model_to_browser())
        for _ in range(30):
            if session.send_tool_response.await_count:
                break
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        adapter.approve_fix.assert_awaited_once_with("fix-1", "inc-1")
        markers = [item["finished"] for item in socket.sent if isinstance(item, dict) and item.get("type") == "input_transcription_state"]
        assert markers == [False, True]
    asyncio.run(scenario())


def test_router_opens_mocked_sdk_and_cleans_up_on_browser_disconnect():
    adapter, _, _ = make_adapter()
    session = FakeSession()
    opened = {}

    @asynccontextmanager
    async def connect(**kwargs):
        opened.update(kwargs)
        yield session

    client = SimpleNamespace(aio=SimpleNamespace(live=SimpleNamespace(connect=connect), aclose=AsyncMock()))
    app = FastAPI()
    app.include_router(create_live_router(adapter, client_factory=lambda: client))
    with TestClient(app) as browser:
        with browser.websocket_connect("/live", headers={"origin": "http://localhost:5173"}) as socket:
            assert socket.receive_json()["type"] == "ready"
            socket.send_json({"type": "disconnect"})
    assert opened["model"] == "gemini-3.8-live"
    assert opened["config"]["response_modalities"] == ["AUDIO"]
    client.aio.aclose.assert_awaited_once()


def test_capabilities_do_not_claim_credentials_verified_and_errors_redact_secrets(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-secret-never-display")
    assert live_capabilities()["gemini_live_configured"] is True
    assert live_capabilities()["gemini_live_status"] in {"missing_sdk", "configured_unverified"}
    assert "test-secret-never-display" not in _safe_error(RuntimeError("bad key test-secret-never-display"))
    assert "thinking_config" not in session_config()
    assert "proactivity" not in session_config()
    assert session_config()["realtime_input_config"]["automatic_activity_detection"]["disabled"] is True
