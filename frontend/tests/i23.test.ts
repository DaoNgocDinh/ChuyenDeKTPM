import assert from "node:assert/strict";
import test from "node:test";
import { PlatformApiClient, PlatformApiError } from "../src/api/client.ts";
import {
  extractPendingQuestions,
  IdempotencyTracker,
  isTerminalRunStatus,
  mergeEventsPage,
  parseRunIdFromHash,
} from "../src/api/polling.ts";

test("mergeEventsPage appends ascending, deduplicates, and preserves cursor on empty page", () => {
  const first = mergeEventsPage([], 0, {
    items: [
      { sequence: 2, kind: "step", role: "Requirement", message: "SRS v1", step_id: "s2", created_at: "2026-11-26T10:01:00Z" },
      { sequence: 1, kind: "run", role: "Orchestrator", message: "Claimed", step_id: "s1", created_at: "2026-11-26T10:00:00Z" },
    ],
    next_cursor: 2,
  });
  assert.deepEqual(
    first.items.map((e) => e.sequence),
    [1, 2],
  );
  assert.equal(first.cursor, 2);

  // Empty page must preserve cursor=2 even if server sends 0
  const empty = mergeEventsPage(first.items, first.cursor, { items: [], next_cursor: 0 });
  assert.equal(empty.cursor, 2);
  assert.equal(empty.items.length, 2);

  // Overlapping duplicate event + new event #3
  const next = mergeEventsPage(empty.items, empty.cursor, {
    items: [
      { sequence: 2, kind: "step", role: "Requirement", message: "SRS v1", step_id: "s2", created_at: "2026-11-26T10:01:00Z" },
      { sequence: 3, kind: "gate", role: "Orchestrator", message: "Waiting gate 1", step_id: null, created_at: "2026-11-26T10:02:00Z" },
    ],
    next_cursor: 3,
  });
  assert.deepEqual(
    next.items.map((e) => e.sequence),
    [1, 2, 3],
  );
  assert.equal(next.cursor, 3);
});

test("IdempotencyTracker retains exact key across retries until success or explicit rotate", () => {
  let seq = 0;
  const tracker = new IdempotencyTracker((pid) => `${pid}-k${++seq}`);
  const k1 = tracker.getOrCreate("p1");
  const k1Retry = tracker.getOrCreate("p1");
  assert.equal(k1, "p1-k1");
  assert.equal(k1Retry, "p1-k1");

  tracker.markSucceeded("p1");
  const k2 = tracker.getOrCreate("p1");
  assert.equal(k2, "p1-k2");

  const k3 = tracker.rotate("p1");
  assert.equal(k3, "p1-k3");
});

test("PlatformApiClient calls exact D10 endpoints and surfaces structured API error codes", async () => {
  const calls: Array<{ url: string; method: string; body?: string }> = [];
  const fakeFetch = async (input: string, init?: RequestInit) => {
    calls.push({ url: input, method: init?.method ?? "GET", body: init?.body as string | undefined });
    if (input === "/projects/p1/runs" && init?.method === "POST") {
      return new Response(JSON.stringify({ project_id: "p1", run_id: "r1", status: "queued" }), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (input === "/runs/r1/events?after=5") {
      return new Response(JSON.stringify({ items: [], next_cursor: 5 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (input === "/runs/r1/resume" && init?.method === "POST") {
      return new Response(
        JSON.stringify({ code: "invalid_transition", message: "Run đã hoàn tất." }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      );
    }
    return new Response(JSON.stringify({ code: "not_found", message: "Not found" }), { status: 404 });
  };

  const client = new PlatformApiClient("", fakeFetch);
  const ticket = await client.createRun("p1", { idempotency_key: "a1-lan-1" });
  assert.equal(ticket.run_id, "r1");
  assert.equal(ticket.status, "queued");

  const events = await client.getEvents("r1", 5);
  assert.equal(events.next_cursor, 5);

  await assert.rejects(
    () => client.resumeRun("r1"),
    (err: unknown) => err instanceof PlatformApiError && err.status === 409 && err.code === "invalid_transition",
  );

  assert.equal(calls.length, 3);
});

test("extractPendingQuestions, terminal status, and hash restoration work cleanly", () => {
  const qs = extractPendingQuestions({
    run_id: "r1",
    artifact_id: "req-v1",
    kind: "requirements",
    version: 1,
    sha256: "a".repeat(64),
    previous_artifact_id: null,
    media_type: "application/json",
    content: JSON.stringify({ questions: ["Task dùng các trạng thái nào?"] }),
  });
  assert.deepEqual(qs, [{ question_id: "Q1", prompt: "Task dùng các trạng thái nào?" }]);
  assert.equal(isTerminalRunStatus("completed"), true);
  assert.equal(isTerminalRunStatus("waiting_approval"), false);
  assert.equal(parseRunIdFromHash("#/runs/run-42"), "run-42");
});
