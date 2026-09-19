import asyncio
import hashlib
import json

import pytest
from fastapi import HTTPException

from core.hub import ApprovalRequest, Hub, REPO_ROOT
from verification.runner import probe_shop


def source_digest():
    return hashlib.sha256(b"".join(path.read_bytes() for path in sorted((REPO_ROOT / "shop").rglob("*.py")))).hexdigest()


@pytest.mark.parametrize("fault,winner,error_rate", [("bad_config", "timeout-restore", 1.0), ("null_error", "coupon-guard", 0.5)])
def test_complete_incident_reproduces_verifies_and_requires_approval(tmp_path, fault, winner, error_rate):
    async def scenario():
        before = source_digest()
        hub = Hub(tmp_path)
        applied = await hub.apply_fault(fault)
        assert applied["incident_id"] == hub.incident_id
        await hub.task
        assert hub.stage == "fix_verified"
        assert hub.verified_candidate() == winner
        assert len(hub.results) == 3
        assert all(result.tests_run == 25 for result in hub.results.values())
        assert sum(result.repro_passed and result.suite_passed for result in hub.results.values()) == 1
        assert (await probe_shop(hub.shop))["error_rate"] == error_rate
        assert hub.approval is None
        assert source_digest() == before

        rejected = next(candidate_id for candidate_id in hub.candidates if candidate_id != winner)
        with pytest.raises(HTTPException, match="409"):
            await hub.approve(ApprovalRequest(incident_id=hub.incident_id, candidate_id=rejected))
        response = await hub.approve(ApprovalRequest(incident_id=hub.incident_id, candidate_id=winner))
        assert hub.stage == "resolved"
        assert response["approved"] is True
        assert (await probe_shop(hub.shop))["failed"] == 0
        artifact = tmp_path / response["artifact_url"].lstrip("/")
        assert artifact.read_text() == hub.candidates[winner].patch
        assert source_digest() == before
        event_count = len(hub.history)
        assert (await hub.approve(ApprovalRequest(incident_id=hub.incident_id, candidate_id=winner)))["artifact_url"] == response["artifact_url"]
        assert len(hub.history) == event_count
        stages = [event["stage"] for event in hub.history]
        assert stages.index("cause_found") < stages.index("reproduced") < stages.index("fix_verified") < stages.index("resolved")
        logs = [json.loads(line) for line in (tmp_path / "spans.jsonl").read_text().splitlines()]
        assert len(logs) == 12
        assert sum(not item["ok"] for item in logs) == int(12 * error_rate)
    asyncio.run(scenario())


def test_stale_and_premature_approvals_are_rejected(tmp_path):
    async def scenario():
        hub = Hub(tmp_path)
        await hub.apply_fault("bad_config")
        with pytest.raises(HTTPException) as stale:
            await hub.approve(ApprovalRequest(incident_id="old-incident", candidate_id="timeout-restore"))
        assert stale.value.status_code == 409
        with pytest.raises(HTTPException) as premature:
            await hub.approve(ApprovalRequest(incident_id=hub.incident_id, candidate_id="timeout-restore"))
        assert premature.value.status_code == 409
        await hub.reset()
    asyncio.run(scenario())


def test_reset_cancels_investigation_and_invalidates_results(tmp_path, monkeypatch):
    async def scenario():
        entered = asyncio.Event()
        canceled = asyncio.Event()

        async def blocked(*args):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                canceled.set()

        import verification.runner as runner
        monkeypatch.setattr(runner, "check_reproduction", blocked)
        hub = Hub(tmp_path)
        await hub.apply_fault("null_error")
        old_id = hub.incident_id
        await entered.wait()
        await hub.reset()
        assert canceled.is_set()
        assert hub.incident_id is None
        assert not hub.history and not hub.results
        assert not hub.task
        assert (await probe_shop(hub.shop))["failed"] == 0
        from core.contracts import IncidentUpdate
        from datetime import datetime, timezone
        await hub.emit(IncidentUpdate(incident_id=old_id, stage="fix_verified", at=datetime.now(timezone.utc), message="stale"))
        assert not hub.history
    asyncio.run(scenario())


def test_second_fault_requires_reset(tmp_path):
    async def scenario():
        hub = Hub(tmp_path)
        await hub.apply_fault("bad_config")
        with pytest.raises(HTTPException) as conflict:
            await hub.apply_fault("null_error")
        assert conflict.value.status_code == 409
        await hub.reset()
        await hub.apply_fault("null_error")
        await hub.task
        assert hub.verified_candidate() == "coupon-guard", hub.history[-1]
    asyncio.run(scenario())


def test_text_commands_do_not_approve_negation(tmp_path):
    async def scenario():
        hub = Hub(tmp_path)
        assert "No incident" in (await hub.say("status"))["text"]
        await hub.apply_fault("bad_config")
        await hub.task
        for text in ["do not approve", "don't apply the fix", "what happens if I approve?"]:
            await hub.say(text)
            assert hub.approval is None
        assert "3000" in (await hub.say("explain the cause"))["text"]
        assert "25 tests" in (await hub.say("what was tried"))["text"]
        await hub.say("approve the fix", hub.incident_id)
        assert hub.stage == "resolved"
    asyncio.run(scenario())


def test_delayed_text_approval_cannot_apply_a_new_incident(tmp_path):
    async def scenario():
        hub = Hub(tmp_path)
        await hub.apply_fault("bad_config")
        await hub.task
        old_id = hub.incident_id
        await hub.reset()
        await hub.apply_fault("bad_config")
        await hub.task
        with pytest.raises(HTTPException) as rejected:
            await hub.say("approve the fix", old_id)
        assert rejected.value.status_code == 409
        assert hub.approval is None
        with pytest.raises(HTTPException):
            await hub.say("approve the fix")
        assert hub.approval is None
    asyncio.run(scenario())


def test_failed_post_apply_rolls_back(tmp_path, monkeypatch):
    async def scenario():
        hub = Hub(tmp_path)
        await hub.apply_fault("bad_config")
        await hub.task
        original = (hub.shop / "app/config.py").read_text()

        async def failed_verify(*args, **kwargs):
            raise RuntimeError("verification unavailable")

        monkeypatch.setattr(hub.verifier, "verify_candidate", failed_verify)
        with pytest.raises(RuntimeError, match="unavailable"):
            await hub.approve(ApprovalRequest(incident_id=hub.incident_id, candidate_id=hub.verified_candidate()))
        assert (hub.shop / "app/config.py").read_text() == original
        assert hub.approval is None
        assert hub.stage == "fix_verified"
    asyncio.run(scenario())


def test_start_cannot_race_fault_replacement(tmp_path, monkeypatch):
    async def scenario():
        hub = Hub(tmp_path)
        await hub.apply_fault("bad_config")
        await hub.task
        await hub.approve(ApprovalRequest(incident_id=hub.incident_id, candidate_id=hub.verified_candidate()))
        probe_entered, release_probe = asyncio.Event(), asyncio.Event()
        import core.hub as hub_module
        actual_probe = hub_module.probe_shop

        async def blocked_probe(root):
            probe_entered.set()
            await release_probe.wait()
            return await actual_probe(root)

        monkeypatch.setattr(hub_module, "probe_shop", blocked_probe)
        applying = asyncio.create_task(hub.apply_fault("null_error"))
        await probe_entered.wait()
        assert hub.start() is False
        release_probe.set()
        await applying
        await hub.task
        assert hub.active_fault == "null_error"
        assert hub.verified_candidate() == "coupon-guard"
    asyncio.run(scenario())
