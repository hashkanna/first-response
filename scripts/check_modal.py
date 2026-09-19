"""Bounded real cloud check: `python -m scripts.check_modal [--fault bad_config]`."""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from agent.fixtures import FIXTURES, apply_edit, repro_for
from verification.modal_runner import check_reproduction, prepare, verify_candidate


async def main() -> None:
    parser = argparse.ArgumentParser(description="Warm Modal and prove a real broken reproduction plus three candidate patches.")
    parser.add_argument("--fault", choices=sorted(FIXTURES), default="bad_config")
    parser.add_argument("--prepare-only", action="store_true", help="Authenticate and build the cached image without running shop code")
    args = parser.parse_args()
    environment = await prepare()
    print(json.dumps(environment), flush=True)
    if args.prepare_only:
        return
    root = Path(__file__).resolve().parents[1]
    fixture = FIXTURES[args.fault]
    with tempfile.TemporaryDirectory(prefix="warroom-modal-check-") as temporary:
        snapshot = Path(temporary) / "shop"
        shutil.copytree(root / "shop", snapshot, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
        apply_edit(snapshot, fixture.edit)
        repro = repro_for(fixture)
        failed, output = await check_reproduction(snapshot, repro, Path(temporary))
        print(json.dumps({"fault": args.fault, "broken_reproduction_failed": failed, "log_tail": output}), flush=True)
        if not failed:
            raise RuntimeError("Broken-code reproduction did not fail as expected")
        tasks = [asyncio.create_task(verify_candidate(snapshot, plan, repro, Path(temporary))) for plan in fixture.candidates]
        try:
            results = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        for result in results:
            print(result.model_dump_json(), flush=True)
        winners = [result for result in results if result.applied and result.repro_passed and result.suite_passed]
        if len(winners) != 1:
            raise RuntimeError(f"Expected one verified authored patch, got {len(winners)}")
        receipt = root / ".runtime" / "modal-checks" / f"{args.fault}.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps({
            "checked_at": datetime.now(timezone.utc).isoformat(), "environment": environment,
            "fault": args.fault, "broken_reproduction_failed": failed, "reproduction_log": output,
            "results": [result.model_dump() for result in results],
            "verified_candidate": winners[0].candidate_id, "sandbox_cleanup": "completed",
        }, indent=2) + "\n")
        print(json.dumps({"verified_candidate": winners[0].candidate_id, "checks": winners[0].tests_run, "sandbox_cleanup": "completed", "receipt": str(receipt)}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
