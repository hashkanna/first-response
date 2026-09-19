"""Offline approval rehearsal guards; no synthesis or provider calls."""
from copy import deepcopy

import pytest

from scripts.check_live_audio import approval_resolved, approval_target, review_audio_evidence, review_checks


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


def test_review_receipt_requires_bound_event_and_no_application():
    state = verified_state()
    target = approval_target(state)
    session = {
        "events": [
            {"type": "review_requested", "request_id": "request-1", "incident_id": "inc-1", "candidate_id": "candidate-1", "audio_bytes_so_far": 0},
            {"type": "transcript", "role": "assistant", "text": "Please confirm in review."},
            {"type": "turn_complete", "audio_bytes_so_far": 32000},
        ],
        "transcripts": [{"role": "user", "text": "Apply the verified fix."}],
        "native_output_pcm_bytes": 32000, "error": None,
    }
    assert all(review_checks(session, target, state, state).values())
    session["events"][0]["incident_id"] = "stale"
    assert not review_checks(session, target, state, state)["review_bound_to_verified_target"]
    session["events"].append({"type": "tool_result", "name": "approve_fix", "ok": True})
    assert not review_checks(session, target, state, state)["approval_tool_did_not_apply"]
    after = {**state, "stage": "resolved", "approval": {"approved": True}}
    assert not review_checks(session, target, state, after)["incident_and_approval_unchanged"]


def test_review_audio_rejects_two_bytes_and_early_function_turn_completion():
    target = approval_target(verified_state())
    request = {"type": "review_requested", "incident_id": "inc-1", "candidate_id": "candidate-1", "audio_bytes_so_far": 12000}
    session = {"events": [request, {"type": "turn_complete", "audio_bytes_so_far": 12000}], "native_output_pcm_bytes": 12002}
    assert not any(review_audio_evidence(session, target).values())
    session["native_output_pcm_bytes"] = 16800
    assert review_audio_evidence(session, target)["native_pcm_returned"]
    assert not review_audio_evidence(session, target)["assistant_response_completed_after_review"]
    session["events"].append({"type": "transcript", "role": "assistant", "text": "Review is ready."})
    assert not review_audio_evidence(session, target)["assistant_response_completed_after_review"]
    session["events"].append({"type": "turn_complete", "audio_bytes_so_far": 16800})
    assert all(review_audio_evidence(session, target).values())
    session["events"].insert(-1, {"type": "interrupted"})
    assert not review_audio_evidence(session, target)["assistant_response_completed_after_review"]
