import asyncio

import pytest
from fastapi import HTTPException

from agent.generation import plans_from_batch
from core.contracts import VerifyResult
from core.hub import ApprovalRequest, Hub
from tests.test_generation import timeout_batch
from verification.generated import snapshot_sha256, validated_snapshot


def passing_result(candidate_id):
    return VerifyResult(candidate_id=candidate_id, applied=True, repro_passed=True, suite_passed=True, tests_run=25, tests_failed=0, duration_s=0.1, log_tail="Test double: remote execution is mocked in this test.")


def test_recommendation_follows_proposal_order_not_network_completion(tmp_path):
    hub = Hub(tmp_path / "runtime")
    hub.candidates = {"first": object(), "second": object()}
    hub.results = {"second": passing_result("second"), "first": passing_result("first")}
    assert hub.verified_candidate() == "first"
    hub.approval = {"candidate_id": "second"}
    assert hub.verified_candidate() == "second"


def configure_generated(monkeypatch):
    monkeypatch.setenv("REPAIR_BACKEND", "gemini")
    monkeypatch.setenv("VERIFICATION_BACKEND", "modal")
    monkeypatch.setenv("INVESTIGATOR_BACKEND", "local")

    async def reproduce(*args):
        return True, "1 failed (mocked remote reproduction)"

    async def generate(evidence, cause, root, repro):
        plans = plans_from_batch(timeout_batch(), root, snapshot_sha256(root))
        return plans, {"backend": "gemini", "requests": 1}

    async def verify(root, plan, *args):
        validated_snapshot(root, plan)
        return passing_result(plan.candidate_id)

    async def recovery(root, plan, *args):
        validated_snapshot(root, plan, applied=True)
        return passing_result(plan.candidate_id), {"requests": 12, "failed": 0}

    monkeypatch.setattr("verification.modal_runner.check_reproduction", reproduce)
    monkeypatch.setattr("agent.investigator.generate_repairs", generate)
    monkeypatch.setattr("verification.modal_runner.verify_generated", verify)
    monkeypatch.setattr("verification.modal_runner.verify_generated_recovery", recovery)


def test_generated_repairs_cannot_select_local_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("REPAIR_BACKEND", "gemini")
    with pytest.raises(ValueError, match="requires VERIFICATION_BACKEND=modal"):
        Hub(tmp_path)


def test_all_generated_candidates_may_pass_and_approval_uses_selected_patch_without_host_execution(tmp_path, monkeypatch):
    configure_generated(monkeypatch)

    async def scenario():
        hub = Hub(tmp_path)
        await hub.apply_fault("bad_config")
        await hub.task
        assert hub.stage == "fix_verified", hub.history[-1]
        assert len(hub.results) == 3
        assert all(result.repro_passed and result.suite_passed for result in hub.results.values())
        assert all(candidate.origin == "gemini" for candidate in hub.candidates.values())
        selected = list(hub.plans.values())[1]
        assert selected.edit.after == "PAYMENT_TIMEOUT_MS = 2000"

        async def forbidden(*args, **kwargs):
            pytest.fail("Generated source must never reach a host execution function")

        monkeypatch.setattr("core.hub.probe_shop", forbidden)
        monkeypatch.setattr("verification.runner.verify_candidate", forbidden)
        response = await hub.approve(ApprovalRequest(incident_id=hub.incident_id, candidate_id=selected.candidate_id))
        assert hub.stage == "resolved"
        assert response["candidate_id"] == selected.candidate_id
        assert response["origin"] == "gemini"
        assert "PAYMENT_TIMEOUT_MS = 2000\n" in (hub.shop / "app/config.py").read_text()
        assert (tmp_path / response["artifact_url"].lstrip("/")).read_text() == hub.candidates[selected.candidate_id].patch
        event_count = len(hub.history)
        await hub.approve(ApprovalRequest(incident_id=hub.incident_id, candidate_id=selected.candidate_id))
        assert len(hub.history) == event_count
    asyncio.run(scenario())


