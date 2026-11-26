# I20 · Cancel, Resume và `pending_recovery` an toàn

`backend/recovery.py` kết nối với `worker.py`, `llm.py`, `gateway.py`, `workspace.py`, `mcp_tools.py` và `orchestrator.py` để hủy tiến trình con có kiểm soát và khôi phục sau sự cố mà **không bao giờ áp lại patch mù quáng**:

- **Hủy có kiểm soát (`RecoveryService.cancel` + `RunSignal` + `controlled_command`):**
  - Thu hồi lease ngay lập tức, gắn `cancel_requested = true` trong `checkpoint_json` và theo dõi tài nguyên đang sống (`resource.started` / `resource.stopped` cho CLI model `llm.py` và Docker runner `mcp_tools.py`).
  - Khi còn tiến trình con, đặt `pending_recovery`, chấm dứt toàn bộ cây tiến trình (`taskkill /T /F` trên Windows / `os.killpg` trên POSIX) và chỉ chốt trạng thái `cancelled` + `ended_at` sau khi xác nhận dừng hết tài nguyên. Run `cancelled` không thể `resume`.
- **Biên nhận theo `operation_id` (`Gateway` + `Workspace.operation_receipt`):**
  - Trước khi chạy `workspace.apply_patch`, `Gateway` ghi `pending_effect = {operation_id, step_id, task_id, input_commit, patch_hash}` vào `checkpoint_json`; `Workspace.apply(..., operation_id=...)` ghi nguyên tử biên nhận `logs/op-<operation_id>.json` sau khi Git commit thành công.
- **Đối chiếu khi `RecoveryService.resume`:**
  - Xác minh toàn vẹn `input_refs` (đọc và kiểm SHA-256 trong `ArtifactStore`), quyết định duyệt hiện hành ở `approved_gates`, không còn `logs/pending-patch.json`, không còn task `blocked` cần chủ dự án xử lý, và trạng thái sạch của Git workspace.
  - Nếu crash xảy ra **sau** khi `Dev` đã commit patch nhưng **trước** khi đóng step/checkpoint: đối chiếu khớp `Checkpoint(operation_id, input_commit, patch_hash, output_commit)` qua `recovery_action(...)`, `git rev-parse`, và `git diff` → đánh dấu step `reconciled`, `tool_calls = 'ok'`, task `waiting_test`, lưu `recovered_patch` và xếp run về `queued` (`resume_at_tester`) để `Orchestrator` chạy thẳng bước `Tester` mà **không lặp lại `Dev`**.
  - Nếu thiếu biên nhận, còn `pending-patch.json`, input/approval/workspace bị thay đổi hoặc còn task `blocked`: ghi `recovery.blocked`, giữ nguyên `pending_recovery`/`needs_human_review` và từ chối chạy lặp.

**Test** · `uv run --frozen python -m unittest tests.test_recovery tests.test_worker tests.test_gateway tests.test_orchestrator tests.test_mcp_tools tests.test_workspace -v` và `uvx ruff check --select E4,E7,E9,F backend tests`.
