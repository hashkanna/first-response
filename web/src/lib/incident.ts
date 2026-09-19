import type {
  Evidence,
  FixCandidate,
  IncidentUpdate,
  RootCause,
  Stage,
  VerifyResult,
} from "./contracts";

export interface IncidentState {
  incidentId: string | null;
  stage: Stage | null;
  updates: IncidentUpdate[];
  evidence: Evidence[];
  rootCause: RootCause | null;
  candidates: FixCandidate[];
  results: VerifyResult[];
  prUrl: string | null;
  startedAt: string | null;
  verifiedAt: string | null;
  latestAt: string | null;
  /** Internal ordering and isolation bookkeeping. Reset with createInitialState(). */
  _entityAt: Record<string, number>;
  _stageAt: number;
  _seenEventKeys: string[];
  _retiredIncidentIds: string[];
}

export function createInitialState(): IncidentState {
  return {
    incidentId: null,
    stage: null,
    updates: [],
    evidence: [],
    rootCause: null,
    candidates: [],
    results: [],
    prUrl: null,
    startedAt: null,
    verifiedAt: null,
    latestAt: null,
    _entityAt: {},
    _stageAt: -Infinity,
    _seenEventKeys: [],
    _retiredIncidentIds: [],
  };
}

const STAGES: Stage[] = [
  "alerted",
  "investigating",
  "cause_found",
  "reproduced",
  "fixes_proposed",
  "verifying",
  "fix_verified",
  "no_fix_found",
  "pr_opened",
  "resolved",
];
const stageRank = (stage: Stage | null): number =>
  stage === null ? -1 : stage === "no_fix_found" ? 6 : STAGES.indexOf(stage);
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isString = (value: unknown): value is string => typeof value === "string";
const isId = (value: unknown): value is string =>
  isString(value) && value.trim().length > 0;
const isNumber = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
const isCount = (value: unknown): value is number =>
  isNumber(value) && Number.isInteger(value) && value >= 0;
const isStrings = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every(isString);
const optional = (value: unknown, valid: (v: unknown) => boolean): boolean =>
  value === undefined || value === null || valid(value);
const isService = (value: unknown): boolean =>
  ["catalog", "cart", "checkout", "payments"].includes(value as string);
const isTime = (value: unknown): value is string =>
  isString(value) &&
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(
    value,
  ) &&
  Number.isFinite(Date.parse(value));
const isConfidence = (value: unknown): boolean =>
  isNumber(value) && value >= 0 && value <= 1;
const isWebUrl = (value: unknown): boolean => {
  if (!isString(value)) return false;
  try {
    return ["http:", "https:"].includes(new URL(value).protocol);
  } catch {
    return false;
  }
};
const isEvidence = (value: unknown): value is Evidence =>
  isRecord(value) &&
  isId(value.evidence_id) &&
  ["trace", "exception", "deploy_diff", "code", "metric"].includes(
    value.kind as string,
  ) &&
  isString(value.summary) &&
  isString(value.detail) &&
  optional(value.source_ref, isString);
const isCause = (value: unknown): value is RootCause =>
  isRecord(value) &&
  isService(value.service) &&
  isString(value.file) &&
  optional(value.line, (v) => isCount(v) && v > 0) &&
  optional(value.commit, isString) &&
  isString(value.explanation) &&
  isStrings(value.evidence_ids) &&
  isConfidence(value.confidence);
const isCandidate = (value: unknown): value is FixCandidate =>
  isRecord(value) &&
  isId(value.candidate_id) &&
  isString(value.title) &&
  isString(value.rationale) &&
  isString(value.patch) &&
  isStrings(value.files_touched) &&
  optional(value.origin, (v) => v === "authored" || v === "gemini") &&
  optional(
    value.snapshot_sha,
    (v) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v),
  );
const isResult = (value: unknown): value is VerifyResult =>
  isRecord(value) &&
  isId(value.candidate_id) &&
  typeof value.applied === "boolean" &&
  typeof value.repro_passed === "boolean" &&
  typeof value.suite_passed === "boolean" &&
  isCount(value.tests_run) &&
  isCount(value.tests_failed) &&
  value.tests_failed <= value.tests_run &&
  isNumber(value.duration_s) &&
  value.duration_s >= 0 &&
  isString(value.log_tail);
const optionalArray = (
  value: unknown,
  valid: (item: unknown) => boolean,
): boolean =>
  value === undefined || (Array.isArray(value) && value.every(valid));

