import asyncio

import pytest
from pydantic_ai.models.test import TestModel

from agent.gemini import GroundedRootCause, analyze_evidence, validate_grounding
from core.contracts import Evidence, RootCause
from core.hub import Hub


def bundle(pattern="timeout_budget"):
    timeout = pattern == "timeout_budget"
    filename = "shop/app/config.py" if timeout else "shop/app/checkout.py"
    line = "PAYMENT_TIMEOUT_MS = 3" if timeout else "coupon_code = cart.coupon.code"
    detail = "PaymentTimeout: Payment provider needs 80 ms; timeout is 3 ms" if timeout else "AttributeError: 'NoneType' object has no attribute 'code'"
    diff = "--- a/app/config.py\n+++ b/app/config.py\n-PAYMENT_TIMEOUT_MS = 3000\n+PAYMENT_TIMEOUT_MS = 3\n" if timeout else "--- a/app/checkout.py\n+++ b/app/checkout.py\n-coupon_code = cart.coupon.code if cart.coupon is not None else None\n+coupon_code = cart.coupon.code\n"
    evidence = [Evidence(evidence_id="trace-checkout", kind="exception", summary="Checkout failed", detail=detail), Evidence(evidence_id="deploy-change", kind="deploy_diff", summary="Runtime source changed", detail=diff)]
    sources = {filename: line + "\n"}
    root = RootCause(service="payments" if timeout else "checkout", file=filename, line=1, explanation="The timeout is below the provider latency." if timeout else "The optional coupon is dereferenced without a guard.", evidence_ids=[item.evidence_id for item in evidence], confidence=0.97)
    output = GroundedRootCause(**root.model_dump(), fault_pattern=pattern, causal_code_quote=line, evidence_quotes=[{"evidence_id": "trace-checkout", "quote": detail}, {"evidence_id": "deploy-change", "quote": "+" + line}])
    return output, evidence, sources, root


@pytest.mark.parametrize("pattern", ["timeout_budget", "missing_optional_value"])
def test_pydantic_ai_accepts_grounded_structured_analysis(pattern):
    output, evidence, sources, expected = bundle(pattern)

    async def scenario():
        root, receipt = await analyze_evidence(evidence, sources, expected, model=TestModel(custom_output_args=output.model_dump()))
        assert root.file == expected.file
        assert root.line == expected.line
        assert receipt["framework"] == "pydantic-ai"
        assert receipt["requests"] == 1
        assert receipt["analysis"]["evidence_quotes"]
    asyncio.run(scenario())


@pytest.mark.parametrize("change", [
    {"file": "shop/app/invented.py"},
    {"line": 100},
    {"commit": "fake-sha"},
    {"evidence_ids": ["invented"]},
    {"causal_code_quote": "PAYMENT_TIMEOUT_MS = 9000"},
    {"fault_pattern": "missing_optional_value"},
    {"evidence_quotes": [{"evidence_id": "trace-checkout", "quote": "fabricated timeout measurement"}, {"evidence_id": "deploy-change", "quote": "+PAYMENT_TIMEOUT_MS = 3"}]},
])
def test_grounding_rejects_fabricated_claims(change):
    output, evidence, sources, expected = bundle()
    changed = GroundedRootCause.model_validate({**output.model_dump(), **change})
    with pytest.raises(ValueError):
        validate_grounding(changed, evidence, sources, expected)


def test_invalid_model_output_retries_then_stops():
    output, evidence, sources, expected = bundle()
    args = {**output.model_dump(), "file": "shop/app/invented.py"}

    async def scenario():
        with pytest.raises(Exception, match="retries|limit"):
            await analyze_evidence(evidence, sources, expected, model=TestModel(custom_output_args=args))
    asyncio.run(scenario())


def test_provider_failure_does_not_fall_back_to_local_cause(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTIGATOR_BACKEND", "gemini")

    async def unavailable(*args):
        raise RuntimeError("Provider is unavailable")

    monkeypatch.setattr("agent.investigator.analyze_runtime", unavailable)

    async def scenario():
        hub = Hub(tmp_path)
        await hub.apply_fault("bad_config")
        await hub.task
        assert hub.mode == "gemini-local"
        assert hub.stage == "no_fix_found"
        assert not hub.candidates
        assert not any(event["root_cause"] for event in hub.history)
        assert "Provider is unavailable" in hub.history[-1]["message"]
        assert "PAYMENT_TIMEOUT_MS = 3\n" in (hub.shop / "app/config.py").read_text()
    asyncio.run(scenario())
