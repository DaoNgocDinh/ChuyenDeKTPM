import { FormEvent, useEffect, useRef, useState } from "react";
import { PlatformApiClient, PlatformApiError } from "../api/client.ts";
import { IdempotencyTracker } from "../api/polling.ts";
import type { Project, RunTicket } from "../api/types.ts";

interface ProjectsViewProps {
  client: PlatformApiClient;
  selectedProjectId: string | null;
  onSelectProject: (projectId: string) => void;
  onOpenRun: (runId: string) => void;
}

export function ProjectsView({
  client,
  selectedProjectId,
  onSelectProject,
  onOpenRun,
}: ProjectsViewProps) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [runs, setRuns] = useState<RunTicket[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [brief, setBrief] = useState("");
  const [constraintsText, setConstraintsText] = useState("");
  const [creatingProject, setCreatingProject] = useState(false);

  const [configRef, setConfigRef] = useState("");
  const [startingRun, setStartingRun] = useState(false);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const trackerRef = useRef(new IdempotencyTracker());

  const activeProject = projects.find((p) => p.project_id === selectedProjectId) ?? null;

  async function refreshProjects(signal?: AbortSignal) {
    setLoadingProjects(true);
    setError(null);
    try {
      const list = await client.listProjects(signal);
      setProjects(list);
      if (!selectedProjectId && list.length > 0) {
        onSelectProject(list[0].project_id);
      }
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        setError(err instanceof Error ? err.message : "Không tải được danh sách dự án.");
      }
    } finally {
      setLoadingProjects(false);
    }
  }

  async function refreshRuns(projectId: string, signal?: AbortSignal) {
    setLoadingRuns(true);
    try {
      const list = await client.listRuns(projectId, signal);
      setRuns(list);
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        setError(err instanceof Error ? err.message : "Không tải được lịch sử run.");
      }
    } finally {
      setLoadingRuns(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void refreshProjects(controller.signal);
    return () => controller.abort();
  }, [client]);

  useEffect(() => {
    if (!selectedProjectId) {
      setRuns([]);
      return;
    }
    const controller = new AbortController();
    void refreshRuns(selectedProjectId, controller.signal);
    setActiveKey(trackerRef.current.getOrCreate(selectedProjectId, configRef.trim() || undefined));
    return () => controller.abort();
  }, [client, selectedProjectId, configRef]);

  async function handleCreateProject(event: FormEvent) {
    event.preventDefault();
    if (!name.trim() || !brief.trim()) {
      setError("Tên dự án và brief không được để trống.");
      return;
    }
    setCreatingProject(true);
    setError(null);
    try {
      const constraints = constraintsText
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean);
      const created = await client.createProject({
        name: name.trim(),
        brief: brief.trim(),
        constraints,
      });
      setProjects((prev) => [created, ...prev]);
      onSelectProject(created.project_id);
      setName("");
      setBrief("");
      setConstraintsText("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Tạo dự án thất bại.");
    } finally {
      setCreatingProject(false);
    }
  }

  async function handleStartRun() {
    if (!selectedProjectId) {
      return;
    }
    const trimmedConfig = configRef.trim() || undefined;
    const key = trackerRef.current.getOrCreate(selectedProjectId, trimmedConfig);
    setActiveKey(key);
    setStartingRun(true);
    setError(null);
    try {
      const ticket = await client.createRun(selectedProjectId, {
        idempotency_key: key,
        ...(trimmedConfig ? { configuration_ref: trimmedConfig } : {}),
      });
      trackerRef.current.markSucceeded(selectedProjectId, trimmedConfig);
      setActiveKey(trackerRef.current.getOrCreate(selectedProjectId, trimmedConfig));
      setRuns((prev) => {
        const exists = prev.some((r) => r.run_id === ticket.run_id);
        return exists ? prev : [ticket, ...prev];
      });
      onOpenRun(ticket.run_id);
    } catch (err) {
      if (err instanceof PlatformApiError) {
        setError(`[${err.code}] ${err.message}`);
      } else {
        setError("Khởi chạy run thất bại. Nhấn gửi lại sẽ giữ nguyên idempotency_key.");
      }
    } finally {
      setStartingRun(false);
    }
  }

  function handleRegenerateKey() {
    if (!selectedProjectId) {
      return;
    }
    const next = trackerRef.current.rotate(selectedProjectId, configRef.trim() || undefined);
    setActiveKey(next);
    setError(null);
  }

  return (
    <section className="grid-two">
      <div className="panel">
        <h2>Tạo dự án mới</h2>
        <form onSubmit={handleCreateProject} className="stack">
          <label>
            <span>Tên dự án</span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ví dụ: A1 Quản lý công việc"
              required
            />
          </label>
          <label>
            <span>Mô tả yêu cầu (brief)</span>
            <textarea
              rows={4}
              value={brief}
              onChange={(e) => setBrief(e.target.value)}
              placeholder="Nhập mô tả nghiệp vụ cho dự án CRUD..."
              required
            />
          </label>
          <label>
            <span>Ràng buộc (mỗi dòng một mục)</span>
            <textarea
              rows={3}
              value={constraintsText}
              onChange={(e) => setConstraintsText(e.target.value)}
              placeholder="FastAPI + React + SQLite"
            />
          </label>
          <button type="submit" disabled={creatingProject}>
            {creatingProject ? "Đang tạo..." : "Tạo dự án"}
          </button>
        </form>

        <hr />
        <div className="row-between">
          <h3>Danh sách dự án ({projects.length})</h3>
          <button type="button" className="secondary" onClick={() => void refreshProjects()}>
            Tải lại
          </button>
        </div>
        {loadingProjects ? (
          <p className="muted">Đang tải danh sách dự án...</p>
        ) : projects.length === 0 ? (
          <p className="muted">Chưa có dự án nào trên máy cục bộ.</p>
        ) : (
          <ul className="list">
            {projects.map((proj) => (
              <li key={proj.project_id}>
                <button
                  type="button"
                  className={proj.project_id === selectedProjectId ? "list-item active" : "list-item"}
                  onClick={() => onSelectProject(proj.project_id)}
                >
                  <strong>{proj.name}</strong>
                  <span className="mono small">{proj.project_id}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="panel">
        <h2>Chi tiết dự án &amp; Lịch sử run</h2>
        {error && (
          <div className="alert error" role="alert">
            {error}
          </div>
        )}
        {!activeProject ? (
          <p className="muted">Chọn hoặc tạo một dự án để xem brief và khởi chạy run.</p>
        ) : (
          <div className="stack">
            <div>
              <h3>{activeProject.name}</h3>
              <p>{activeProject.brief}</p>
              {activeProject.constraints.length > 0 && (
                <ul className="chips">
                  {activeProject.constraints.map((c, idx) => (
                    <li key={`${c}-${idx}`} className="chip">
                      {c}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="card">
              <h3>Khởi chạy run mới</h3>
              <div className="stack">
                <label>
                  <span>Tham chiếu cấu hình (tùy chọn)</span>
                  <input
                    type="text"
                    value={configRef}
                    onChange={(e) => setConfigRef(e.target.value)}
                    placeholder="Để trống để dùng cấu hình mặc định của host"
                  />
                </label>
                <p className="small muted">
                  Khóa chống trùng lặp hiện hành:{" "}
                  <code className="mono">{activeKey ?? "chưa tạo"}</code>
                </p>
                <div className="row">
                  <button type="button" onClick={() => void handleStartRun()} disabled={startingRun}>
                    {startingRun ? "Đang xếp hàng..." : "Khởi chạy run (202)"}
                  </button>
                  <button type="button" className="secondary" onClick={handleRegenerateKey}>
                    Đổi khóa mới
                  </button>
                </div>
              </div>
            </div>

            <div>
              <div className="row-between">
                <h3>Lịch sử run ({runs.length})</h3>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => void refreshRuns(activeProject.project_id)}
                >
                  Làm mới
                </button>
              </div>
              {loadingRuns ? (
                <p className="muted">Đang tải lịch sử run...</p>
              ) : runs.length === 0 ? (
                <p className="muted">Dự án chưa có run nào.</p>
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Run ID</th>
                      <th>Trạng thái</th>
                      <th>Thao tác</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((run) => (
                      <tr key={run.run_id}>
                        <td className="mono">{run.run_id}</td>
                        <td>
                          <span className={`badge status-${run.status}`}>{run.status}</span>
                        </td>
                        <td>
                          <button type="button" className="secondary" onClick={() => onOpenRun(run.run_id)}>
                            Theo dõi
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
