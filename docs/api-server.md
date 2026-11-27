# I22 · Backend HTTP API cục bộ (nhánh `I22-api`)

Hiện thực đầy đủ hợp đồng OpenAPI 3.1.1 đã duyệt tại [D10](openapi.json) và khớp trực tiếp với client React của `I23`–`I24` (`backend/api/server.py`):

- **Phạm vi và bảo mật cục bộ:** `serve_local(...)` chỉ cho phép bind trên loopback (`127.0.0.1`, `localhost`, `::1`); mọi lỗi trả về thống nhất theo schema `{"code", "message"}` của D10 (`not_found`, `approval_version_conflict`, `invalid_transition`, `tool_denied`, `budget_exceeded`, `invalid_request`, `idempotency_conflict`).
- **Đủ 14 endpoint D10 + `/health`:**
  - `GET/POST /projects`, `GET/POST /projects/{project_id}/runs` (`202` + kiểm tra `idempotency_key` chống sinh job trùng và báo `409 idempotency_conflict` nếu đổi payload).
  - `GET /runs/{run_id}` (trạng thái, `stage`, `current_step_id`, `quota`, `next_actions`, `last_error`, `gate_artifact_ids`, `question_artifact_id`).
  - `GET /runs/{run_id}/events?after=...` (cursor tăng dần ổn định, trang rỗng giữ nguyên `next_cursor`).
  - `GET /runs/{run_id}/artifacts` (kèm `previous_artifact_id` để UI so sánh diff) và `GET /artifacts/{artifact_id}?run_id=...` (chặn đọc chéo run bằng `404 not_found`).
  - `POST /runs/{run_id}/approvals` (cổng 1 và cổng 2 nguyên tử qua `ApprovalService`, chặn phiên bản/hash cũ bằng `409 approval_version_conflict`), `POST /runs/{run_id}/clarifications`.
  - `POST /runs/{run_id}/cancel` (`202`), `POST /runs/{run_id}/resume` (`202`, từ chối trên run đã kết thúc hoặc khi còn `pending-patch.json` chưa đối chiếu).
  - `GET /runs/{run_id}/tasks`, `GET /runs/{run_id}/test-reports`, `GET /runs/{run_id}/export` (gọi `build_export_zip` của I25, lọc secret/traversal), `POST /runs/{run_id}/acceptance`.

**Test** · `uv run --frozen python -m unittest tests.test_api tests.test_api_contract tests.test_orchestrator tests.test_approvals tests.test_exporter -v` và `uvx ruff check --select E4,E7,E9,F backend tests`.
