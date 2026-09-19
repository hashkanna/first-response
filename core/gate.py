"""Conservative local rules. No remote risk service is used."""

from core.contracts import Alert, FixCandidate, FixRisk, VerifyResult


def triage_alert(alert: Alert) -> str:
    return "page" if alert.value > alert.threshold else "ignore"


def verification_passed(result: VerifyResult) -> bool:
    return result.applied and result.repro_passed and result.suite_passed and result.tests_run > 0 and result.tests_failed == 0


def assess_fix(candidate: FixCandidate, result: VerifyResult) -> FixRisk:
    verified = (
        candidate.candidate_id == result.candidate_id
        and verification_passed(result)
    )
    # Even a verified patch requires the operator's explicit approval.
    return FixRisk(action="needs_human" if verified else "reject", confidence=1, source="fallback")
