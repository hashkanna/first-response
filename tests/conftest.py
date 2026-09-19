"""Offline tests never consume cloud credentials from a developer's .env."""

import pytest


@pytest.fixture(autouse=True)
def explicit_offline_backends(monkeypatch):
    monkeypatch.setenv("VERIFICATION_BACKEND", "local")
    monkeypatch.setenv("INVESTIGATOR_BACKEND", "local")
    monkeypatch.setenv("REPAIR_BACKEND", "authored")
