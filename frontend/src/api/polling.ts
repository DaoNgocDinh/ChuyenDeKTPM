import type { ArtifactDetail, EventItem, EventsPage, RunStatus } from "./types.ts";

export const TERMINAL_RUN_STATUSES: ReadonlySet<RunStatus> = new Set([
  "completed",
  "failed",
  "cancelled",
]);

export function isTerminalRunStatus(status: RunStatus): boolean {
  return TERMINAL_RUN_STATUSES.has(status);
}

/**
 * Merge a cursor-polled events page into existing timeline state (D10 contract):
 * - Keep only events strictly greater than previous cursor or deduplicated by sequence.
 * - Sort ascending by sequence.
 * - Preserve previous cursor unchanged on an empty page (never regress cursor).
 */
export function mergeEventsPage(
  existing: readonly EventItem[],
  currentCursor: number,
  page: EventsPage,
): { items: EventItem[]; cursor: number } {
  const bySeq = new Map<number, EventItem>();
  for (const item of existing) {
    bySeq.set(item.sequence, item);
  }
  let maxSeq = currentCursor;
  for (const item of page.items) {
    if (item.sequence > 0) {
      bySeq.set(item.sequence, item);
      if (item.sequence > maxSeq) {
        maxSeq = item.sequence;
      }
    }
  }
  const items = Array.from(bySeq.values()).sort((a, b) => a.sequence - b.sequence);
  const nextCursor =
    page.items.length === 0
      ? currentCursor
      : Math.max(currentCursor, page.next_cursor, maxSeq);
  return { items, cursor: nextCursor };
}

/**
 * Retains the exact idempotency_key across retries after transient network errors
 * for the same project + configuration pair (D10 Screen 1 contract).
 */
export class IdempotencyTracker {
  private readonly keys = new Map<string, string>();
  private readonly generateKey: (projectId: string) => string;

  constructor(generateKey?: (projectId: string) => string) {
    this.generateKey =
      generateKey ??
      ((projectId) => {
        const rand =
          typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
            ? crypto.randomUUID()
            : `${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
        return `${projectId}-${rand}`;
      });
  }

  private slot(projectId: string, configurationRef?: string): string {
    return `${projectId}::${configurationRef ?? ""}`;
  }

  getOrCreate(projectId: string, configurationRef?: string): string {
    const id = this.slot(projectId, configurationRef);
    const existing = this.keys.get(id);
    if (existing) {
      return existing;
    }
    const created = this.generateKey(projectId);
    this.keys.set(id, created);
    return created;
  }

  markSucceeded(projectId: string, configurationRef?: string): void {
    this.keys.delete(this.slot(projectId, configurationRef));
  }

  rotate(projectId: string, configurationRef?: string): string {
    const id = this.slot(projectId, configurationRef);
    const created = this.generateKey(projectId);
    this.keys.set(id, created);
    return created;
  }
}

export interface PendingQuestion {
  question_id: string;
  prompt: string;
}

/**
 * Extracts open questions from a requirements/clarification artifact payload.
 * Supports either string[] ("questions": ["..."]) or object[] with id/text fields.
 */
export function extractPendingQuestions(artifact: ArtifactDetail | null): PendingQuestion[] {
  if (!artifact) {
    return [];
  }
  try {
    const parsed = JSON.parse(artifact.content) as { questions?: unknown };
    if (!Array.isArray(parsed.questions)) {
      return [];
    }
    const out: PendingQuestion[] = [];
    parsed.questions.forEach((entry, index) => {
      if (typeof entry === "string" && entry.trim()) {
        out.push({ question_id: `Q${index + 1}`, prompt: entry.trim() });
      } else if (entry && typeof entry === "object") {
        const obj = entry as Record<string, unknown>;
        const id =
          typeof obj.question_id === "string" && obj.question_id.trim()
            ? obj.question_id.trim()
            : typeof obj.id === "string" && obj.id.trim()
              ? obj.id.trim()
              : `Q${index + 1}`;
        const prompt =
          typeof obj.question === "string"
            ? obj.question
            : typeof obj.prompt === "string"
              ? obj.prompt
              : typeof obj.text === "string"
                ? obj.text
                : "";
        if (prompt.trim()) {
          out.push({ question_id: id, prompt: prompt.trim() });
        }
      }
    });
    return out;
  } catch {
    return [];
  }
}

export function parseRunIdFromHash(hash: string): string | null {
  const match = /^#\/runs\/([^/?#]+)/.exec(hash);
  return match ? decodeURIComponent(match[1]) : null;
}

export const SIX_ROLES = [
  "Orchestrator",
  "Requirement",
  "Architecture",
  "Planning",
  "Dev",
  "Tester",
] as const;
