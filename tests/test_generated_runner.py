"""Generated-source screening and remote-only execution contracts; no paid calls."""
import asyncio
import shutil
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.fixtures import FIXTURES, apply_edit, repro_for
from core.contracts import ReproTest
from verification.generated import (
    GeneratedEdit, GeneratedPlan, apply_generated_plan, generated_patch,
    snapshot_sha256, validate_generated_plan, validated_snapshot,
)
from verification import modal_runner


@pytest.fixture
def broken(tmp_path):
    def make(fault="bad_config"):
        source = tmp_path / fault / "shop"
        shutil.copytree(Path(__file__).parents[1] / "shop", source, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        apply_edit(source, FIXTURES[fault].edit)
        return source
    return make


def plan_for(root, fault="bad_config", after=None):
    fixture = FIXTURES[fault]
    return GeneratedPlan("gen-1", "Generated repair", "Restore tested checkout behavior", GeneratedEdit(fixture.edit.path, fixture.edit.after, after or fixture.edit.before), snapshot_sha256(root))


def test_generated_numeric_assignment_and_diff_match_snapshot(broken):
    root = broken()
    plan = plan_for(root, after="PAYMENT_TIMEOUT_MS = 1000 * 3")
    validate_generated_plan(root, plan)
    patch = generated_patch(root, plan)
    assert "+PAYMENT_TIMEOUT_MS = 1000 * 3" in patch
    assert "-PAYMENT_TIMEOUT_MS = 3" in patch
    assert "PAYMENT_TIMEOUT_MS = 3\n" in (root / "app/config.py").read_text()


@pytest.mark.parametrize("expression", [
    "cart.coupon.code if cart.coupon is not None else None",
    'getattr(cart.coupon, "code", None)',
    "cart.coupon and cart.coupon.code",
])
def test_generated_safe_coupon_expressions_are_allowed(broken, expression):
    root = broken("null_error")
    validate_generated_plan(root, plan_for(root, "null_error", "coupon_code = " + expression))


@pytest.mark.parametrize("after", [
    "PAYMENT_TIMEOUT_MS = __import__('os').system('echo unsafe')",
    "PAYMENT_TIMEOUT_MS = open('/tmp/secret').read()",
    "PAYMENT_TIMEOUT_MS = 3000; import os",
    "PAYMENT_TIMEOUT_MS = eval('3000')",
    "PAYMENT_TIMEOUT_MS = [x for x in range(1)]",
    "PAYMENT_TIMEOUT_MS = (lambda: 3000)()",
    "PAYMENT_TIMEOUT_MS = globals()",
    "PAYMENT_TIMEOUT_MS = 10 ** 1000000000",
    "DIFFERENT_TARGET = 3000",
    "PAYMENT_TIMEOUT_MS = 3000\nimport pytest",
])
def test_generated_unsafe_structures_are_rejected_without_execution(broken, after):
    root = broken()
    with pytest.raises(ValueError):
        validate_generated_plan(root, plan_for(root, after=after))


def test_private_getattr_and_nonliteral_attribute_are_rejected(broken):
    root = broken("null_error")
    for expr in ['getattr(cart.coupon, "__class__", None)', 'getattr(cart.coupon, cart.coupon.code, None)']:
        with pytest.raises(ValueError):
            validate_generated_plan(root, plan_for(root, "null_error", "coupon_code = " + expr))


@pytest.mark.parametrize("path", ["../app/config.py", "/tmp/config.py", "tests/test_shop.py", "app/__init__.py", "app/conftest.py", "app/new.py", "app/../app/config.py", "app//config.py"])
def test_generated_edit_cannot_target_tests_new_files_or_noncanonical_paths(broken, path):
    root = broken()
    plan = plan_for(root)
    with pytest.raises(ValueError):
        validate_generated_plan(root, replace(plan, edit=replace(plan.edit, path=path)))


def test_changed_snapshot_is_rejected_before_remote_creation(broken, monkeypatch, tmp_path):
    root = broken()
    plan = plan_for(root)
    (root / "app/config.py").write_text("PAYMENT_TIMEOUT_MS = 4\n")
    async def forbidden():
        raise AssertionError("Cannot create a sandbox for stale source")
    monkeypatch.setattr(modal_runner, "_sandbox", forbidden)
    with pytest.raises(ValueError, match="snapshot"):
        asyncio.run(modal_runner.verify_generated(root, plan, repro_for(FIXTURES["bad_config"]), tmp_path))


def test_tampered_tests_and_probes_cannot_enter_generated_verification(broken):
    root = broken()
    (root / "tests/test_shop.py").write_text("def test_fake():\n    pass\n")
    with pytest.raises(ValueError, match="Trusted"):
        validate_generated_plan(root, plan_for(root))


def test_symlink_source_is_rejected(broken, tmp_path):
    root = broken()
    original = root / "app/config.py"
    external = tmp_path / "external.py"
    external.write_text(original.read_text())
    original.unlink()
    original.symlink_to(external)
    with pytest.raises(ValueError, match="Symlinks"):
        snapshot_sha256(root)


def test_symlink_root_and_oversized_source_are_rejected(broken, tmp_path):
    root = broken()
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="Symlinks"):
        snapshot_sha256(alias)
    (root / "app/config.py").write_text("#" * 64001)
    with pytest.raises(ValueError, match="bounded snapshot"):
        snapshot_sha256(root)


