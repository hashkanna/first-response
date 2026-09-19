"""Offline approval rehearsal guards; no synthesis or provider calls."""
from copy import deepcopy

import pytest

from scripts.check_live_audio import approval_resolved, approval_target


def verified_state():
    return {
        "incident_id": "inc-1", "stage": "fix_verified", "approval": None,
        "recommended_candidate_id": "candidate-1",
        "events": [{"incident_id": "inc-1", "candidates": [{"candidate_id": "candidate-1", "snapshot_sha": "a" * 64}],
                    "results": [{"candidate_id": "candidate-1", "applied": True, "repro_passed": True, "suite_passed": True, "tests_run": 25, "tests_failed": 0}]}],
    }


def test_approval_capture_requires_verified_snapshot_and_rejects_stale_events():
    state = verified_state()
    assert approval_target(state) == {"incident_id": "inc-1", "candidate_id": "candidate-1", "snapshot_sha": "a" * 64}
    for field, value in (("tests_run", 0), ("tests_failed", 1), ("applied", False)):
        bad = deepcopy(state)
        bad["events"][0]["results"][0][field] = value
        with pytest.raises(ValueError):
            approval_target(bad)
    state["events"][0]["candidates"][0]["snapshot_sha"] = None
    with pytest.raises(ValueError):
        approval_target(state)
    state["incident_id"] = "inc-new"
    with pytest.raises(ValueError):
        approval_target(state)


def test_resolution_must_match_incident_candidate_and_source_snapshot():
    state = verified_state()
    target = approval_target(state)
    assert approval_resolved(state, target) is False
    state.update(stage="resolved", approval={"approved": True, **target})
    assert approval_resolved(state, target) is True
    for field in ("incident_id", "candidate_id", "snapshot_sha"):
        bad = deepcopy(state)
        bad["approval"][field] = "changed"
        with pytest.raises(ValueError):
            approval_resolved(bad, target)


def test_candidate_or_incident_drift_aborts_before_resolution():
    state = verified_state()
    target = approval_target(state)
    state["events"][0]["candidates"][0]["snapshot_sha"] = "b" * 64
    with pytest.raises(ValueError):
        approval_resolved(state, target)
    state["incident_id"] = "inc-new"
    with pytest.raises(ValueError):
        approval_resolved(state, target)
