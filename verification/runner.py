"""Run trusted fixtures in separate local working directories.

These directories are NOT security sandboxes. Only the fixed, reviewed code in
agent.fixtures and shop is executed. Never route arbitrary generated code here.
"""

import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

from agent.fixtures import CandidatePlan, FIXTURES, apply_edit, repro_for
from core.contracts import ReproTest, VerifyResult

MAX_LOG_BYTES = 24_000
RUN_TIMEOUT_S = 20


def copy_shop(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"))


def assert_authored_source(shop_root: Path) -> None:
    """Only the checked-in shop and its two reviewed faults may run locally."""
    from verification.generated import TRUSTED_SHOP, snapshot_files

    actual = snapshot_files(shop_root)
    clean = snapshot_files(TRUSTED_SHOP)
    allowed = [clean]
    for fixture in FIXTURES.values():
        changed = dict(clean)
        original = changed[fixture.edit.path]
        changed[fixture.edit.path] = original.replace(fixture.edit.before, fixture.edit.after, 1)
        allowed.append(changed)
    if actual not in allowed:
        raise ValueError("Local execution is restricted to reviewed authored shop snapshots; generated or modified source requires Modal.")


def assert_authored_reproduction(repro: ReproTest) -> None:
    if not any(repro.path == known.path and repro.code == known.code for known in (repro_for(fixture) for fixture in FIXTURES.values())):
        raise ValueError("Local execution accepts only exact reviewed reproduction fixtures; generated tests require Modal.")


async def run_process(cwd: Path, args: list[str], timeout: float = RUN_TIMEOUT_S) -> tuple[int, str]:
    # Deliberately omit provider credentials and other ambient application secrets.
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(cwd),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "LANG": "en_US.UTF-8",
    }
    process = await asyncio.create_subprocess_exec(sys.executable, *args, cwd=cwd, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    tail = bytearray()

    async def collect() -> None:
        assert process.stdout is not None
        while chunk := await process.stdout.read(4096):
            tail.extend(chunk)
            if len(tail) > MAX_LOG_BYTES:
                del tail[:-MAX_LOG_BYTES]
        await process.wait()

    try:
        await asyncio.wait_for(collect(), timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
        if process.returncode is None:
            process.kill()
        await process.wait()
        if isinstance(exc, asyncio.CancelledError):
            raise
        return 124, tail.decode(errors="replace") + f"\nExecution exceeded {timeout:g} seconds."
    return process.returncode or 0, tail.decode(errors="replace")


def counts(output: str) -> tuple[int, int]:
    # Read only pytest's final summary; traceback text can contain these words too.
    summary = next((line for line in reversed(output.splitlines()) if re.search(r"\d+ (?:passed|failed|error)", line)), "")
    numbers = {name: int(value) for value, name in re.findall(r"(\d+) (passed|failed|errors?|skipped)", summary)}
    failed = numbers.get("failed", 0) + numbers.get("error", 0) + numbers.get("errors", 0)
    return sum(numbers.values()), failed


async def run_pytest(cwd: Path, target: str) -> tuple[int, str]:
    return await run_process(cwd, ["-m", "pytest", target, "-q", "--tb=short", "--disable-warnings", "-p", "no:cacheprovider", "-o", "addopts="])


async def probe_shop(shop_root: Path) -> dict:
    assert_authored_source(shop_root)
    code, output = await run_process(shop_root.parent, ["-m", "shop.probe"])
    if code:
        raise RuntimeError(f"Shop probe failed to run: {output[-2000:]}")
    return json.loads(output)


async def check_reproduction(shop_root: Path, repro: ReproTest, runs_root: Path) -> tuple[bool, str]:
    assert_authored_source(shop_root)
    assert_authored_reproduction(repro)
    runs_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="reproduce-", dir=runs_root) as temp:
        cwd = Path(temp)
        copy_shop(shop_root, cwd / "shop")
        target = cwd / repro.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(repro.code)
        code, output = await run_pytest(cwd, repro.path)
        run, failed = counts(output)
        # A collection error or timeout is not a successful reproduction.
        return code == 1 and run == 1 and failed == 1 and "ERROR collecting" not in output, output


async def verify_candidate(shop_root: Path, plan: CandidatePlan, repro: ReproTest, runs_root: Path, *, apply: bool = True) -> VerifyResult:
    if not isinstance(plan, CandidatePlan) or not any(plan in fixture.candidates for fixture in FIXTURES.values()):
        raise ValueError("Local verification accepts only authored CandidatePlan fixtures; generated edits require Modal.")
    assert_authored_source(shop_root)
    assert_authored_reproduction(repro)
    started = time.perf_counter()
    runs_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{plan.candidate_id}-", dir=runs_root) as temp:
        cwd = Path(temp)
        copy_shop(shop_root, cwd / "shop")
        try:
            if apply:
                apply_edit(cwd / "shop", plan.edit)
        except (ValueError, OSError) as exc:
            return VerifyResult(candidate_id=plan.candidate_id, applied=False, repro_passed=False, suite_passed=False, tests_run=0, tests_failed=0, duration_s=round(time.perf_counter() - started, 3), log_tail=str(exc))
        target = cwd / repro.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(repro.code)
        repro_code, repro_output = await run_pytest(cwd, repro.path)
        suite_code, suite_output = await run_pytest(cwd, "shop/tests")
        repro_run, repro_failed = counts(repro_output)
        suite_run, suite_failed = counts(suite_output)
        return VerifyResult(
            candidate_id=plan.candidate_id, applied=True,
            repro_passed=repro_code == 0 and repro_run > 0 and repro_failed == 0,
            suite_passed=suite_code == 0 and suite_run > 0 and suite_failed == 0,
            tests_run=repro_run + suite_run, tests_failed=repro_failed + suite_failed,
            duration_s=round(time.perf_counter() - started, 3),
            log_tail=("REPRODUCTION\n" + repro_output + "\nREGRESSION SUITE\n" + suite_output)[-MAX_LOG_BYTES:],
        )
