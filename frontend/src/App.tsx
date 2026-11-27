import { useEffect, useMemo, useState } from "react";
import { PlatformApiClient } from "./api/client.ts";
import { parseRunIdFromHash } from "./api/polling.ts";
import type { NextAction } from "./api/types.ts";
import { ApprovalView } from "./components/ApprovalView.tsx";
import { CodeTestTraceView } from "./components/CodeTestTraceView.tsx";
import { ProjectsView } from "./components/ProjectsView.tsx";
import { RunDetailView } from "./components/RunDetailView.tsx";

type Screen = "projects" | "run" | "approvals" | "inspect";

export function App() {
  const client = useMemo(() => new PlatformApiClient(), []);
  const [healthText, setHealthText] = useState("Đang kiểm tra API…");
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(() =>
    parseRunIdFromHash(window.location.hash),
  );
  const [screen, setScreen] = useState<Screen>(() =>
    parseRunIdFromHash(window.location.hash) ? "run" : "projects",
  );

  useEffect(() => {
    const controller = new AbortController();
    void client
      .checkHealth(controller.signal)
      .then((res) => {
        setHealthText(res.status === "ok" ? "API cục bộ đang hoạt động" : "Phản hồi API không hợp lệ");
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setHealthText("Chưa kết nối được API FastAPI cục bộ");
        }
      });
    return () => controller.abort();
  }, [client]);

  useEffect(() => {
    const onHashChange = () => {
      const fromHash = parseRunIdFromHash(window.location.hash);
      if (fromHash) {
        setActiveRunId(fromHash);
        setScreen((prev) => (prev === "projects" ? "run" : prev));
      }
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  function openRun(runId: string) {
    setActiveRunId(runId);
    setScreen("run");
    window.location.hash = `#/runs/${encodeURIComponent(runId)}`;
  }

  function handleNavigateAction(action: NextAction) {
    if (action === "review") {
      setScreen("approvals");
    } else if (action === "inspect" || action === "accept_output") {
      setScreen("inspect");
    }
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <h1>Nền tảng Multi-Agent 6 Vai Trò</h1>
          <p className="small muted" role="status">
            {healthText}
          </p>
        </div>
        <nav className="tabs" aria-label="Điều hướng bốn màn hình MVP">
          <button
            type="button"
            className={screen === "projects" ? "tab active" : "tab"}
            onClick={() => setScreen("projects")}
          >
            1. Dự án &amp; Run
          </button>
          <button
            type="button"
            className={screen === "run" ? "tab active" : "tab"}
            disabled={!activeRunId}
            onClick={() => setScreen("run")}
          >
            2. Theo dõi Run
          </button>
          <button
            type="button"
            className={screen === "approvals" ? "tab active" : "tab"}
            disabled={!activeRunId}
            onClick={() => setScreen("approvals")}
          >
            3. Duyệt Artifact
          </button>
          <button
            type="button"
            className={screen === "inspect" ? "tab active" : "tab"}
            disabled={!activeRunId}
            onClick={() => setScreen("inspect")}
          >
            4. Mã, Test &amp; Truy vết
          </button>
        </nav>
      </header>

      <main className="content">
        {screen === "projects" || !activeRunId ? (
          <ProjectsView
            client={client}
            selectedProjectId={selectedProjectId}
            onSelectProject={setSelectedProjectId}
            onOpenRun={openRun}
          />
        ) : screen === "run" ? (
          <RunDetailView
            client={client}
            runId={activeRunId}
            onNavigateAction={handleNavigateAction}
          />
        ) : screen === "approvals" ? (
          <ApprovalView client={client} runId={activeRunId} />
        ) : (
          <CodeTestTraceView client={client} runId={activeRunId} />
        )}
      </main>
    </div>
  );
}
