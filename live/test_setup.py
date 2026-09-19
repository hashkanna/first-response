import os
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from live.setup import create_setup_router


def browser(monkeypatch, enabled=True, client_host="127.0.0.1"):
    monkeypatch.setenv("WAR_ROOM_ENABLE_SETUP", "1" if enabled else "0")
    app = FastAPI()
    app.include_router(create_setup_router())
    return TestClient(app, base_url="http://127.0.0.1:8000", client=(client_host, 50000))


def setup_form(client):
    response = client.get("/setup")
    assert response.status_code == 200
    return re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)


HEADERS = {"origin": "http://127.0.0.1:8000", "referer": "http://127.0.0.1:8000/setup"}
FAKE_KEY = "AIza" + "a" * 35


def test_setup_is_disabled_by_default_and_rejects_non_loopback(monkeypatch):
    assert browser(monkeypatch, enabled=False).get("/setup").status_code == 404
    assert browser(monkeypatch, client_host="192.0.2.20").get("/setup").status_code == 403


def test_key_is_accepted_once_in_memory_and_never_echoed(monkeypatch, caplog):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = browser(monkeypatch)
    csrf = setup_form(client)
    response = client.post("/setup", data={"csrf": csrf, "key": FAKE_KEY}, headers=HEADERS)
    assert response.status_code == 200
    assert os.environ["GEMINI_API_KEY"] == FAKE_KEY
    assert FAKE_KEY not in response.text
    assert FAKE_KEY not in caplog.text
    assert response.headers["cache-control"] == "no-store"
    assert client.post("/setup", data={"csrf": csrf, "key": FAKE_KEY}, headers=HEADERS).status_code == 403


def test_wrong_origin_referer_and_csrf_cannot_change_credentials(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = browser(monkeypatch)
    csrf = setup_form(client)
    for headers, nonce in [
        ({**HEADERS, "origin": "https://attacker.example"}, csrf),
        ({**HEADERS, "referer": "http://127.0.0.1:8000/other"}, csrf),
        ({"origin": HEADERS["origin"]}, csrf), (HEADERS, "incorrect"),
    ]:
        assert client.post("/setup", json={"csrf": nonce, "key": FAKE_KEY}, headers=headers).status_code == 403
    assert "GEMINI_API_KEY" not in os.environ


def test_json_setup_and_size_limits(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = browser(monkeypatch)
    csrf = setup_form(client)
    assert client.post("/setup", json={"csrf": csrf, "key": "a" * 5000}, headers=HEADERS).status_code == 413
    response = client.post("/setup", json={"csrf": csrf, "key": FAKE_KEY}, headers=HEADERS)
    assert response.status_code == 200
    assert FAKE_KEY not in response.text


def test_modern_dotted_google_key_is_accepted_without_echo(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = browser(monkeypatch)
    csrf = setup_form(client)
    synthetic_key = "AQ." + "synthetic-test-segment_" * 3
    response = client.post("/setup", data={"csrf": csrf, "key": synthetic_key}, headers=HEADERS)
    assert response.status_code == 200
    assert os.environ["GEMINI_API_KEY"] == synthetic_key
    assert synthetic_key not in response.text
