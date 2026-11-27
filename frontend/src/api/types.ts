/**
 * TypeScript contract mirroring docs/openapi.json (D10, OpenAPI 3.1.1).
 * Kept strictly aligned with D10 so I23/I24 connect directly to I22 with zero schema drift.
 */

export type ErrorCode =
  | "not_found"
  | "approval_version_conflict"
  | "invalid_transition"
  | "tool_denied"
  | "budget_exceeded"
  | "invalid_request"
  | "idempotency_conflict";

export interface ApiErrorBody {
  code: ErrorCode;
  message: string;
}

export interface CreateProjectRequest {
  name: string;
  brief: string;
  constraints?: string[];
}

export interface Project {
  project_id: string;
  name: string;
  brief: string;
  constraints: string[];
}

export type RunStatus =
  | "queued"
  | "running"
  | "waiting_approval"
  | "pending_recovery"
  | "needs_human_review"
  | "completed"
  | "failed"
  | "cancelled";

export type NextAction =
  | "review"
  | "cancel"
  | "resume"
  | "inspect"
  | "clarify"
  | "accept_output";

export interface CreateRunRequest {
  idempotency_key: string;
  configuration_ref?: string;
}

export interface RunTicket {
  project_id: string;
  run_id: string;
  status: RunStatus;
}

export interface RunQuota {
  input_tokens: number;
  output_tokens: number;
  usage_complete: boolean;
  tool_calls: number;
}

export interface RunDetail {
  project_id: string;
  run_id: string;
  status: RunStatus;
  stage: string | null;
  current_step_id: string | null;
  quota: RunQuota;
  next_actions: NextAction[];
  last_error: ApiErrorBody | null;
  gate_artifact_ids?: string[];
  question_artifact_id?: string | null;
}

export interface EventItem {
  sequence: number;
  kind: string;
  role: string | null;
  message: string;
  step_id: string | null;
  created_at: string;
}

export interface EventsPage {
  items: EventItem[];
  next_cursor: number;
}

export interface ArtifactRef {
  artifact_id: string;
  version: number;
  sha256: string;
}

export interface ArtifactItem {
  run_id: string;
  artifact_id: string;
  kind: string;
  version: number;
  sha256: string;
  previous_artifact_id: string | null;
}

export interface ArtifactDetail extends ArtifactItem {
  media_type: string;
  content: string;
}

export type ApprovalGate = "requirements" | "architecture_plan";
export type ApprovalDecision = "approve" | "request_changes";

export interface ApprovalRequest {
  gate: ApprovalGate;
  artifacts: ArtifactRef[];
  decision: ApprovalDecision;
  comment: string;
}

export interface DecisionReceipt {
  run_id: string;
  decision_id: string;
  status: RunStatus;
}

export type TaskStatus =
  | "todo"
  | "ready"
  | "in_progress"
  | "waiting_test"
  | "rework"
  | "done"
  | "blocked";

export interface TaskItem {
  task_id: string;
  title: string;
  status: TaskStatus;
  requirement_ids: string[];
  dependency_ids: string[];
  patch_artifact_ids: string[];
}

export interface TestReportItem {
  report_id: string;
  task_id: string | null;
  suite_id: string;
  commit: string;
  exit_code: number | null;
  passed: number;
  failed: number;
  skipped: number;
  errors: number;
  log_artifact_id: string | null;
  bug_artifact_ids: string[];
  trace_artifact_ids: string[];
}

export interface ClarificationAnswer {
  question_id: string;
  answer: string;
}

export interface ClarificationRequest {
  artifact: ArtifactRef;
  answers: ClarificationAnswer[];
}

export interface FinalAcceptanceRequest {
  manifest: ArtifactRef;
  decision: "accept" | "request_changes";
  comment: string;
}
