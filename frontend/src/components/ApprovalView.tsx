import { FormEvent, useEffect, useState } from "react";
import { PlatformApiClient, PlatformApiError } from "../api/client.ts";
import { buildApprovalPayload, computeLineDiff, toArtifactRef } from "../api/review.ts";
import type {
  ApprovalDecision,
  ApprovalGate,
  ArtifactDetail,
  ArtifactItem,
  RunDetail,
} from "../api/types.ts";

interface ApprovalViewProps {
  client: PlatformApiClient;
  runId: string;
}

function latestByKind(items: readonly ArtifactItem[], kind: string): ArtifactItem | undefined {
  return items
    .filter((a) => a.kind.toLowerCase() === kind.toLowerCase())
    .sort((a, b) => b.version - a.version)[0];
}

export function ApprovalView({ client, runId }: ApprovalViewProps) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ArtifactDetail | null>(null);
  const [previousDetail, setPreviousDetail] = useState<ArtifactDetail | null>(null);
  const [showDiff, setShowDiff] = useState(false);

  const [gate, setGate] = useState<ApprovalGate>("requirements");
  const [gatePrimaryId, setGatePrimaryId] = useState("");
  const [gateSecondaryId, setGateSecondaryId] = useState("");
  const [decision, setDecision] = useState<ApprovalDecision>("approve");
  const [comment, setComment] = useState("");

  const [busy, setBusy] = useState(false);
  const [staleConflict, setStaleConflict] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [receiptMsg, setReceiptMsg] = useState<string | null>(null);

  async function loadAll(signal?: AbortSignal) {
    setError(null);
    setStaleConflict(null);
    try {
      const [runData, list] = await Promise.all([
        client.getRun(runId, signal),
        client.listArtifacts(runId, undefined, signal),
      ]);
      setRun(runData);
      setArtifacts(list);

      const gateIds = runData.gate_artifact_ids ?? [];
      if (gateIds.length === 2) {
        setGate("architecture_plan");
        setGatePrimaryId(gateIds[0]);
        setGateSecondaryId(gateIds[1]);
        setSelectedId((prev) => prev ?? gateIds[0]);
      } else if (gateIds.length === 1) {
        setGate("requirements");
        setGatePrimaryId(gateIds[0]);
        setGateSecondaryId("");
        setSelectedId((prev) => prev ?? gateIds[0]);
      } else {
        const req = latestByKind(list, "requirements");
        const arch = latestByKind(list, "architecture");
        const plan = latestByKind(list, "plan");
        if (arch && plan) {
          setGate("architecture_plan");
          setGatePrimaryId(arch.artifact_id);
          setGateSecondaryId(plan.artifact_id);
          setSelectedId((prev) => prev ?? arch.artifact_id);
        } else if (req) {
          setGate("requirements");
          setGatePrimaryId(req.artifact_id);
          setGateSecondaryId("");
          setSelectedId((prev) => prev ?? req.artifact_id);
        } else if (list.length > 0) {
          setSelectedId((prev) => prev ?? list[0].artifact_id);
        }
      }
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        setError(err instanceof Error ? err.message : "Không tải được danh sách artifact.");
      }
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void loadAll(controller.signal);
    return () => controller.abort();
  }, [client, runId]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setPreviousDetail(null);
      return;
    }
    const controller = new AbortController();
    setPreviousDetail(null);
    void client
      .getArtifact(runId, selectedId, controller.signal)
      .then(async (current) => {
        setDetail(current);
        if (current.previous_artifact_id) {
          try {
            const prev = await client.getArtifact(
              runId,
              current.previous_artifact_id,
              controller.signal,
            );
            setPreviousDetail(prev);
          } catch {
            setPreviousDetail(null);
          }
        }
      })
      .catch((err) => {
        if (!(err instanceof DOMException && err.name === "AbortError")) {
          setError(err instanceof Error ? err.message : "Không đọc được nội dung artifact.");
        }
      });
    return () => controller.abort();
  }, [client, runId, selectedId]);

  async function handleSubmitDecision(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setStaleConflict(null);
    setReceiptMsg(null);

    const byId = new Map(artifacts.map((a) => [a.artifact_id, a]));
    const selectedRefs =
      gate === "requirements"
        ? [byId.get(gatePrimaryId)].filter((x): x is ArtifactItem => Boolean(x)).map(toArtifactRef)
        : [byId.get(gatePrimaryId), byId.get(gateSecondaryId)]
            .filter((x): x is ArtifactItem => Boolean(x))
            .map(toArtifactRef);

    let payload;
    try {
      payload = buildApprovalPayload({
        gate,
        artifacts: selectedRefs,
        decision,
        comment,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Dữ liệu quyết định duyệt chưa hợp lệ.");
      return;
    }

    setBusy(true);
    try {
      const receipt = await client.submitApproval(runId, payload);
      setReceiptMsg(
        `Đã ghi quyết định nguyên tử (${receipt.decision_id}). Trạng thái run: ${receipt.status}.`,
      );
      setComment("");
      await loadAll();
    } catch (err) {
      if (err instanceof PlatformApiError && err.code === "approval_version_conflict") {
        setStaleConflict(
          `[409 approval_version_conflict] ${err.message} — Hãy tải lại phiên bản mới trước khi duyệt.`,
        );
      } else if (err instanceof PlatformApiError) {
        setError(`[${err.code}] ${err.message}`);
      } else {
        setError("Gửi quyết định duyệt thất bại.");
      }
    } finally {
      setBusy(false);
    }
  }

  const diffLines =
    showDiff && detail && previousDetail
      ? computeLineDiff(previousDetail.content, detail.content)
      : [];

  return (
    <section className="stack">
      <div className="panel">
        <div className="row-between">
          <div>
            <h2>Duyệt artifact · Run <span className="mono">{runId}</span></h2>
            {run && (
              <p className="small muted">
                Trạng thái: <strong>{run.status}</strong> · Stage: <strong>{run.stage ?? "—"}</strong>
              </p>
            )}
          </div>
          <button type="button" className="secondary" onClick={() => void loadAll()}>
            Tải lại phiên bản hiện hành
          </button>
        </div>

        {staleConflict && (
          <div className="alert warn" role="alert">
            <div className="row-between">
              <span>{staleConflict}</span>
              <button type="button" onClick={() => void loadAll()}>
                Tải lại phiên bản mới
              </button>
            </div>
          </div>
        )}
        {error && (
          <div className="alert error" role="alert">
            {error}
          </div>
        )}
        {receiptMsg && <div className="alert ok">{receiptMsg}</div>}
      </div>

      <div className="grid-two">
        <div className="panel">
          <h3>Phiên bản artifact trong run ({artifacts.length})</h3>
          {artifacts.length === 0 ? (
            <p className="muted">Chưa có artifact nào trong run này.</p>
          ) : (
            <ul className="list">
              {artifacts.map((art) => (
                <li key={art.artifact_id}>
                  <button
                    type="button"
                    className={art.artifact_id === selectedId ? "list-item active" : "list-item"}
                    onClick={() => setSelectedId(art.artifact_id)}
                  >
                    <span>
                      <strong>{art.kind}</strong> v{art.version}
                    </span>
                    <span className="mono small">
                      {art.artifact_id} · {art.sha256.slice(0, 8)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          <hr />
          <h3>Gửi quyết định cổng duyệt</h3>
          {run && run.status !== "waiting_approval" && (
            <div className="alert warn" role="status">
              Run hiện ở trạng thái <strong>{run.status}</strong>, không đang chờ duyệt cổng. Hãy sang tab{" "}
              <strong>2. Theo dõi Run</strong> để xem chi tiết lỗi hoặc bấm <strong>Khôi phục (resume)</strong>.
            </div>
          )}
          <form onSubmit={handleSubmitDecision} className="stack">
            <label>
              <span>Cổng duyệt</span>
              <select
                value={gate}
                onChange={(e) => setGate(e.target.value as ApprovalGate)}
              >
                <option value="requirements">Cổng 1 · Requirements (1 bản)</option>
                <option value="architecture_plan">
                  Cổng 2 · Architecture + Plan (nguyên tử 2 bản)
                </option>
              </select>
            </label>

            <label>
              <span>{gate === "requirements" ? "Artifact Requirements" : "Artifact Architecture"}</span>
              <select value={gatePrimaryId} onChange={(e) => setGatePrimaryId(e.target.value)}>
                <option value="">-- Chọn artifact --</option>
                {artifacts.map((a) => (
                  <option key={a.artifact_id} value={a.artifact_id}>
                    {a.kind} v{a.version} ({a.artifact_id} · {a.sha256.slice(0, 8)})
                  </option>
                ))}
              </select>
            </label>

            {gate === "architecture_plan" && (
              <label>
                <span>Artifact Plan (cùng cổng 2)</span>
                <select value={gateSecondaryId} onChange={(e) => setGateSecondaryId(e.target.value)}>
                  <option value="">-- Chọn artifact plan --</option>
                  {artifacts.map((a) => (
                    <option key={a.artifact_id} value={a.artifact_id}>
                      {a.kind} v{a.version} ({a.artifact_id} · {a.sha256.slice(0, 8)})
                    </option>
                  ))}
                </select>
              </label>
            )}

            <label>
              <span>Quyết định</span>
              <select
                value={decision}
                onChange={(e) => setDecision(e.target.value as ApprovalDecision)}
              >
                <option value="approve">Chấp nhận (approve)</option>
                <option value="request_changes">Yêu cầu sửa (request_changes)</option>
              </select>
            </label>

            <label>
              <span>
                Ghi chú {decision === "request_changes" ? "(bắt buộc)" : "(tùy chọn)"}
              </span>
              <textarea
                rows={3}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Nêu rõ yêu cầu chỉnh sửa hoặc ghi chú duyệt..."
                required={decision === "request_changes"}
              />
            </label>

            <button type="submit" disabled={busy || (run !== null && run.status !== "waiting_approval")}>
              {busy ? "Đang ghi quyết định..." : "Xác nhận quyết định cổng"}
            </button>
          </form>
        </div>

        <div className="panel">
          <div className="row-between">
            <h3>Nội dung artifact đang xem</h3>
            {detail && previousDetail && (
              <button
                type="button"
                className="secondary"
                onClick={() => setShowDiff((v) => !v)}
              >
                {showDiff
                  ? "Xem nội dung hiện hành"
                  : `So sánh với v${previousDetail.version}`}
              </button>
            )}
          </div>
          {!detail ? (
            <p className="muted">Chọn một artifact ở cột bên trái để đọc nội dung và hash.</p>
          ) : (
            <div className="stack">
              <div className="small muted mono">
                id={detail.artifact_id} · kind={detail.kind} · v{detail.version} ·{" "}
                {detail.media_type}
                <br />
                sha256={detail.sha256}
                {detail.previous_artifact_id ? ` · previous=${detail.previous_artifact_id}` : ""}
              </div>

              {showDiff && previousDetail ? (
                <div className="diff-view" aria-label="So sánh phiên bản">
                  {diffLines.map((line, idx) => (
                    <div key={idx} className={`diff-line diff-${line.kind}`}>
                      <span className="diff-prefix">
                        {line.kind === "added" ? "+" : line.kind === "removed" ? "-" : " "}
                      </span>
                      <span>{line.text}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <pre className="code-block">{detail.content}</pre>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