/** Validate untrusted JSON without adding a runtime schema dependency. Extra fields are ignored. */
export function parseIncidentUpdate(value: unknown): IncidentUpdate | null {
  if (
    !isRecord(value) ||
    !isId(value.incident_id) ||
    !STAGES.includes(value.stage as Stage) ||
    !isTime(value.at) ||
    !isString(value.message) ||
    !optionalArray(value.evidence, isEvidence) ||
    !optionalArray(value.candidates, isCandidate) ||
    !optionalArray(value.results, isResult) ||
    !optional(value.root_cause, isCause) ||
    !optional(value.pr_url, isWebUrl)
  )
    return null;
  return {
    incident_id: value.incident_id,
    stage: value.stage as Stage,
    at: value.at,
    message: value.message,
    evidence: (value.evidence as Evidence[] | undefined) ?? [],
    candidates: (value.candidates as FixCandidate[] | undefined) ?? [],
    results: (value.results as VerifyResult[] | undefined) ?? [],
    root_cause: (value.root_cause as RootCause | null | undefined) ?? null,
    pr_url: (value.pr_url as string | null | undefined) ?? null,
  };
}

function mergeEntities<T>(
  current: T[],
  incoming: T[],
  id: (item: T) => string,
  kind: string,
  at: number,
  times: Record<string, number>,
): T[] {
  const merged = [...current];
  for (const item of incoming) {
    const key = `${kind}:${id(item)}`;
    if (at < (times[key] ?? -Infinity)) continue;
    const index = merged.findIndex((existing) => id(existing) === id(item));
    if (index === -1) merged.push(item);
    else merged[index] = item;
    times[key] = at;
  }
  return merged;
}

/** A candidate is offerable only after its patch, reproduction, AND suite succeed. */
export function getVerifiedCandidates(state: IncidentState): FixCandidate[] {
  return state.candidates.filter((candidate) =>
    state.results.some(
      (result) =>
        result.candidate_id === candidate.candidate_id &&
        result.applied &&
        result.repro_passed &&
        result.suite_passed &&
        result.tests_run > 0 &&
        result.tests_failed === 0,
    ),
  );
}

/** Merge partial events without erasing previous evidence or mixing different incidents. */
export function reduceIncident(
  state: IncidentState,
  input: IncidentUpdate,
): IncidentState {
  const event = parseIncidentUpdate(input);
  if (!event) return state;
  const at = Date.parse(event.at);
  let current = state;
  if (current.incidentId !== null && current.incidentId !== event.incident_id) {
    // A new alert is the only permitted boundary. Old sockets cannot restore retired incidents.
    if (
      event.stage !== "alerted" ||
      current._retiredIncidentIds.includes(event.incident_id) ||
      at <= Date.parse(current.latestAt ?? current.startedAt ?? event.at)
    )
      return state;
    current = {
      ...createInitialState(),
      _retiredIncidentIds: [...current._retiredIncidentIds, current.incidentId],
    };
  }
  const eventKey = JSON.stringify(event);
  if (current._seenEventKeys.includes(eventKey)) return current;
  const times = { ...current._entityAt };
  const next: IncidentState = {
    ...current,
    incidentId: event.incident_id,
    updates: [...current.updates, event].sort(
      (a, b) => Date.parse(a.at) - Date.parse(b.at),
    ),
    evidence: mergeEntities(
      current.evidence,
      event.evidence ?? [],
      (item) => item.evidence_id,
      "evidence",
      at,
      times,
    ),
    candidates: mergeEntities(
      current.candidates,
      event.candidates ?? [],
      (item) => item.candidate_id,
      "candidate",
      at,
      times,
    ),
    results: mergeEntities(
      current.results,
      event.results ?? [],
      (item) => item.candidate_id,
      "result",
      at,
      times,
    ),
    latestAt:
      !current.latestAt || at > Date.parse(current.latestAt)
        ? event.at
        : current.latestAt,
    _seenEventKeys: [...current._seenEventKeys, eventKey],
    _entityAt: times,
  };
  if (event.root_cause && at >= (times.rootCause ?? -Infinity)) {
    next.rootCause = event.root_cause;
    times.rootCause = at;
  }
  if (event.pr_url && at >= (times.prUrl ?? -Infinity)) {
    next.prUrl = event.pr_url;
    times.prUrl = at;
  }
  if (
    event.stage === "alerted" &&
    (!next.startedAt || at < Date.parse(next.startedAt))
  )
    next.startedAt = event.at;
  const hasVerifiedFix = getVerifiedCandidates(next).length > 0;
  const supportedStage = event.stage !== "fix_verified" || hasVerifiedFix;
  if (
    supportedStage &&
    at >= current._stageAt &&
    stageRank(event.stage) >= stageRank(current.stage)
  ) {
    next.stage = event.stage;
    next._stageAt = at;
  }
  // Completion messages alone are never proof of a working patch.
  if (
    event.stage === "fix_verified" &&
    hasVerifiedFix &&
    (!next.verifiedAt || at < Date.parse(next.verifiedAt))
  )
    next.verifiedAt = event.at;
  if (!hasVerifiedFix) {
    next.verifiedAt = null;
    if (next.stage === "fix_verified") next.stage = "verifying";
  }
  return next;
}

/** Duration freezes at verified completion and never becomes negative. */
export function elapsedMs(state: IncidentState, now = Date.now()): number {
  if (!state.startedAt) return 0;
  const end = state.verifiedAt ? Date.parse(state.verifiedAt) : now;
  return Math.max(0, end - Date.parse(state.startedAt));
}
