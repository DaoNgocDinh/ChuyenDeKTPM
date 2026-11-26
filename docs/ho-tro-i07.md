# I07 (Phần hỗ trợ trước) · Hai cổng duyệt và Quản lý thay đổi yêu cầu

> **Trạng thái:** Đây là **phần hỗ trợ trước (draft/support)** cho [Issue #30 (`I07`)](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/30), **chưa phải bản nghiệm thu cuối**. Issue `#30` vẫn giữ `OPEN` và cần nối trực tiếp với `I06` (Orchestrator) cùng `I22` (FastAPI API) sau khi hoàn thiện các nhánh đó.

## Thành phần đã dựng (trên nền `I02`, `I03`, `D07`, `D08`, `D10`)

- `backend/approvals.py` (`ApprovalService`):
  - `open_gate(...)`: khóa trạng thái run từ `running → waiting_approval` kèm `pending_gate` cho Cổng 1 (`requirements`) hoặc Cổng 2 nguyên tử (`architecture` + `plan` tham chiếu đúng phiên bản `architecture`).
  - `decide_gate(...)`: ghi quyết định nguyên tử vào bảng `approvals` và chuyển trạng thái qua `D08` (`approve_current` / `request_revision`). Từ chối tuyệt đối mọi phê duyệt sai `run_id`, sai phiên bản hoặc sai SHA-256 bằng `ApprovalVersionConflict` (`approval_version_conflict`). Khi `request_changes`, yêu cầu `comment` khác rỗng, ghi đường định tuyến về vai trò phù hợp và đánh dấu các artifact cần xét lại.
  - `is_gate_approved(...)`: guard tin cậy của Host để `I06` kiểm tra trước khi mở `Architecture` (Cổng 1) hoặc `Dev` (Cổng 2); phê duyệt cho `v1` không bao giờ mở khóa cho `v2`.
  - `record_clarification(...)` và `compute_requirement_change_impact(...)`: gắn câu trả lời làm rõ vào đúng phiên bản artifact và xác định toàn bộ `architecture`/`plan`/`tasks` bị lỗi thời khi yêu cầu nâng lên phiên bản mới.

## Cách chạy kiểm tra

```sh
uv run --frozen python -m unittest tests.test_approvals -v
```
