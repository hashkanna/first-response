import pytest

from core.contracts import FixCandidate, VerifyResult
from core.gate import assess_fix, verification_passed


@pytest.mark.parametrize("changes", [{"tests_run": 0}, {"tests_failed": 1}, {"applied": False}, {"repro_passed": False}, {"suite_passed": False}])
def test_gate_rejects_inconsistent_or_incomplete_success(changes):
    data = {"candidate_id": "fix", "applied": True, "repro_passed": True, "suite_passed": True, "tests_run": 25, "tests_failed": 0, "duration_s": 1, "log_tail": "passed"}
    result = VerifyResult(**{**data, **changes})
    candidate = FixCandidate(candidate_id="fix", title="fix", rationale="fix", patch="patch", files_touched=["app/config.py"])
    assert not verification_passed(result)
    assert assess_fix(candidate, result).action == "reject"
