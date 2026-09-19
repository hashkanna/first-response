/** Wire contracts mirrored from core/contracts.py in the implementation brief. */
export type Service = "catalog" | "cart" | "checkout" | "payments";
export type FaultKind =
  "bad_config" | "null_error" | "slow_query" | "type_error";
export type Stage =
  | "alerted"
  | "investigating"
  | "cause_found"
  | "reproduced"
  | "fixes_proposed"
  | "verifying"
  | "fix_verified"
  | "no_fix_found"
  | "pr_opened"
  | "resolved";

export interface Alert {
  alert_id: string;
  service: Service;
  signal: "error_rate" | "latency_p95";
  value: number;
  threshold: number;
  started_at: string;
}
export interface Evidence {
  evidence_id: string;
  kind: "trace" | "exception" | "deploy_diff" | "code" | "metric";
  summary: string;
  detail: string;
  source_ref?: string | null;
}
export interface RootCause {
  service: Service;
  file: string;
  line?: number | null;
  commit?: string | null;
  explanation: string;
  evidence_ids: string[];
  confidence: number;
}
export interface ReproTest {
  path: string;
  code: string;
  fails_on_current?: boolean | null;
}
export interface FixCandidate {
  candidate_id: string;
  title: string;
  rationale: string;
  patch: string;
  files_touched: string[];
  origin?: "authored" | "gemini";
  snapshot_sha?: string | null;
}
export interface VerifyResult {
  candidate_id: string;
  applied: boolean;
  repro_passed: boolean;
  suite_passed: boolean;
  tests_run: number;
  tests_failed: number;
  duration_s: number;
  log_tail: string;
}
export interface FixRisk {
  action: "auto_apply" | "needs_human" | "reject";
  confidence: number;
  source: "jev" | "fallback";
}
/** Lists may be omitted on the wire: the Python model supplies empty defaults. */
export interface IncidentUpdate {
  incident_id: string;
  stage: Stage;
  at: string;
  message: string;
  evidence?: Evidence[];
  root_cause?: RootCause | null;
  candidates?: FixCandidate[];
  results?: VerifyResult[];
  pr_url?: string | null;
}
export interface VoiceCue {
  scheduling: "INTERRUPT" | "WHEN_IDLE" | "SILENT";
  facts: string;
}
export interface StartInvestigationArgs {
  service?: Service | null;
}
export interface ApproveFixArgs {
  candidate_id?: string | null;
}
export interface ExplainArgs {
  topic: "cause" | "fix" | "evidence" | "what_was_tried";
}