def test_generated_approval_rejects_any_changed_snapshot_file(tmp_path, monkeypatch):
    configure_generated(monkeypatch)

    async def scenario():
        hub = Hub(tmp_path)
        await hub.apply_fault("bad_config")
        await hub.task
        selected = hub.verified_candidate()
        target = hub.shop / "app/catalog.py"
        target.write_text(target.read_text() + "\n# external edit\n")
        with pytest.raises(HTTPException) as error:
            await hub.approve(ApprovalRequest(incident_id=hub.incident_id, candidate_id=selected))
        assert error.value.status_code == 409
        assert hub.approval is None
        assert "PAYMENT_TIMEOUT_MS = 3\n" in (hub.shop / "app/config.py").read_text()
    asyncio.run(scenario())


def test_generated_recovery_failure_rolls_back_without_host_probe(tmp_path, monkeypatch):
    configure_generated(monkeypatch)

    async def recovery(*args):
        raise RuntimeError("Remote recovery unavailable")

    monkeypatch.setattr("verification.modal_runner.verify_generated_recovery", recovery)

    async def scenario():
        hub = Hub(tmp_path)
        await hub.apply_fault("bad_config")
        await hub.task
        selected = hub.verified_candidate()
        with pytest.raises(RuntimeError, match="Remote recovery"):
            await hub.approve(ApprovalRequest(incident_id=hub.incident_id, candidate_id=selected))
        assert hub.approval is None
        assert "PAYMENT_TIMEOUT_MS = 3\n" in (hub.shop / "app/config.py").read_text()
        assert not (tmp_path / "artifacts").exists()
    asyncio.run(scenario())


def test_change_during_generated_recovery_prevents_resolution(tmp_path, monkeypatch):
    configure_generated(monkeypatch)

    async def recovery(root, plan, *args):
        target = root / "app/catalog.py"
        target.write_text(target.read_text() + "\n# changed during remote verification\n")
        return passing_result(plan.candidate_id), {"requests": 12, "failed": 0}

    monkeypatch.setattr("verification.modal_runner.verify_generated_recovery", recovery)

    async def scenario():
        hub = Hub(tmp_path)
        await hub.apply_fault("bad_config")
        await hub.task
        with pytest.raises(RuntimeError, match="changed during"):
            await hub.approve(ApprovalRequest(incident_id=hub.incident_id, candidate_id=hub.verified_candidate()))
        assert hub.approval is None
        assert "PAYMENT_TIMEOUT_MS = 3\n" in (hub.shop / "app/config.py").read_text()
    asyncio.run(scenario())


def test_reset_cancels_pending_generation_without_plan_leaks(tmp_path, monkeypatch):
    configure_generated(monkeypatch)

    async def scenario():
        entered, canceled = asyncio.Event(), asyncio.Event()

        async def pending(*args):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                canceled.set()

        monkeypatch.setattr("agent.investigator.generate_repairs", pending)
        hub = Hub(tmp_path)
        await hub.apply_fault("bad_config")
        await entered.wait()
        await hub.reset()
        assert canceled.is_set()
        assert hub.incident_id is None
        assert not hub.plans and not hub.candidates and not hub.results
        assert "PAYMENT_TIMEOUT_MS = 3000\n" in (hub.shop / "app/config.py").read_text()
    asyncio.run(scenario())


def test_failed_generator_never_falls_back_to_authored_repairs(tmp_path, monkeypatch):
    configure_generated(monkeypatch)

    async def failed(*args):
        raise RuntimeError("Generation unavailable")

    monkeypatch.setattr("agent.investigator.generate_repairs", failed)

    async def scenario():
        hub = Hub(tmp_path)
        await hub.apply_fault("bad_config")
        await hub.task
        assert hub.stage == "no_fix_found"
        assert not hub.plans and not hub.candidates and not hub.results
        assert "Generation unavailable" in hub.history[-1]["message"]
    asyncio.run(scenario())
