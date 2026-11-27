import { FormEvent, useEffect, useState } from "react";
import { PlatformApiClient, PlatformApiError } from "../api/client.ts";
import { buildAcceptancePayload, buildTraceRows, toArtifactRef } from "../api/review.ts";
import type {
  ArtifactDetail,
  ArtifactItem,
  TaskItem,
  TestReportItem,
} from "../api/types.ts";

interface CodeTestTraceViewProps {
  client: PlatformApiClient;
  runId: string;
}

export function CodeTestTraceView({ client, runId }: CodeTestTraceViewProps) {
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [reports, setReports] = useState<TestReportItem[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [inspected, setInspected] = useState<ArtifactDetail | null>(null);
  const [inspectTitle, setInspectTitle] = useState("");

  const [manifestId, setManifestId] = useState("");
  const [acceptanceDecision, setAcceptanceDecision] = useState<"accept" | "request_changes">("accept");
  const [acceptanceComment, setAcceptanceComment] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function loadAll(signal?: AbortSignal) {
    setError(null);
    try {
      const [taskList, reportList, artifactList] = await Promise.all([
        client.getTasks(runId, signal),
        client.getTestReports(runId, signal),
        client.listArtifacts(runId, undefined, signal),
      ]);
      setTasks(taskList);
      setReports(reportList);
      setArtifacts(artifactList);
      const manifestCandidate = artifactList
        .filter((a) => a.kind.toLowerCase().includes("manifest"))
        .sort((a, b) => b.version - a.version)[0];
      if (manifestCandidate) {
        setManifestId((prev) => prev || manifestCandidate.artifact_id);
      } else if (artifactList.length > 0) {
        setManifestId((prev) => prev || artifactList[artifactList.length - 1].artifact_id);
      }
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        setError(err instanceof Error ? err.message : "Không tải được dữ liệu mã và kiểm thử.");
      }
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void loadAll(controller.signal);
    return () => controller.abort();
  }, [client, runId]);

  async function inspectArtifact(artifactId: string, label: string) {
    setError(null);
    setInspectTitle(label);
    try {
      const data = await client.getArtifact(runId, artifactId);
      setInspected(data);
    } catch (err) {
      setError(
        err instanceof PlatformApiError ? `[${err.code}] ${err.message}` : `Không mở được ${artifactId}.`,
      );
    }
  }

  async function handleFinalAcceptance(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    const chosen = artifacts.find((a) => a.artifact_id === manifestId);
    if (!chosen) {
      setError("Hãy chọn đúng manifest artifact trước khi ghi quyết định nghiệm thu cuối.");
      return;
    }

    let payload;
    try {
      payload = buildAcceptancePayload({
        manifest: toArtifactRef(chosen),
        decision: acceptanceDecision,
        comment: acceptanceComment,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Dữ liệu nghiệm thu cuối không hợp lệ.");
      return;
    }

    setSubmitting(true);
    try {
      const receipt = await client.submitAcceptance(runId, payload);
      setNotice(`Đã ghi nghiệm thu cuối (${receipt.decision_id}), trạng thái run: ${receipt.status}.`);
      setAcceptanceComment("");
    } catch (err) {
      setError(
        err instanceof PlatformApiError ? `[${err.code}] ${err.message}` : "Ghi nghiệm thu cuối thất bại.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  const traceRows = buildTraceRows(tasks, reports);
  const diffArtifacts = artifacts.filter((a) =>
    ["patch", "diff", "dev_result", "bug_report", "review"].some((k) =>
      a.kind.toLowerCase().includes(k),
    ),
  );

  return (
    <section className="stack">
      <div className="panel">
        <div className="row-between">
          <div>
            <h2>Mã nguồn, Kiểm thử &amp; Truy vết · Run <span className="mono">{runId}</span></h2>
            <p className="small muted">
              Hiển thị riêng số ca đạt/lỗi/bỏ qua từ runner thật, liên kết FR → task → patch → test và gói export đã lọc secret.
            </p>
          </div>
          <div className="row">
            <button type="button" className="secondary" onClick={() => void loadAll()}>
              Làm mới
            </button>
            <a className="button-link" href={client.exportRunUrl(runId)} download>
              Tải ZIP Export
            </a>
          </div>
        </div>
        {error && (
          <div className="alert error" role="alert">
            {error}
          </div>
        )}
        {notice && <div className="alert ok">{notice}</div>}
      </div>

      <div className="panel">
        <h3>Báo cáo kiểm thử từ runner ({reports.length})</h3>
        {reports.length === 0 ? (
          <p className="muted">Chưa có test report cho run này.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Suite / Task</th>
                <th>Commit</th>
                <th>Exit</th>
                <th>Đạt</th>
                <th>Lỗi (Fail)</th>
                <th>Error</th>
                <th>Bỏ qua</th>
                <th>Bằng chứng</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((rep) => (
                <tr key={rep.report_id}>
                  <td>
                    <strong>{rep.suite_id}</strong>
                    <div className="mono small">{rep.task_id ?? "run-level"}</div>
                  </td>
                  <td className="mono small">{rep.commit.slice(0, 12)}</td>
                  <td className="mono">{rep.exit_code ?? "—"}</td>
                  <td>
                    <span className="badge status-completed">{rep.passed}</span>
                  </td>
                  <td>
                    <span className={rep.failed > 0 ? "badge status-failed" : "badge"}>{rep.failed}</span>
                  </td>
                  <td>
                    <span className={rep.errors > 0 ? "badge status-failed" : "badge"}>{rep.errors}</span>
                  </td>
                  <td>
                    <span className={rep.skipped > 0 ? "badge status-rework" : "badge"}>
                      {rep.skipped}
                    </span>
                  </td>
                  <td>
                    <div className="row">
                      {rep.log_artifact_id && (
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => void inspectArtifact(rep.log_artifact_id!, `Log runner (${rep.report_id})`)}
                        >
                          Log
                        </button>
                      )}
                      {rep.bug_artifact_ids.map((bid) => (
                        <button
                          key={bid}
                          type="button"
                          className="secondary"
                          onClick={() => void inspectArtifact(bid, `Bug report (${bid})`)}
                        >
                          Bug: {bid}
                        </button>
                      ))}
                      {rep.trace_artifact_ids.map((tid) => (
                        <button
                          key={tid}
                          type="button"
                          className="secondary"
                          onClick={() => void inspectArtifact(tid, `Trace (${tid})`)}
                        >
                          Trace: {tid}
                        </button>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <h3>Chuỗi truy vết FR → Task → Patch → Test ({traceRows.length})</h3>
        {traceRows.length === 0 ? (
          <p className="muted">Chưa có liên kết FR → task cho run này.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>FR</th>
                <th>Task &amp; Trạng thái</th>
                <th>Patch / Diff</th>
                <th>Test Report theo Commit</th>
              </tr>
            </thead>
            <tbody>
              {traceRows.map((row, idx) => (
                <tr key={`${row.requirement_id}-${row.task_id}-${idx}`}>
                  <td className="mono">
                    <strong>{row.requirement_id}</strong>
                  </td>
                  <td>
                    <span className="mono">{row.task_id}</span>{" "}
                    <span className={`badge status-${row.task_status}`}>{row.task_status}</span>
                  </td>
                  <td>
                    {row.patch_artifact_ids.length === 0 ? (
                      <span className="muted small">Chưa có patch</span>
                    ) : (
                      <div className="row">
                        {row.patch_artifact_ids.map((pid) => (
                          <button
                            key={pid}
                            type="button"
                            className="secondary"
                            onClick={() => void inspectArtifact(pid, `Patch / Diff (${pid})`)}
                          >
                            {pid}
                          </button>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="small">
                    {row.reports.length === 0 ? (
                      <span className="muted">Chưa chạy test</span>
                    ) : (
                      row.reports.map((r) => (
                        <div key={r.report_id} className="mono">
                          {r.suite_id}@{r.commit.slice(0, 8)}: pass={r.passed} fail={r.failed} err={r.errors} skip={r.skipped}
                        </div>
                      ))
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="grid-two">
        <div className="panel">
          <h3>Trình xem Diff / Bug / Log</h3>
          {diffArtifacts.length > 0 && (
            <div className="row" style={{ marginBottom: "0.6rem" }}>
              {diffArtifacts.map((art) => (
                <button
                  key={art.artifact_id}
                  type="button"
                  className="secondary"
                  onClick={() => void inspectArtifact(art.artifact_id, `${art.kind} v${art.version}`)}
                >
                  {art.kind} v{art.version}
                </button>
              ))}
            </div>
          )}
          {!inspected ? (
            <p className="muted">Chọn một nút Patch, Log, Bug hoặc Trace ở trên để mở nội dung gốc.</p>
          ) : (
            <div className="stack">
              <div className="small muted mono">
                {inspectTitle} · id={inspected.artifact_id} · v{inspected.version} · sha256=
                {inspected.sha256.slice(0, 12)}…
              </div>
              <pre className="code-block">{inspected.content}</pre>
            </div>
          )}
        </div>

        <div className="panel">
          <h3>Nghiệm thu cuối của chủ dự án</h3>
          <form onSubmit={handleFinalAcceptance} className="stack">
            <label>
              <span>Manifest đối chiếu (gắn ID, version, SHA-256)</span>
              <select value={manifestId} onChange={(e) => setManifestId(e.target.value)}>
                <option value="">-- Chọn manifest artifact --</option>
                {artifacts.map((a) => (
                  <option key={a.artifact_id} value={a.artifact_id}>
                    {a.kind} v{a.version} ({a.artifact_id} · {a.sha256.slice(0, 8)})
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Quyết định nghiệm thu</span>
              <select
                value={acceptanceDecision}
                onChange={(e) =>
                  setAcceptanceDecision(e.target.value as "accept" | "request_changes")
                }
              >
                <option value="accept">Chấp nhận sản phẩm cuối (accept)</option>
                <option value="request_changes">Yêu cầu sửa thêm (request_changes)</option>
              </select>
            </label>
            <label>
              <span>
                Nhận xét {acceptanceDecision === "request_changes" ? "(bắt buộc)" : "(tùy chọn)"}
              </span>
              <textarea
                rows={3}
                value={acceptanceComment}
                onChange={(e) => setAcceptanceComment(e.target.value)}
                placeholder="Ghi rõ căn cứ đối chiếu ZIP, mã và test report..."
                required={acceptanceDecision === "request_changes"}
              />
            </label>
            <button type="submit" disabled={submitting}>
              {submitting ? "Đang lưu..." : "Ghi nhận quyết định nghiệm thu cuối"}
            </button>
          </form>
        </div>
      </div>
    </section>
  );
}
