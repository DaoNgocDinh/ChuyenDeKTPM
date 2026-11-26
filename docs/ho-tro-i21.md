# I21 (Phần hỗ trợ trước) · Event Audit, Redaction và Chuỗi truy vết FR → Task → Patch → Test

> **Trạng thái:** Đây là **phần hỗ trợ trước (draft/support)** cho [Issue #44 (`I21`)](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/44), **chưa phải bản nghiệm thu cuối**. Issue `#44` vẫn giữ `OPEN` và cần nối dữ liệu thật từ `I17` (`Tester`) và `I18` (vòng `Tester → Dev`) trước khi nghiệm thu.

## Thành phần đã dựng (trên nền `I02`, `I03`, `I13`)

- `backend/trace.py` (`TraceAuditService`, `redact_payload`, `ERROR_CATEGORIES`):
  - `record_event(...)`: gắn `correlation_id`, phân loại lỗi đúng 4 nhóm (`schema`, `policy`, `environment`, `code`) và lọc đệ quy khóa nhạy cảm + chuỗi canary trước khi ghi bảng `events`.
  - `poll_events(...)`: phân trang theo cursor `after`, giữ nguyên cursor trên trang rỗng theo đúng hợp đồng `D10`.
  - `link_fr_chain(...)` và `trace_requirement(...)`: ghi và duyệt chuỗi `FR → task → patch → test_report` trong đúng `run_id`, chặn tuyệt đối nối nhầm ID của run khác và báo các mắt xích còn thiếu (`missing_task`, `missing_patch`, `missing_test_report`).
  - `audit_requirements_coverage(...)` và `artifact_version_history(...)`: kiểm tra độ phủ truy vết toàn bộ danh sách FR và truy vấn lịch sử phiên bản artifact.

## Cách chạy kiểm tra

```sh
uv run --frozen python -m unittest tests.test_trace tests.test_gateway -v
```
