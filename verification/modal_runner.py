"""Real, network-disabled Modal verification of authored and generated repairs.

Only Python source from the supplied broken shop snapshot and its reproduction
are uploaded. Host environment variables, keys, git metadata and databases are
never mounted or copied. Failures propagate; this module never chooses a local
fallback. Public signatures match verification.runner.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import Any, AsyncIterator

from agent.fixtures import CandidatePlan
from core.contracts import ReproTest, VerifyResult
from verification.runner import MAX_LOG_BYTES, counts

logger = logging.getLogger(__name__)
SANDBOX_TIMEOUT_S = 60
PROCESS_TIMEOUT_S = 20
MAX_SNAPSHOT_BYTES = 1_000_000
MAX_SNAPSHOT_FILES = 200
PYTEST_VERSION = "8.4.2"
APP_NAME = "voice-incident-war-room-verification"
_resources: tuple[Any, Any] | None = None
_resource_lock = asyncio.Lock()

# The bootstrap is authored code. Payload contents remain data, never shell text.
_BOOTSTRAP = r'''
import json
from pathlib import Path, PurePosixPath
payload = json.loads(Path("/tmp/warroom-input.json").read_text())
root = Path("/workspace")
root.mkdir(exist_ok=True)
for name, content in payload["files"].items():
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Unsafe snapshot path")
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
edit = payload.get("edit")
if edit:
    target = root / "shop" / edit["path"]
    lines = target.read_text().splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if line.strip() == edit["before"]]
    if len(matches) != 1:
        print(json.dumps({"applied": False, "reason": "Authored edit did not match exactly one source line"}))
    else:
        i = matches[0]
        indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
        lines[i] = indent + edit["after"] + ("\n" if lines[i].endswith("\n") else "")
        target.write_text("".join(lines))
        print(json.dumps({"applied": True}))
else:
    print(json.dumps({"applied": True}))
'''


def _safe_python_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.suffix != ".py" or "\\" in value:
        raise ValueError("Verification accepts relative Python source paths only")
    if any(part.startswith(".") for part in path.parts):
        raise ValueError("Hidden paths cannot be sent to a verification sandbox")
    return str(path)


def _snapshot(shop_root: Path, repro: ReproTest, plan: CandidatePlan | None = None) -> tuple[dict, str]:
    """Read the broken checkout once before any remote operation can await."""
    source = shop_root.resolve(strict=True)
    files: dict[str, str] = {}
    size = 0
    for path in sorted(source.rglob("*.py")):
        relative = path.relative_to(source)
        if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError("Symlinks are not permitted in verification source")
        name = "shop/" + _safe_python_path(relative.as_posix())
        content = path.read_text()
        size += len(content.encode())
        files[name] = content
        if size > MAX_SNAPSHOT_BYTES or len(files) > MAX_SNAPSHOT_FILES:
            raise ValueError("Shop snapshot exceeds the bounded upload size")
    if "shop/__init__.py" not in files or "shop/tests/test_shop.py" not in files:
        raise ValueError("Expected toy-shop source and regression suite are missing")
    repro_path = _safe_python_path(repro.path)
    if not repro_path.startswith("tests/"):
        raise ValueError("Reproduction must be inside tests/ outside the original shop suite")
    if len(repro.code.encode()) > 100_000:
        raise ValueError("Reproduction exceeds the bounded upload size")
    files[repro_path] = repro.code
    payload: dict[str, Any] = {"files": files}
    if plan is not None:
        edit_path = _safe_python_path(plan.edit.path)
        if "shop/" + edit_path not in files:
            raise ValueError("Candidate edit targets a file absent from the source snapshot")
        payload["edit"] = {"path": edit_path, "before": plan.edit.before, "after": plan.edit.after}
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return payload, fingerprint


async def prepare() -> dict[str, str]:
    """Authenticate and eagerly build/cache the small dependency image."""
    app, image = await _get_resources()
    return {"backend": "modal", "app": APP_NAME, "image_id": image.object_id, "pytest": PYTEST_VERSION}


async def _get_resources() -> tuple[Any, Any]:
    global _resources
    if _resources is not None:
        return _resources
    async with _resource_lock:
        if _resources is not None:
            return _resources
        try:
            modal = importlib.import_module("modal")
        except ImportError as exc:
            raise RuntimeError("Modal backend requires the project dependency: install requirements.txt into .venv") from exc
        # SDK reads its own local credential profile. No credential is passed to the image or sandbox.
        app = await modal.App.lookup.aio(os.environ.get("MODAL_APP_NAME", APP_NAME), create_if_missing=True)
        image = modal.Image.debian_slim(python_version="3.12").pip_install(f"pytest=={PYTEST_VERSION}")
        image = await image.build.aio(app)
        _resources = app, image
        return _resources


async def _cleanup(sandbox: Any) -> None:
    """Try both remote termination and local connection cleanup on every exit."""
    try:
        await sandbox.terminate.aio()
    finally:
        await sandbox.detach.aio()


@asynccontextmanager
async def _sandbox() -> AsyncIterator[Any]:
    app, image = await _get_resources()
    modal = importlib.import_module("modal")
    creation = asyncio.create_task(modal.Sandbox.create.aio(
        app=app, image=image, timeout=SANDBOX_TIMEOUT_S, cpu=(0.25, 1.0), memory=(256, 512),
        block_network=True, secrets=[], include_oidc_identity_token=False,
    ))
    try:
        sandbox = await asyncio.shield(creation)
    except asyncio.CancelledError:
        # Creation may already have reached Modal; retrieve the handle and stop it.
        try:
            sandbox = await creation
        except Exception:
            logger.exception("Modal sandbox creation failed while cancellation was pending")
        else:
            await _cleanup(sandbox)
        raise
    try:
        yield sandbox
    finally:
        # Cancellation must not skip cleanup. The cloud lifetime is also bounded to 60s.
        cleanup = asyncio.create_task(_cleanup(sandbox))
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await cleanup
            raise


async def _exec(sandbox: Any, args: list[str], *, cwd: str | None = None) -> tuple[int, str]:
    process = await sandbox.exec.aio(
        *args, timeout=PROCESS_TIMEOUT_S, workdir=cwd,
        env={"PYTHONPATH": "/workspace", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
    )
    stdout, stderr, code = await asyncio.gather(process.stdout.read.aio(), process.stderr.read.aio(), process.wait.aio())
    # Read streams concurrently to avoid blocking on a full stderr pipe.
    return code, (stdout + ("\n" + stderr if stderr else ""))[-MAX_LOG_BYTES:]


async def _upload(sandbox: Any, payload: dict) -> tuple[bool, str]:
    await sandbox.filesystem.write_text.aio(json.dumps(payload), "/tmp/warroom-input.json")
    code, output = await _exec(sandbox, ["python", "-c", _BOOTSTRAP])
    if code:
        raise RuntimeError(f"Modal snapshot setup failed: {output[-2000:]}")
    try:
        result = json.loads(output.strip())
        return result["applied"] is True, result.get("reason", "")
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("Modal snapshot setup returned an invalid response") from exc


async def _pytest(sandbox: Any, target: str) -> tuple[int, str]:
    return await _exec(sandbox, ["python", "-m", "pytest", target, "-q", "--tb=short", "--disable-warnings", "-p", "no:cacheprovider", "-o", "addopts="], cwd="/workspace")


async def check_reproduction(shop_root: Path, repro: ReproTest, runs_root: Path) -> tuple[bool, str]:
    payload, fingerprint = _snapshot(shop_root, repro)
    async with _sandbox() as sandbox:
        await _upload(sandbox, payload)
        code, output = await _pytest(sandbox, repro.path)
        run, failed = counts(output)
        prefix = f"MODAL SANDBOX {sandbox.object_id}\nBROKEN SNAPSHOT sha256:{fingerprint}\n"
        # Pytest exit 1 with exactly one failed test; collection errors/timeouts do not count.
        return code == 1 and run == 1 and failed == 1 and "ERROR collecting" not in output, prefix + output


async def verify_candidate(shop_root: Path, plan: CandidatePlan, repro: ReproTest, runs_root: Path, *, apply: bool = True) -> VerifyResult:
    started = time.perf_counter()
    payload, fingerprint = _snapshot(shop_root, repro, plan if apply else None)
    async with _sandbox() as sandbox:
        applied, reason = await _upload(sandbox, payload)
        prefix = f"MODAL SANDBOX {sandbox.object_id}\nBROKEN SNAPSHOT sha256:{fingerprint}\n"
        if not applied:
            return VerifyResult(candidate_id=plan.candidate_id, applied=False, repro_passed=False, suite_passed=False, tests_run=0, tests_failed=0, duration_s=round(time.perf_counter() - started, 3), log_tail=prefix + reason)
        repro_code, repro_output = await _pytest(sandbox, repro.path)
        suite_code, suite_output = await _pytest(sandbox, "shop/tests")
        repro_run, repro_failed = counts(repro_output)
        suite_run, suite_failed = counts(suite_output)
        return VerifyResult(
            candidate_id=plan.candidate_id, applied=True,
            repro_passed=repro_code == 0 and repro_run > 0 and repro_failed == 0,
            suite_passed=suite_code == 0 and suite_run > 0 and suite_failed == 0,
            tests_run=repro_run + suite_run, tests_failed=repro_failed + suite_failed,
            duration_s=round(time.perf_counter() - started, 3),
            log_tail=(prefix + "REPRODUCTION\n" + repro_output + "\nREGRESSION SUITE\n" + suite_output)[-MAX_LOG_BYTES:],
        )


def _generated_payload(shop_root: Path, plan, repro: ReproTest, *, applied: bool = False) -> tuple[dict, str]:
    from agent.fixtures import FIXTURES, repro_for
    from verification.generated import validated_snapshot

    # Reproductions are authored trusted fixtures, not model-supplied test code.
    trusted = [repro_for(fixture) for fixture in FIXTURES.values()]
    if not any(repro.path == item.path and repro.code == item.code for item in trusted):
        raise ValueError("Generated verification requires an unchanged trusted reproduction")
    base, patched = validated_snapshot(shop_root, plan, applied=applied)
    selected = patched if applied else base
    payload = {"files": {"shop/" + name: content for name, content in selected.items()}}
    payload["files"][repro.path] = repro.code
    if not applied:
        payload["edit"] = {"path": plan.edit.path, "before": plan.edit.before.strip(), "after": plan.edit.after.strip()}
    return payload, plan.base_sha256


async def _generated_check(shop_root: Path, plan, repro: ReproTest, *, applied: bool, recovery: bool) -> tuple[VerifyResult, dict]:
    started = time.perf_counter()
    payload, fingerprint = _generated_payload(shop_root, plan, repro, applied=applied)
    async with _sandbox() as sandbox:
        edit_applied, reason = await _upload(sandbox, payload)
        prefix = f"MODAL GENERATED VERIFICATION {sandbox.object_id}\nBROKEN SNAPSHOT sha256:{fingerprint}\n"
        if not edit_applied:
            return VerifyResult(candidate_id=plan.candidate_id, applied=False, repro_passed=False, suite_passed=False, tests_run=0, tests_failed=0, duration_s=round(time.perf_counter() - started, 3), log_tail=prefix + reason), {}
        repro_code, repro_output = await _pytest(sandbox, repro.path)
        suite_code, suite_output = await _pytest(sandbox, "shop/tests")
        repro_run, repro_failed = counts(repro_output)
        suite_run, suite_failed = counts(suite_output)
        result = VerifyResult(
            candidate_id=plan.candidate_id, applied=True,
            repro_passed=repro_code == 0 and repro_run == 1 and repro_failed == 0,
            suite_passed=suite_code == 0 and suite_run == 24 and suite_failed == 0,
            tests_run=repro_run + suite_run, tests_failed=repro_failed + suite_failed,
            duration_s=round(time.perf_counter() - started, 3),
            log_tail=(prefix + "REPRODUCTION\n" + repro_output + "\nREGRESSION SUITE\n" + suite_output)[-MAX_LOG_BYTES:],
        )
        healthy: dict = {}
        if recovery and result.repro_passed and result.suite_passed:
            code, output = await _exec(sandbox, ["python", "-m", "shop.probe"], cwd="/workspace")
            if code:
                raise RuntimeError("Generated recovery probe failed inside Modal")
            try:
                healthy = json.loads(output)
            except (ValueError, TypeError) as exc:
                raise RuntimeError("Generated recovery probe returned invalid JSON") from exc
            if (not isinstance(healthy, dict) or healthy.get("requests") != 12
                or not isinstance(healthy.get("records"), list) or len(healthy["records"]) != 12
                or type(healthy.get("failed")) is not int
                or any(not isinstance(record, dict) or type(record.get("ok")) is not bool for record in healthy["records"])
                or healthy["failed"] != sum(not record["ok"] for record in healthy["records"])):
                raise RuntimeError("Generated recovery probe returned inconsistent checkout counts")
            result.log_tail += f"\nREMOTE CHECKOUT PROBE\n{healthy['requests']} requests; {healthy['failed']} failed.\n"
        result.duration_s = round(time.perf_counter() - started, 3)
        return result, healthy


async def verify_generated(shop_root: Path, plan, repro: ReproTest, runs_root: Path, *, apply: bool = True) -> VerifyResult:
    """Execute a screened Gemini-authored edit only inside a fresh Modal sandbox."""
    result, _ = await _generated_check(shop_root, plan, repro, applied=not apply, recovery=False)
    return result


async def verify_generated_recovery(shop_root: Path, plan, repro: ReproTest, runs_root: Path) -> tuple[VerifyResult, dict]:
    """Test and probe already-applied generated source exclusively inside Modal."""
    return await _generated_check(shop_root, plan, repro, applied=True, recovery=True)
