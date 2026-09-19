"""Validated Live function calls backed by the same incident manager as the UI."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import ValidationError

from core.contracts import ApproveFixArgs, ExplainArgs, StartInvestigationArgs


@dataclass
class LiveAdapter:
    get_status: Callable[[], dict[str, Any]]
    start_investigation: Callable[[str | None], Awaitable[dict[str, Any]]]
    explain: Callable[[str], Awaitable[dict[str, Any] | str]]
    approve_fix: Callable[[str, str], Awaitable[dict[str, Any]]]
    subscribe: Callable[[], asyncio.Queue[dict[str, Any]]]
    unsubscribe: Callable[[asyncio.Queue[dict[str, Any]]], None]


def verified_ids(status: dict[str, Any]) -> set[str]:
    """Use the latest result for each candidate in the active incident only."""
    incident_id = status.get("incident_id")
    results: dict[str, dict[str, Any]] = {}
    candidates: set[str] = set()
    for event in status.get("events", []):
        if event.get("incident_id") != incident_id:
            continue
        candidates.update(item["candidate_id"] for item in event.get("candidates", []))
        results.update((item["candidate_id"], item) for item in event.get("results", []))
    return {
        candidate_id for candidate_id, result in results.items()
        if candidate_id in candidates and all(result.get(field) is True for field in ("applied", "repro_passed", "suite_passed"))
        and isinstance(result.get("tests_run"), int) and result["tests_run"] > 0
        and result.get("tests_failed") == 0
    }


def compact_status(status: dict[str, Any]) -> dict[str, Any]:
    """No source files, secrets, or unlimited test output in conversational context."""
    events = [event for event in status.get("events", []) if event.get("incident_id") == status.get("incident_id")]
    latest = events[-1] if events else {}
    candidates: dict[str, dict[str, Any]] = {}
    results: dict[str, dict[str, Any]] = {}
    for event in events:
        candidates.update((item["candidate_id"], item) for item in event.get("candidates", []))
        results.update((item["candidate_id"], item) for item in event.get("results", []))
    verifications = []
    for candidate_id, candidate in list(candidates.items())[:3]:
        result = results.get(candidate_id, {})
        passed = candidate_id in verified_ids(status)
        verifications.append({
            "candidate_id": candidate_id,
            "title": str(candidate.get("title", ""))[:240],
            "origin": candidate.get("origin"),
            **{field: result.get(field) for field in ("applied", "repro_passed", "suite_passed", "tests_run", "tests_failed")},
            "failed_log_tail": str(result.get("log_tail", ""))[-2200:] if result and not passed else "",
        })
    return {
        "incident_id": status.get("incident_id"),
        "stage": status.get("stage"),
        "active_fault": status.get("active_fault"),
        "mode": status.get("mode"),
        "latest_fact": latest.get("message", "No incident is active."),
        "verified_candidate_ids": sorted(verified_ids(status)),
        "recommended_candidate_id": status.get("recommended_candidate_id"),
        "candidate_verifications": verifications,
        "approval": status.get("approval"),
    }


class ApprovalLatch:
    """A model tool call alone can never approve a change.

    Only a recent explicit operator utterance arms a one-use grant, bound to the
    current incident and its already-verified candidates. Hub context/cues never
    pass through this method. Negative or unrelated input clears the grant.
    """

    def __init__(self) -> None:
        self.incident_id: str | None = None
        self.candidate_ids: set[str] = set()
        self.expires = 0.0

    def clear(self) -> None:
        self.incident_id = None
        self.candidate_ids = set()
        self.expires = 0.0

    def observe(self, text: str, status: dict[str, Any]) -> None:
        self.clear()
        normalized = re.sub(r"[^a-z0-9\s]", "", text.lower()).strip()
        normalized = re.sub(r"\s+", " ", normalized)
        explicit = re.fullmatch(
            r"(?:yes(?: please)?(?: go ahead)?|go ahead(?: please)?|"
            r"(?:yes )?(?:approve|apply)(?: it| that| the fix| the verified fix| the patch)?(?: please)?|"
            r"yes (?:apply|approve)(?: it| the fix| the verified fix| the patch)?)",
            normalized,
        )
        eligible = verified_ids(status)
        if explicit and eligible and status.get("stage") == "fix_verified":
            self.incident_id = status.get("incident_id")
            self.candidate_ids = eligible
            self.expires = time.monotonic() + 60

    def consume(self, candidate_id: str, status: dict[str, Any]) -> bool:
        allowed = (
            time.monotonic() < self.expires
            and self.incident_id == status.get("incident_id")
            and status.get("stage") == "fix_verified"
            and candidate_id in self.candidate_ids
            and candidate_id in verified_ids(status)
        )
        self.clear()
        return allowed


TOOL_DECLARATIONS = [
    {
        "name": "start_investigation",
        "description": "Start or join the active alert investigation. Returns immediately; evidence arrives in background updates.",
        "behavior": "NON_BLOCKING",
        "parameters": {"type": "OBJECT", "properties": {"service": {"type": "STRING", "enum": ["catalog", "cart", "checkout", "payments"]}}},
    },
    {
        "name": "get_status",
        "description": "Get actual incident facts and candidate-specific verification outcomes, including bounded failure logs. Use this to explain why a proposed repair failed.",
        "behavior": "NON_BLOCKING",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "explain",
        "description": "Retrieve recorded facts about the cause, fix, evidence, or candidates tested. Never invent missing evidence.",
        "behavior": "NON_BLOCKING",
        "parameters": {"type": "OBJECT", "properties": {"topic": {"type": "STRING", "enum": ["cause", "fix", "evidence", "what_was_tried"]}}, "required": ["topic"]},
    },
    {
        "name": "approve_fix",
        "description": "Apply a verified fix ONLY after the human explicitly says yes, approve, or apply. Requires a recent operator confirmation; never call because of a background cue.",
        "behavior": "NON_BLOCKING",
        "parameters": {"type": "OBJECT", "properties": {"candidate_id": {"type": "STRING"}}},
    },
]


async def execute_tool(name: str, arguments: Any, adapter: LiveAdapter, approval: ApprovalLatch) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        return {"error": "Tool arguments must be an object. Ask the operator to clarify."}
    fields = {"get_status": set(), "start_investigation": {"service"}, "explain": {"topic"}, "approve_fix": {"candidate_id"}}
    if name in fields and set(arguments) - fields[name]:
        return {"error": "Unexpected tool arguments. Ask the operator to clarify."}
    try:
        if name == "get_status":
            if arguments:
                return {"error": "get_status takes no arguments."}
            return compact_status(adapter.get_status())
        if name == "start_investigation":
            parsed = StartInvestigationArgs.model_validate(arguments)
            return await adapter.start_investigation(parsed.service)
        if name == "explain":
            parsed = ExplainArgs.model_validate(arguments)
            return {"facts": await adapter.explain(parsed.topic)}
        if name == "approve_fix":
            parsed = ApproveFixArgs.model_validate(arguments)
            status = adapter.get_status()
            eligible = verified_ids(status)
            candidate_id = parsed.candidate_id
            if candidate_id is None:
                recommended = status.get("recommended_candidate_id")
                if recommended in eligible:
                    candidate_id = recommended
                elif len(eligible) == 1:
                    candidate_id = next(iter(eligible))
            if candidate_id not in eligible:
                return {"error": "Select a candidate that passed patch application, reproduction, and the full suite."}
            if not approval.consume(candidate_id, status):
                return {"error": "No current explicit operator approval. Type exactly 'Apply the verified fix' or click the review button and confirm there. Do not repeat spoken approval. Opening review does not apply a change."}
            return await adapter.approve_fix(candidate_id, status["incident_id"])
        return {"error": f"Unknown tool: {name}"}
    except ValidationError as error:
        return {"error": "Invalid tool arguments. Ask the operator to clarify.", "details": error.errors(include_input=False, include_url=False)}
    except Exception as error:
        # FastAPI HTTPException exposes a safe detail; never forward arbitrary SDK exceptions.
        detail = getattr(error, "detail", None)
        return {"error": str(detail)[:400] if detail is not None else "The hub operation failed. Check the incident state before retrying."}
