"""Offline contract and lifecycle checks; these tests spend no Modal credits."""
import asyncio
import json
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.fixtures import FIXTURES, apply_edit, repro_for
from core.contracts import ReproTest
from verification import modal_runner as runner


@pytest.fixture
def broken_shop(tmp_path):
    destination = tmp_path / "shop"
    shutil.copytree(Path(__file__).parents[1] / "shop", destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    apply_edit(destination, FIXTURES["bad_config"].edit)
    return destination


def test_snapshot_excludes_credentials_and_other_data(broken_shop):
    (broken_shop / ".env").write_text("SECRET=this-should-not-leave")
    (broken_shop / "orders.sqlite3").write_bytes(b"private-data")
    payload, digest = runner._snapshot(broken_shop, repro_for(FIXTURES["bad_config"]))
    assert len(digest) == 64
    assert all(name.endswith(".py") for name in payload["files"])
    assert "this-should-not-leave" not in json.dumps(payload)
    assert "PAYMENT_TIMEOUT_MS = 3\n" in payload["files"]["shop/app/config.py"]


@pytest.mark.parametrize("path", ["../test_repro.py", "/tmp/test.py", "shop/app/config.py", "tests/.hidden.py"])
def test_snapshot_rejects_unsafe_reproduction_paths(broken_shop, path):
    with pytest.raises(ValueError):
        runner._snapshot(broken_shop, ReproTest(path=path, code="pass"))


def test_snapshot_rejects_symlink_source(broken_shop, tmp_path):
    outside = tmp_path / "secret.py"
    outside.write_text("PRIVATE = 1")
    (broken_shop / "app" / "outside.py").symlink_to(outside)
    with pytest.raises(ValueError, match="Symlinks"):
        runner._snapshot(broken_shop, repro_for(FIXTURES["bad_config"]))


def test_snapshot_is_independent_of_later_runtime_mutation(broken_shop):
    payload, digest = runner._snapshot(broken_shop, repro_for(FIXTURES["bad_config"]))
    (broken_shop / "app" / "config.py").write_text("PAYMENT_TIMEOUT_MS = 999\n")
    assert "PAYMENT_TIMEOUT_MS = 3\n" in payload["files"]["shop/app/config.py"]
    assert len(digest) == 64


def mock_sandbox(monkeypatch):
    state = {"terminated": 0}
    @asynccontextmanager
    async def sandbox():
        try:
            yield SimpleNamespace(object_id="sb-test")
        finally:
            state["terminated"] += 1
    monkeypatch.setattr(runner, "_sandbox", sandbox)
    async def upload(*args):
        return True, ""
    monkeypatch.setattr(runner, "_upload", upload)
    return state


def test_verified_result_requires_real_success_codes_and_test_counts(monkeypatch, broken_shop, tmp_path):
    state = mock_sandbox(monkeypatch)
    outputs = iter([(0, "1 passed in 0.01s"), (0, "24 passed in 0.01s")])
    async def run(*args):
        return next(outputs)
    monkeypatch.setattr(runner, "_pytest", run)
    fixture = FIXTURES["bad_config"]
    result = asyncio.run(runner.verify_candidate(broken_shop, fixture.candidates[-1], repro_for(fixture), tmp_path))
    assert result.applied and result.repro_passed and result.suite_passed
    assert result.tests_run == 25 and result.tests_failed == 0
    assert "MODAL SANDBOX sb-test" in result.log_tail
    assert state["terminated"] == 1


def test_reproduction_collection_error_is_not_a_reproduced_failure(monkeypatch, broken_shop, tmp_path):
    state = mock_sandbox(monkeypatch)
    async def run(*args):
        return 2, "ERROR collecting test_repro.py\n1 error in 0.01s"
    monkeypatch.setattr(runner, "_pytest", run)
    failed, output = asyncio.run(runner.check_reproduction(broken_shop, repro_for(FIXTURES["bad_config"]), tmp_path))
    assert not failed
    assert state["terminated"] == 1


def test_failed_patch_never_runs_tests(monkeypatch, broken_shop, tmp_path):
    state = mock_sandbox(monkeypatch)
    async def upload(*args):
        return False, "No matching authored line"
    async def run(*args):
        raise AssertionError("Tests cannot run after edit failure")
    monkeypatch.setattr(runner, "_upload", upload)
    monkeypatch.setattr(runner, "_pytest", run)
    fixture = FIXTURES["bad_config"]
    result = asyncio.run(runner.verify_candidate(broken_shop, fixture.candidates[-1], repro_for(fixture), tmp_path))
    assert not result.applied and not result.repro_passed and not result.suite_passed
    assert result.tests_run == 0
    assert state["terminated"] == 1


def test_remote_error_propagates_and_cleans_up(monkeypatch, broken_shop, tmp_path):
    state = mock_sandbox(monkeypatch)
    async def run(*args):
        raise RuntimeError("Remote infrastructure unavailable")
    monkeypatch.setattr(runner, "_pytest", run)
    with pytest.raises(RuntimeError, match="Remote infrastructure"):
        asyncio.run(runner.check_reproduction(broken_shop, repro_for(FIXTURES["bad_config"]), tmp_path))
    assert state["terminated"] == 1


def test_modal_settings_and_cleanup_on_cancellation(monkeypatch):
    calls = []
    async def terminate(): calls.append("terminate")
    async def detach(): calls.append("detach")
    sandbox = SimpleNamespace(terminate=SimpleNamespace(aio=terminate), detach=SimpleNamespace(aio=detach))
    async def create(**kwargs):
        assert kwargs["block_network"] is True
        assert kwargs["timeout"] == 60
        assert kwargs["secrets"] == []
        assert kwargs["include_oidc_identity_token"] is False
        assert kwargs["cpu"] == (0.25, 1.0)
        return sandbox
    async def resources(): return object(), object()
    monkeypatch.setattr(runner, "_get_resources", resources)
    monkeypatch.setattr(runner.importlib, "import_module", lambda name: SimpleNamespace(Sandbox=SimpleNamespace(create=SimpleNamespace(aio=create))))
    async def cancel():
        async with runner._sandbox():
            raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cancel())
    assert calls == ["terminate", "detach"]


def test_detach_still_runs_when_termination_fails():
    calls = []
    async def terminate():
        calls.append("terminate")
        raise RuntimeError("Lost network")
    async def detach(): calls.append("detach")
    sandbox = SimpleNamespace(terminate=SimpleNamespace(aio=terminate), detach=SimpleNamespace(aio=detach))
    with pytest.raises(RuntimeError, match="Lost network"):
        asyncio.run(runner._cleanup(sandbox))
    assert calls == ["terminate", "detach"]
