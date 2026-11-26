import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

function PlatformStatus() {
  const [status, setStatus] = useState("Đang kiểm tra kết nối API…");
  useEffect(() => {
    const controller = new AbortController();
    async function checkHealth() {
      try {
        const response = await fetch("/health", { signal: controller.signal });
        if (!response.ok || (await response.json()).status !== "ok") {
          throw new Error("Invalid health response");
        }
        setStatus("API đang hoạt động.");
      } catch {
        if (!controller.signal.aborted) {
          setStatus("Chưa kết nối được API. Hãy kiểm tra tiến trình FastAPI rồi tải lại.");
        }
      }
    }
    void checkHealth();
    return () => controller.abort();
  }, []);
  return (
    <main>
      <h1>Trạng thái nền tảng</h1>
      <p role="status">{status}</p>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<PlatformStatus />);
