import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from core.contracts import IncidentUpdate
from core.hub import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "runtime")) as client:
        yield client


def wait_for_stage(client, wanted):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        status = client.get("/status").json()
        if status["stage"] == wanted:
            return status
        if status["stage"] == "no_fix_found":
            pytest.fail(str(status["events"][-1]))
        time.sleep(0.02)
    pytest.fail(f"Did not reach {wanted}")


def test_health_and_validation(client):
    assert client.get("/health").json()["mode"] == "deterministic-local"
    assert client.post("/say", json={"text": ""}).status_code == 422
    assert client.post("/say", json={"text": "status", "inject": True}).status_code == 422
    assert client.post("/faults/not-a-fault/apply").status_code == 404
    assert client.post("/approve", json={"candidate_id": "timeout-restore"}).status_code == 422
    assert client.get("/artifacts/nope.patch").status_code == 404


def test_api_pipeline_patch_and_websocket_replay(client):
    response = client.post("/faults/bad_config/apply")
    assert response.status_code == 200
    status = wait_for_stage(client, "fix_verified")
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json() == {"type": "reset"}
        events = [ws.receive_json() for _ in status["events"]]
        assert events == status["events"]
        ws.send_json({"stage": "resolved", "incident_id": status["incident_id"]})
        assert client.get("/status").json()["stage"] == "fix_verified"
        result = client.post("/approve", json={"incident_id": status["incident_id"], "candidate_id": "timeout-restore"})
        assert result.status_code == 200
        assert ws.receive_json()["stage"] == "resolved"
    patch = client.get(result.json()["artifact_url"])
    assert patch.status_code == 200
    assert "+PAYMENT_TIMEOUT_MS = 3000" in patch.text
    assert client.post("/faults/reset").json()["ok"]
    assert client.get("/status").json()["events"] == []


def test_untrusted_origins_cannot_mutate_or_connect(client):
    assert client.post("/faults/reset", headers={"Origin": "https://evil.example"}).status_code == 403
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"Origin": "https://evil.example"}):
            pass
    assert client.post("/faults/reset", headers={"Origin": "http://localhost:5173"}).status_code == 200


def test_contract_array_defaults_are_independent():
    from datetime import datetime, timezone
    first = IncidentUpdate(incident_id="a", stage="alerted", at=datetime.now(timezone.utc), message="a")
    second = IncidentUpdate(incident_id="b", stage="alerted", at=datetime.now(timezone.utc), message="b")
    first.results.append(None)
    assert not second.results
