import type {
  ApprovalDecision,
  ApprovalGate,
  ApprovalRequest,
  ArtifactItem,
  ArtifactRef,
  FinalAcceptanceRequest,
  TaskItem,
  TestReportItem,
} from "./types.ts";

const SHA256_RE = /^[0-9a-f]{64}$/;

export function toArtifactRef(item: Pick<ArtifactItem, "artifact_id" | "version" | "sha256">): ArtifactRef {
  return {
    artifact_id: item.artifact_id,
    version: item.version,
    sha256: item.sha256,
  };
}

export function validateArtifactRef(ref: ArtifactRef): void {
  if (!ref.artifact_id.trim()) {
    throw new Error("artifact_id không được để trống.");
  }
  if (!Number.isInteger(ref.version) || ref.version < 1) {
    throw new Error("version phải là số nguyên >= 1.");
  }
  if (!SHA256_RE.test(ref.sha256)) {
    throw new Error("sha256 phải gồm đúng 64 ký tự hex chữ thường.");
  }
}

/**
 * Validates and constructs an atomic gate approval payload matching D10 Approval schema:
 * - gate="requirements" requires exactly 1 artifact ref.
 * - gate="architecture_plan" requires exactly 2 distinct artifact refs.
 * - decision="request_changes" requires a non-empty comment.
 */
export function buildApprovalPayload(input: {
  gate: ApprovalGate;
  artifacts: ArtifactRef[];
  decision: ApprovalDecision;
  comment: string;
}): ApprovalRequest {
  const comment = input.comment.trim();
  if (input.decision === "request_changes" && comment.length === 0) {
    throw new Error("Bắt buộc nhập ghi chú (comment) khi chọn yêu cầu sửa.");
  }

  const expectedCount = input.gate === "requirements" ? 1 : 2;
  if (input.artifacts.length !== expectedCount) {
    throw new Error(
      input.gate === "requirements"
        ? "Cổng 1 (requirements) cần đúng 1 artifact."
        : "Cổng 2 (architecture_plan) cần đúng 2 artifact (architecture và plan) trong một quyết định nguyên tử.",
    );
  }

  const ids = new Set<string>();
  for (const ref of input.artifacts) {
    validateArtifactRef(ref);
    if (ids.has(ref.artifact_id)) {
      throw new Error("Không được gửi trùng artifact_id trong cùng một quyết định cổng.");
    }
    ids.add(ref.artifact_id);
  }

  return {
    gate: input.gate,
    artifacts: input.artifacts,
    decision: input.decision,
    comment,
  };
}

export function buildAcceptancePayload(input: {
  manifest: ArtifactRef;
  decision: "accept" | "request_changes";
  comment: string;
}): FinalAcceptanceRequest {
  validateArtifactRef(input.manifest);
  const comment = input.comment.trim();
  if (input.decision === "request_changes" && comment.length === 0) {
    throw new Error("Bắt buộc nhập lý do khi từ chối / yêu cầu sửa ở nghiệm thu cuối.");
  }
  return {
    manifest: input.manifest,
    decision: input.decision,
    comment,
  };
}

export interface DiffLine {
  kind: "same" | "added" | "removed";
  text: string;
}

/**
 * Simple deterministic LCS line diff for comparing an artifact against previous_artifact_id.
 */
export function computeLineDiff(previousText: string, currentText: string): DiffLine[] {
  const a = previousText.replace(/\r\n/g, "\n").split("\n");
  const b = currentText.replace(/\r\n/g, "\n").split("\n");
  const m = a.length;
  const n = b.length;

  // Guard against huge files: fall back to direct removed/added sections if matrix > 250k cells
  if (m * n > 250_000) {
    return [
      ...a.map((text): DiffLine => ({ kind: "removed", text })),
      ...b.map((text): DiffLine => ({ kind: "added", text })),
    ];
  }

  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array<number>(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i -= 1) {
    for (let j = n - 1; j >= 0; j -= 1) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < m && j < n) {
    if (a[i] === b[j]) {
      out.push({ kind: "same", text: a[i] });
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out.push({ kind: "removed", text: a[i] });
      i += 1;
    } else {
      out.push({ kind: "added", text: b[j] });
      j += 1;
    }
  }
  while (i < m) {
    out.push({ kind: "removed", text: a[i] });
    i += 1;
  }
  while (j < n) {
    out.push({ kind: "added", text: b[j] });
    j += 1;
  }
  return out;
}

export interface TraceRow {
  requirement_id: string;
  task_id: string;
  task_status: string;
  patch_artifact_ids: string[];
  reports: TestReportItem[];
}

/**
 * Joins FR -> task -> patch -> test reports for Screen 4 traceability table.
 */
export function buildTraceRows(
  tasks: readonly TaskItem[],
  testReports: readonly TestReportItem[],
): TraceRow[] {
  const reportsByTask = new Map<string, TestReportItem[]>();
  for (const report of testReports) {
    if (!report.task_id) {
      continue;
    }
    const list = reportsByTask.get(report.task_id) ?? [];
    list.push(report);
    reportsByTask.set(report.task_id, list);
  }

  const rows: TraceRow[] = [];
  for (const task of tasks) {
    const linkedReports = reportsByTask.get(task.task_id) ?? [];
    const reqIds = task.requirement_ids.length > 0 ? task.requirement_ids : ["(chưa gắn FR)"];
    for (const rid of reqIds) {
      rows.push({
        requirement_id: rid,
        task_id: task.task_id,
        task_status: task.status,
        patch_artifact_ids: [...task.patch_artifact_ids],
        reports: linkedReports,
      });
    }
  }
  return rows;
}
