"""Evidence-led orchestration for the two trusted incident scenarios.

Diagnosis uses local fixture matching or an explicitly selected Pydantic AI
Gemini analysis. Repairs are authored fixtures or bounded Gemini-generated
edits. Generated code executes only in Modal; provider failures never fall back.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

from agent.fixtures import FaultFixture, build_candidates, repro_for
from core.contracts import Evidence, IncidentUpdate, RootCause
from verification.runner import check_reproduction, verify_candidate
from agent.gemini import analyze_runtime
from core.gate import verification_passed
from core.errors import safe_error_detail
from agent.generation import candidate_views, generate_repairs

Emit = Callable[[IncidentUpdate], Awaitable[None]]


async def investigate(incident_id: str, fixture: FaultFixture, shop_root: Path, probe: dict, deploy_diff: str, runs_root: Path, emit: Emit, verifier=None, backend_name: str = "local", investigator_backend: str = "local", repair_backend: str = "authored", plans_store: dict | None = None) -> None:
    async def update(stage: str, message: str, **kwargs) -> None:
        await emit(IncidentUpdate(incident_id=incident_id, stage=stage, at=datetime.now(timezone.utc), message=message, **kwargs))

    try:
        if repair_backend == "gemini" and backend_name != "modal":
            raise RuntimeError("Generated repairs require Modal verification; local execution is forbidden.")
        await update("investigating", "Inspecting the actual failed checkouts and the runtime source change.")
        failure = next(record for record in probe["records"] if not record["ok"])
        target = shop_root / fixture.edit.path
        source = target.read_text()
        line = next(index for index, content in enumerate(source.splitlines(), start=1) if content.strip() == fixture.edit.after)
        snippet = "\n".join(f"{index:>3}  {content}" for index, content in enumerate(source.splitlines(), start=1) if max(1, line - 4) <= index <= line + 4)
        evidence = [
            Evidence(evidence_id="trace-checkout", kind="exception", summary=f"{failure['exception']}: {failure['message']}", detail=failure["traceback"], source_ref=".runtime/spans.jsonl"),
            Evidence(evidence_id="deploy-change", kind="deploy_diff", summary=f"The injected fault changed shop/{fixture.edit.path}.", detail=deploy_diff, source_ref=f"shop/{fixture.edit.path}"),
            Evidence(evidence_id="source-location", kind="code", summary=f"The failing runtime source matches the authored {fixture.name} fault.", detail=snippet, source_ref=f"shop/{fixture.edit.path}:{line}"),
        ]
        cause = RootCause(service=fixture.service, file=f"shop/{fixture.edit.path}", line=line, explanation=fixture.explanation, evidence_ids=[item.evidence_id for item in evidence], confidence=1.0)
        if investigator_backend == "gemini":
            await update("investigating", "Pydantic AI is asking Gemini to analyze the actual exception, deploy diff, and runtime source.", evidence=evidence)
            cause, receipt = await analyze_runtime(evidence, shop_root, cause)
            receipt["incident_id"] = incident_id
            receipt["at"] = datetime.now(timezone.utc).isoformat()
            (shop_root.parent / "investigator.json").write_text(json.dumps(receipt, indent=2))
        await update("cause_found", cause.explanation, evidence=evidence, root_cause=cause)

        repro = repro_for(fixture)
        reproduce = verifier.check_reproduction if verifier else check_reproduction
        verify = verifier.verify_candidate if verifier else verify_candidate
        failed, output = await reproduce(shop_root, repro, runs_root)
        repro.fails_on_current = failed
        if not failed:
            await update("no_fix_found", "The authored reproduction did not produce a single failing test. Investigation stopped; no fix can be approved.", evidence=[Evidence(evidence_id="repro-log", kind="trace", summary="Reproduction could not be confirmed.", detail=output[-12000:], source_ref=repro.path)])
            return
        await update("reproduced", "The reproduction fails on the broken runtime copy. Testing candidate fixes next.", evidence=[Evidence(evidence_id="repro-log", kind="trace", summary="The reproduction produced one failing test on the broken code.", detail=output[-12000:], source_ref=repro.path)])

        if repair_backend == "gemini":
            await update("reproduced", "The reproduction fails. Gemini is deriving three repair edits from the broken source and observed evidence.")
            plans, receipt = await generate_repairs(evidence, cause, shop_root, repro)
            receipt["incident_id"] = incident_id
            receipt["at"] = datetime.now(timezone.utc).isoformat()
            (shop_root.parent / "generated-repairs.json").write_text(json.dumps(receipt, indent=2))
            candidates = candidate_views(shop_root, plans)
            verify = verifier.verify_generated
            proposed_message = "Gemini generated three distinct bounded repair patches. None has been executed on the host or declared correct."
        else:
            plans = list(fixture.candidates)
            candidates = build_candidates(shop_root, fixture)
            proposed_message = "Three authored candidate patches are ready for independent verification."
        if plans_store is not None:
            plans_store.update({plan.candidate_id: plan for plan in plans})
        await update("fixes_proposed", proposed_message, candidates=candidates)
        location = "network-disabled Modal sandboxes" if backend_name == "modal" else "separate local working copies"
        await update("verifying", f"Running all three candidates in {location}: reproduction plus regression suite.", candidates=candidates)
        tasks = [asyncio.create_task(verify(shop_root, plan, repro, runs_root)) for plan in plans]
        results = []
        try:
            for finished in asyncio.as_completed(tasks):
                result = await finished
                results.append(result)
                passed = verification_passed(result)
                outcome = "passed" if passed else "failed verification"
                await update("verifying", f"{result.candidate_id} {outcome}: {result.tests_run} tests executed, {result.tests_failed} failed.", results=[result])
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        verified = [result for result in results if verification_passed(result)]
        if verified:
            by_id = {result.candidate_id: result for result in verified}
            winner = next(by_id[candidate.candidate_id] for candidate in candidates if candidate.candidate_id in by_id)
            await update("fix_verified", f"{len(results)} candidates tested. {len(verified)} passed all {winner.tests_run} tests, including the reproduction and regression suite. Approval is required before applying {winner.candidate_id} to the toy shop.", candidates=candidates, results=results)
        else:
            await update("no_fix_found", "No candidate passed both the reproduction and regression suite. The toy shop remains unchanged.", candidates=candidates, results=results)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await update("no_fix_found", f"Investigation stopped: {type(exc).__name__}: {safe_error_detail(exc)}. No patch was applied.")