def test_last_moment_target_symlink_cannot_redirect_generated_write(broken, tmp_path, monkeypatch):
    from verification import generated
    root = broken()
    plan = plan_for(root)
    actual_validate = generated.validated_snapshot
    outside = tmp_path / "outside.py"
    outside.write_text("PRESERVE = True\n")
    def swap_after_validation(*args, **kwargs):
        result = actual_validate(*args, **kwargs)
        (root / plan.edit.path).unlink()
        (root / plan.edit.path).symlink_to(outside)
        return result
    monkeypatch.setattr(generated, "validated_snapshot", swap_after_validation)
    with pytest.raises(OSError):
        apply_generated_plan(root, plan)
    assert outside.read_text() == "PRESERVE = True\n"


def test_applied_validation_reverses_edit_and_detects_unrelated_source_drift(broken):
    root = broken()
    plan = plan_for(root)
    apply_generated_plan(root, plan)
    base, patched = validated_snapshot(root, plan, applied=True)
    assert "PAYMENT_TIMEOUT_MS = 3\n" in base["app/config.py"]
    assert "PAYMENT_TIMEOUT_MS = 3000\n" in patched["app/config.py"]
    with (root / "app/catalog.py").open("a") as stream:
        stream.write("\nCHANGED = True\n")
    with pytest.raises(ValueError, match="snapshot"):
        validated_snapshot(root, plan, applied=True)


def test_added_repro_is_trusted_and_not_part_of_common_source_digest(broken):
    root = broken()
    plan = plan_for(root)
    repro = repro_for(FIXTURES["bad_config"])
    payload, fingerprint = modal_runner._generated_payload(root, plan, repro)
    assert fingerprint == snapshot_sha256(root) == plan.base_sha256
    assert payload["files"][repro.path] == repro.code
    with pytest.raises(ValueError, match="unchanged trusted reproduction"):
        modal_runner._generated_payload(root, plan, ReproTest(path=repro.path, code="def test_forged(): pass"))


def test_generated_recovery_runs_test_and_probe_commands_only_in_modal(broken, monkeypatch, tmp_path):
    root = broken()
    plan = plan_for(root)
    apply_generated_plan(root, plan)
    commands = []
    lifecycle = []
    @asynccontextmanager
    async def sandbox():
        try:
            yield SimpleNamespace(object_id="sb-generated-test")
        finally:
            lifecycle.append("terminated")
    async def upload(remote, payload):
        assert "edit" not in payload
        assert "PAYMENT_TIMEOUT_MS = 3000" in payload["files"]["shop/app/config.py"]
        return True, ""
    async def pytest_remote(remote, target):
        commands.append(target)
        return (0, "24 passed in 0.01s") if target == "shop/tests" else (0, "1 passed in 0.01s")
    async def exec_remote(remote, args, *, cwd):
        import json
        commands.append(args)
        assert cwd == "/workspace"
        return 0, json.dumps({"requests": 12, "failed": 0, "error_rate": 0, "records": [{"ok": True}] * 12})
    monkeypatch.setattr(modal_runner, "_sandbox", sandbox)
    monkeypatch.setattr(modal_runner, "_upload", upload)
    monkeypatch.setattr(modal_runner, "_pytest", pytest_remote)
    monkeypatch.setattr(modal_runner, "_exec", exec_remote)
    result, healthy = asyncio.run(modal_runner.verify_generated_recovery(root, plan, repro_for(FIXTURES["bad_config"]), tmp_path))
    assert result.applied and result.repro_passed and result.suite_passed
    assert result.tests_run == 25 and result.tests_failed == 0
    assert healthy["failed"] == 0
    assert commands[-1] == ["python", "-m", "shop.probe"]
    assert plan.base_sha256 in result.log_tail
    assert lifecycle == ["terminated"]


def test_generated_verification_does_not_accept_missing_regression_cases(broken, monkeypatch, tmp_path):
    root = broken()
    plan = plan_for(root)
    @asynccontextmanager
    async def sandbox(): yield SimpleNamespace(object_id="sb-test")
    async def upload(*args): return True, ""
    async def run(remote, target): return 0, "1 passed in 0.01s"
    monkeypatch.setattr(modal_runner, "_sandbox", sandbox)
    monkeypatch.setattr(modal_runner, "_upload", upload)
    monkeypatch.setattr(modal_runner, "_pytest", run)
    result = asyncio.run(modal_runner.verify_generated(root, plan, repro_for(FIXTURES["bad_config"]), tmp_path))
    assert result.repro_passed and not result.suite_passed
    assert result.tests_run == 2
