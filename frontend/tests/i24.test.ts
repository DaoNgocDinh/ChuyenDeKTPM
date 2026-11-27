import assert from "node:assert/strict";
import test from "node:test";
import { PlatformApiClient, PlatformApiError } from "../src/api/client.ts";
import {
  buildAcceptancePayload,
  buildApprovalPayload,
  buildTraceRows,
  computeLineDiff,
} from "../src/api/review.ts";

const HASH_A = "a".repeat(64);
const HASH_B = "b".repeat(64);

test("buildApprovalPayload enforces Gate 1 (1 ref), Gate 2 (2 atomic refs), and request_changes comment", () => {
  const gate1 = buildApprovalPayload({
    gate: "requirements",
    artifacts: [{ artifact_id: "req-v1", version: 1, sha256: HASH_A }],
    decision: "approve",
    comment: "",
  });
  assert.equal(gate1.gate, "requirements");
  assert.equal(gate1.artifacts.length, 1);

  assert.throws(
    () =>
      buildApprovalPayload({
        gate: "requirements",
        artifacts: [{ artifact_id: "req-v1", version: 1, sha256: HASH_A }],
        decision: "request_changes",
        comment: "   ",
      }),
    /comment/i,
  );

  assert.throws(
    () =>
      buildApprovalPayload({
        gate: "architecture_plan",
        artifacts: [{ artifact_id: "arch-v1", version: 1, sha256: HASH_A }],
        decision: "approve",
        comment: "",
      }),
    /2 artifact/i,
  );

  const gate2 = buildApprovalPayload({
    gate: "architecture_plan",
    artifacts: [
      { artifact_id: "arch-v1", version: 1, sha256: HASH_A },
      { artifact_id: "plan-v1", version: 1, sha256: HASH_B },
    ],
    decision: "approve",
    comment: "Khớp FR",
  });
  assert.equal(gate2.artifacts.length, 2);
});

test("PlatformApiClient scopes getArtifact with run_id and surfaces 409 approval_version_conflict", async () => {
  const seenUrls: string[] = [];
  const fakeFetch = async (input: string, init?: RequestInit) => {
    seenUrls.push(input);
    if (input === "/artifacts/req-v2?run_id=r1") {
      return new Response(
        JSON.stringify({
          run_id: "r1",
          artifact_id: "req-v2",
          kind: "requirements",
          version: 2,
          sha256: HASH_B,
          previous_artifact_id: "req-v1",
          media_type: "application/json",
          content: '{"functional":[]}',
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    if (input === "/runs/r1/approvals" && init?.method === "POST") {
      return new Response(
        JSON.stringify({
          code: "approval_version_conflict",
          message: "Tải lại phiên bản mới trước khi duyệt.",
        }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      );
    }
    return new Response(JSON.stringify({ code: "not_found", message: "not_found" }), { status: 404 });
  };

  const client = new PlatformApiClient("", fakeFetch);
  const art = await client.getArtifact("r1", "req-v2");
  assert.equal(art.previous_artifact_id, "req-v1");
  assert.ok(seenUrls.includes("/artifacts/req-v2?run_id=r1"));

  await assert.rejects(
    () =>
      client.submitApproval("r1", {
        gate: "requirements",
        artifacts: [{ artifact_id: "req-v1", version: 1, sha256: HASH_A }],
        decision: "approve",
        comment: "",
      }),
    (err: unknown) =>
      err instanceof PlatformApiError &&
      err.status === 409 &&
      err.code === "approval_version_conflict",
  );
});

test("computeLineDiff identifies unchanged, removed, and added lines", () => {
  const lines = computeLineDiff("line 1\nold rule\nline 3", "line 1\nnew rule\nline 3");
  assert.deepEqual(lines, [
    { kind: "same", text: "line 1" },
    { kind: "removed", text: "old rule" },
    { kind: "added", text: "new rule" },
    { kind: "same", text: "line 3" },
  ]);
});

test("buildTraceRows links FR -> task -> patch -> test reports and buildAcceptancePayload validates manifest", () => {
  const rows = buildTraceRows(
    [
      {
        task_id: "TASK-01",
        title: "Validate empty title",
        status: "done",
        requirement_ids: ["FR-TITLE", "FR-CRUD"],
        dependency_ids: [],
        patch_artifact_ids: ["patch-1"],
      },
    ],
    [
      {
        report_id: "rep-1",
        task_id: "TASK-01",
        suite_id: "development",
        commit: "c".repeat(40),
        exit_code: 0,
        passed: 4,
        failed: 0,
        skipped: 0,
        errors: 0,
        log_artifact_id: "log-1",
        bug_artifact_ids: [],
        trace_artifact_ids: ["trace-1"],
      },
    ],
  );
  assert.equal(rows.length, 2);
  assert.equal(rows[0].requirement_id, "FR-TITLE");
  assert.deepEqual(rows[0].patch_artifact_ids, ["patch-1"]);
  assert.equal(rows[0].reports[0].passed, 4);

  const accepted = buildAcceptancePayload({
    manifest: { artifact_id: "manifest-v1", version: 1, sha256: HASH_A },
    decision: "accept",
    comment: "Đã đối chiếu ZIP và test report",
  });
  assert.equal(accepted.decision, "accept");

  assert.throws(
    () =>
      buildAcceptancePayload({
        manifest: { artifact_id: "manifest-v1", version: 1, sha256: HASH_A },
        decision: "request_changes",
        comment: "",
      }),
    /bắt buộc/i,
  );
});
