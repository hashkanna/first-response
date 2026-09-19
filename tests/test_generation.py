import asyncio
import json

import pytest
from pydantic_ai.models.test import TestModel

from agent.fixtures import CandidatePlan, Edit, FIXTURES, apply_edit, patch_for, repro_for
from agent.generation import RepairBatch, build_generation_input, candidate_views, generate_repairs, plans_from_batch
from core.contracts import Evidence, ReproTest, RootCause
from core.hub import REPO_ROOT
from verification.generated import apply_generated_plan, snapshot_sha256
from verification.runner import check_reproduction, copy_shop, probe_shop, verify_candidate


def timeout_batch(values=(1000, 2000, 3000)):
    return RepairBatch(candidates=[{
        "title": f"Use a {value} ms payment budget",
        "rationale": f"A {value} ms budget should accommodate the observed provider latency while keeping a finite limit.",
        "path": "app/config.py", "before": "PAYMENT_TIMEOUT_MS = 3", "after": f"PAYMENT_TIMEOUT_MS = {value}",
    } for value in values])


def broken_shop(tmp_path):
    root = tmp_path / "shop"
    copy_shop(REPO_ROOT / "shop", root)
    fixture = FIXTURES["bad_config"]
    diff = patch_for(root, fixture.edit)
    apply_edit(root, fixture.edit)
    evidence = [
        Evidence(evidence_id="trace-checkout", kind="exception", summary="Checkout failed", detail="PaymentTimeout: Payment provider needs 80 ms; timeout is 3 ms"),
        Evidence(evidence_id="deploy-change", kind="deploy_diff", summary="Runtime timeout changed", detail=diff),
    ]
    cause = RootCause(service="payments", file="shop/app/config.py", line=3, explanation="The timeout is below the observed provider latency.", evidence_ids=[item.evidence_id for item in evidence], confidence=0.98)
    return root, evidence, cause, repro_for(fixture)


def test_model_generates_three_snapshot_bound_candidates(tmp_path):
    root, evidence, cause, repro = broken_shop(tmp_path)

    async def scenario():
        plans, receipt = await generate_repairs(evidence, cause, root, repro, model=TestModel(custom_output_args=timeout_batch().model_dump()))
        assert len(plans) == 3
        assert len({plan.candidate_id for plan in plans}) == 3
        assert {plan.base_sha256 for plan in plans} == {snapshot_sha256(root)}
        assert receipt["requests"] == 1
        assert len(receipt["input_payload_sha256"]) == 64
        assert len(receipt["output_payload_sha256"]) == 64
        views = candidate_views(root, plans)
        assert all(view.origin == "gemini" and view.snapshot_sha == plan.base_sha256 for view, plan in zip(views, plans))
        assert "+PAYMENT_TIMEOUT_MS = 2000" in views[1].patch
        assert "PAYMENT_TIMEOUT_MS = 3\n" in (root / "app/config.py").read_text()
    asyncio.run(scenario())


def test_generation_input_has_actual_data_without_authored_strategies(tmp_path):
    root, evidence, cause, repro = broken_shop(tmp_path)
    payload = build_generation_input(evidence, cause, root, repro)
    serialized = json.dumps(payload)
    assert "Payment provider needs 80 ms" in serialized
    assert "PAYMENT_TIMEOUT_MS = 3" in serialized
    assert "test_repro_payment_timeout" in serialized
    for plan in FIXTURES["bad_config"].candidates:
        assert plan.candidate_id not in serialized
        assert plan.title not in serialized
        assert plan.rationale not in serialized


def test_duplicate_candidates_are_rejected(tmp_path):
    root, _, _, _ = broken_shop(tmp_path)
    with pytest.raises(ValueError, match="distinct"):
        plans_from_batch(timeout_batch((1000, 1000, 3000)), root, snapshot_sha256(root))


def test_generation_rejects_snapshot_changed_while_waiting(tmp_path):
    root, _, _, _ = broken_shop(tmp_path)
    old_sha = snapshot_sha256(root)
    (root / "app/catalog.py").write_text((root / "app/catalog.py").read_text() + "\n# changed during generation\n")
    with pytest.raises(ValueError, match="changed"):
        plans_from_batch(timeout_batch(), root, old_sha)


def test_local_runner_cannot_execute_a_generated_plan_or_modified_source(tmp_path):
    root, _, _, repro = broken_shop(tmp_path)
    plan = plans_from_batch(timeout_batch(), root, snapshot_sha256(root))[0]

    async def scenario():
        with pytest.raises(ValueError, match="authored CandidatePlan"):
            await verify_candidate(root, plan, repro, tmp_path / "runs")
        apply_generated_plan(root, plan)
        with pytest.raises(ValueError, match="requires Modal"):
            await probe_shop(root)
    asyncio.run(scenario())


def test_invalid_generation_retries_then_fails_without_authored_fallback(tmp_path):
    root, evidence, cause, repro = broken_shop(tmp_path)
    batch = timeout_batch().model_dump()
    batch["candidates"][0]["after"] = "PAYMENT_TIMEOUT_MS = __import__('os').system('echo unsafe')"

    async def scenario():
        with pytest.raises(Exception, match="retries|limit"):
            await generate_repairs(evidence, cause, root, repro, model=TestModel(custom_output_args=batch))
        assert "PAYMENT_TIMEOUT_MS = 3\n" in (root / "app/config.py").read_text()
    asyncio.run(scenario())


def test_local_runner_rejects_generated_content_disguised_as_authored_types(tmp_path):
    root, _, _, repro = broken_shop(tmp_path)
    disguised = CandidatePlan("custom", "Custom source change", "This content is not an authored fixture.", Edit("app/config.py", "PAYMENT_TIMEOUT_MS = 3", "PAYMENT_TIMEOUT_MS = 2000"))
    untrusted_test = ReproTest(path=repro.path, code=repro.code + "\nprint('unreviewed code')\n")

    async def scenario():
        with pytest.raises(ValueError, match="authored CandidatePlan"):
            await verify_candidate(root, disguised, repro, tmp_path / "runs")
        with pytest.raises(ValueError, match="reviewed reproduction"):
            await check_reproduction(root, untrusted_test, tmp_path / "runs")
        with pytest.raises(ValueError, match="reviewed reproduction"):
            await verify_candidate(root, FIXTURES["bad_config"].candidates[0], untrusted_test, tmp_path / "runs")
    asyncio.run(scenario())
