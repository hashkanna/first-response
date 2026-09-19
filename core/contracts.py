"""The wire contract shared by the incident hub and war-room UI."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Service = Literal["catalog", "cart", "checkout", "payments"]
FaultKind = Literal["bad_config", "null_error", "slow_query", "type_error"]
Stage = Literal[
    "alerted", "investigating", "cause_found", "reproduced", "fixes_proposed",
    "verifying", "fix_verified", "no_fix_found", "pr_opened", "resolved",
]


class Alert(BaseModel):
    alert_id: str
    service: Service
    signal: Literal["error_rate", "latency_p95"]
    value: float
    threshold: float
    started_at: datetime


class Evidence(BaseModel):
    evidence_id: str
    kind: Literal["trace", "exception", "deploy_diff", "code", "metric"]
    summary: str
    detail: str
    source_ref: str | None = None


class RootCause(BaseModel):
    service: Service
    file: str
    line: int | None = None
    commit: str | None = None
    explanation: str
    evidence_ids: list[str]
    confidence: float = Field(ge=0, le=1)


class ReproTest(BaseModel):
    path: str
    code: str
    fails_on_current: bool | None = None


class FixCandidate(BaseModel):
    candidate_id: str
    title: str
    rationale: str
    patch: str
    files_touched: list[str]
    origin: Literal["authored", "gemini"] = "authored"
    snapshot_sha: str | None = None


class VerifyResult(BaseModel):
    candidate_id: str
    applied: bool
    repro_passed: bool
    suite_passed: bool
    tests_run: int
    tests_failed: int
    duration_s: float
    log_tail: str


class FixRisk(BaseModel):
    action: Literal["auto_apply", "needs_human", "reject"]
    confidence: float = Field(ge=0, le=1)
    source: Literal["jev", "fallback"]


class IncidentUpdate(BaseModel):
    incident_id: str
    stage: Stage
    at: datetime
    message: str
    evidence: list[Evidence] = Field(default_factory=list)
    root_cause: RootCause | None = None
    candidates: list[FixCandidate] = Field(default_factory=list)
    results: list[VerifyResult] = Field(default_factory=list)
    pr_url: str | None = None


class VoiceCue(BaseModel):
    scheduling: Literal["INTERRUPT", "WHEN_IDLE", "SILENT"]
    facts: str


class StartInvestigationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service: Service | None = None


class ApproveFixArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str | None = None


class ExplainArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: Literal["cause", "fix", "evidence", "what_was_tried"]
