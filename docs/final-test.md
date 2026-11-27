# Nhánh tích hợp kiểm thử `Final-Test`

Nhánh `Final-Test` gộp toàn bộ mã nguồn đã hoàn thiện từ các nhánh `I01`–`I25` (gồm cả `I22-api`), `D05`–`D11`, `E01`, `E02`, `E03`, `E07` và bổ sung bộ khởi chạy hợp nhất `backend/platform_runtime.py` nối trực tiếp FastAPI + Worker + Orchestrator + 6 Agent + RecoveryService (`I20`).

## 1. Chạy bộ kiểm thử tự động

```powershell
# Kiểm tra toàn vẹn bộ đề nghiệm thu độc lập E01
uv run --frozen python -m evaluation.checksums

# Chạy toàn bộ backend + evaluation + experiment + integration tests
uv run --frozen python -m unittest discover -s tests -p "test_*.py" -v

# Kiểm tra lint Python
uvx ruff check --select E4,E7,E9,F backend evaluation experiments tests

# Chạy test & build Frontend React (I23 + I24)
Set-Location frontend
npm ci
node --test tests/i23.test.ts tests/i24.test.ts
npm run build
```

> Lưu ý: Các ca cần Docker thật hoặc model Neon High thật được mở bằng biến môi trường `KTPM_TEST_RUNNER_IMAGE=<image-I15>`, `KTPM_LIVE_MODEL=1`, `SDLC_LIVE_MODEL=1`.

## 2. Chạy thử toàn bộ hệ thống cục bộ (Backend API + Worker + React UI)

Terminal 1 — khởi chạy Backend FastAPI (`127.0.0.1:8000`) kèm Worker nền 6 agent:
```powershell
uv run --frozen python -m backend.platform_runtime --db data/platform.sqlite --workspaces data/workspaces --host 127.0.0.1 --port 8000
```

Terminal 2 — khởi chạy giao diện React (`localhost:5173`):
```powershell
Set-Location frontend
npm run dev
```
