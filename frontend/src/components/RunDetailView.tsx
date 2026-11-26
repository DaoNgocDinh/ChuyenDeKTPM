import { FormEvent, useEffect, useRef, useState } from "react";
import { PlatformApiClient, PlatformApiError } from "../api/client.ts";
import {
  extractPendingQuestions,
  isTerminalRunStatus,
  mergeEventsPage,
  SIX_ROLES,
} from "../api/polling.ts";
import type {
  ArtifactDetail,
  EventItem,
  NextAction,
  RunDetail,
  TaskItem,
} from "../api/types.ts";

interface RunDetailViewProps {
  client: PlatformApiClient;
  runId: string;
  pollIntervalMs?: number;
  onNavigateAction?: (action: NextAction) => void;
}

export function RunDetailView({
  client,
  runId,
  pollIntervalMs = 2500,
  onNavigateAction,
}: RunDetailViewProps) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [cursor, setCursor] = useState(0);
  const cursorRef = useRef(0);

  const [pollingEnabled, setPollingEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState(false);

  const [questionArtifact, setQuestionArtifact] = useState<ArtifactDetail | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [clarifyMessage, setClarifyMessage] = useState<string | null>(null);

  useEffect(() => {
    cursorRef.current = 0;
    setCursor(0);
    setEvents([]);
    setRun(null);
    setTasks([]);
    setQuestionArtifact(null);
    setAnswers({});
    setError(null);
  }, [runId]);

  async function pollOnce(signal?: AbortSignal) {
    try {
      const [runData, tasksData, eventsPage] = await Promise.all([
        client.getRun(runId, signal),
        client.getTasks(runId, signal),
        client.getEvents(runId, cursorRef.current, signal),
      ]);
      setRun(runData);
      setTasks(tasksData);
      setEvents((prev) => {
        const merged = mergeEventsPage(prev, cursorRef.current, eventsPage);
        cursorRef.current = merged.cursor;
        setCursor(merged.cursor);
        return merged.items;
      });
      setError(null);
      if (isTerminalRunStatus(runData.status)) {
        setPollingEnabled(false);
      }
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        setError(
          err instanceof PlatformApiError
            ? `[${err.code}] ${err.message}`
            : "Không đọc được trạng thái run.",
        );
      }
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void pollOnce(controller.signal);
    if (!pollingEnabled) {
      return () => controller.abort();
    }
    const timer = window.setInterval(() => {
      void pollOnce(controller.signal);
    }, pollIntervalMs);
    return () => {
      window.clearInterval(timer);
      controller.abort();
    };
  }, [client, runId, pollingEnabled, pollIntervalMs]);

  useEffect(() => {
    const qid = run?.question_artifact_id;
    if (!qid) {
      setQuestionArtifact(null);
      return;
    }
    const controller = new AbortController();
    void client
      .getArtifact(runId, qid, controller.signal)
      .then((detail) => setQuestionArtifact(detail))
      .catch(() => setQuestionArtifact(null));
    return () => controller.abort();
  }, [client, runId, run?.question_artifact_id]);

  async function handleControl(kind: "cancel" | "resume") {
    setActionBusy(true);
    setError(null);
    try {
      if (kind === "cancel") {
        await client.cancelRun(runId);
      } else {
        await client.resumeRun(runId);
        setPollingEnabled(true);
      }
      await pollOnce();
    } catch (err) {
      setError(
        err instanceof PlatformApiError ? `[${err.code}] ${err.message}` : "Thao tác điều khiển thất bại.",
      );
    } finally {
      setActionBusy(false);
    }
  }

  async function handleSubmitClarification(event: FormEvent) {
    event.preventDefault();
    if (!questionArtifact) {
      return;
    }
    const pending = extractPendingQuestions(questionArtifact);
    const payloadAnswers = pending
      .map((q) => ({ question_id: q.question_id, answer: (answers[q.question_id] ?? "").trim() }))
      .filter((item) => item.answer.length > 0);
    if (payloadAnswers.length === 0) {
      setError("Cần nhập ít nhất một câu trả lời làm rõ.");
      return;
    }
    setActionBusy(true);
    setError(null);
    setClarifyMessage(null);
    try {
      const receipt = await client.submitClarifications(runId, {
        artifact: {
          artifact_id: questionArtifact.artifact_id,
          version: questionArtifact.version,
          sha256: questionArtifact.sha256,
        },
        answers: payloadAnswers,
      });
      setClarifyMessage(`Đã ghi câu trả lời (${receipt.decision_id}), trạng thái: ${receipt.status}.`);
      setPollingEnabled(true);
      await pollOnce();
    } catch (err) {
      setError(
        err instanceof PlatformApiError ? `[${err.code}] ${err.message}` : "Gửi câu trả lời thất bại.",
      );
    } finally {
      setActionBusy(false);
    }
  }

  const seenRoles = new Set(events.map((e) => (e.role ?? "").toLowerCase()).filter(Boolean));
  const pendingQuestions = extractPendingQuestions(questionArtifact);

  return (
    <section className="stack">
      <div className="panel">
        <div className="row-between">
          <div>
            <h2>Chi tiết run: <span className="mono">{runId}</span></h2>
            {run && (
              <p className="small muted">
                Project: <span className="mono">{run.project_id}</span> · Stage:{" "}
                <strong>{run.stage ?? "chưa bắt đầu"}</strong> · Step:{" "}
                <span className="mono">{run.current_step_id ?? "—"}</span>
              </p>
            )}
          </div>
          <div className="row">
            {run && <span className={`badge status-${run.status}`}>{run.status}</span>}
            <button type="button" className="secondary" onClick={() => void pollOnce()}>
              Poll ngay
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => setPollingEnabled((v) => !v)}
            >
              {pollingEnabled ? "Tạm dừng poll" : "Bật auto-poll"}
            </button>
          </div>
        </div>

        {error && (
          <div className="alert error" role="alert">
            {error}
          </div>
        )}

        {run?.last_error && (
          <div className="alert warn" role="status">
            <strong>Lỗi gần nhất ({run.last_error.code}):</strong> {run.last_error.message}
          </div>
        )}

        {run && (
          <div className="metrics">
            <div className="metric">
              <span className="muted small">Input tokens</span>
              <strong>{run.quota.input_tokens}</strong>
            </div>
            <div className="metric">
              <span className="muted small">Output tokens</span>
              <strong>{run.quota.output_tokens}</strong>
            </div>
            <div className="metric">
              <span className="muted small">Tool calls</span>
              <strong>{run.quota.tool_calls}</strong>
            </div>
            <div className="metric">
              <span className="muted small">Usage</span>
              <strong>{run.quota.usage_complete ? "Đầy đủ" : "Thiếu usage"}</strong>
            </div>
            <div className="metric">
              <span className="muted small">Event cursor</span>
              <strong className="mono">after={cursor}</strong>
            </div>
          </div>
        )}

        <div className="role-strip" aria-label="Sáu vai trò logic">
          {SIX_ROLES.map((role) => {
            const active =
              seenRoles.has(role.toLowerCase()) ||
              (run?.stage?.toLowerCase().includes(role.toLowerCase()) ?? false);
            return (
              <span key={role} className={active ? "role-pill active" : "role-pill"}>
                {role}
              </span>
            );
          })}
        </div>

        {run && run.next_actions.length > 0 && (
          <div className="row" aria-label="Hành động khả dụng">
            {run.next_actions.includes("cancel") && (
              <button
                type="button"
                className="danger"
                disabled={actionBusy}
                onClick={() => void handleControl("cancel")}
              >
                Dừng run (cancel)
              </button>
            )}
            {run.next_actions.includes("resume") && (
              <button
                type="button"
                disabled={actionBusy}
                onClick={() => void handleControl("resume")}
              >
                Khôi phục (resume)
              </button>
            )}
            {run.next_actions.includes("review") && onNavigateAction && (
              <button type="button" onClick={() => onNavigateAction("review")}>
                Mở màn hình duyệt artifact
              </button>
            )}
            {(run.next_actions.includes("inspect") || run.next_actions.includes("accept_output")) &&
              onNavigateAction && (
                <button type="button" className="secondary" onClick={() => onNavigateAction("inspect")}>
                  Xem mã, test &amp; truy vết
                </button>
              )}
          </div>
        )}
      </div>

      {run?.next_actions.includes("clarify") && questionArtifact && (
        <div className="panel">
          <h3>Câu hỏi làm rõ (v{questionArtifact.version})</h3>
          <p className="small muted mono">
            artifact={questionArtifact.artifact_id} · sha256={questionArtifact.sha256.slice(0, 12)}…
          </p>
          {clarifyMessage && <div className="alert ok">{clarifyMessage}</div>}
          <form onSubmit={handleSubmitClarification} className="stack">
            {pendingQuestions.length === 0 ? (
              <pre className="code-block">{questionArtifact.content}</pre>
            ) : (
              pendingQuestions.map((q) => (
                <label key={q.question_id}>
                  <span>
                    <strong>{q.question_id}:</strong> {q.prompt}
                  </span>
                  <input
                    type="text"
                    value={answers[q.question_id] ?? ""}
                    onChange={(e) =>
                      setAnswers((prev) => ({ ...prev, [q.question_id]: e.target.value }))
                    }
                    placeholder="Nhập câu trả lời của chủ dự án..."
                  />
                </label>
              ))
            )}
            <button type="submit" disabled={actionBusy || pendingQuestions.length === 0}>
              Gửi câu trả lời làm rõ
            </button>
          </form>
        </div>
      )}

      <div className="grid-two">
        <div className="panel">
          <h3>Danh sách task ({tasks.length})</h3>
          {tasks.length === 0 ? (
            <p className="muted">Chưa có task nào trong run này.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Trạng thái</th>
                  <th>FR</th>
                  <th>Phụ thuộc</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => (
                  <tr key={task.task_id}>
                    <td>
                      <strong className="mono">{task.task_id}</strong>
                      <div className="small">{task.title}</div>
                    </td>
                    <td>
                      <span className={`badge status-${task.status}`}>{task.status}</span>
                    </td>
                    <td className="mono small">{task.requirement_ids.join(", ") || "—"}</td>
                    <td className="mono small">{task.dependency_ids.join(", ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="panel">
          <h3>Timeline sự kiện ({events.length})</h3>
          {events.length === 0 ? (
            <p className="muted">Chưa nhận được sự kiện mới (cursor={cursor}).</p>
          ) : (
            <ol className="timeline">
              {events.map((ev) => (
                <li key={ev.sequence} className="timeline-item">
                  <div className="row-between small muted">
                    <span className="mono">
                      #{ev.sequence} · {ev.kind}
                      {ev.role ? ` · ${ev.role}` : ""}
                    </span>
                    <span>{ev.created_at}</span>
                  </div>
                  <div>{ev.message}</div>
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
    </section>
  );
}
