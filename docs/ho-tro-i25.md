# I25 (Phần hỗ trợ trước) · Đóng gói Export ZIP đã lọc Secret

> **Trạng thái:** Đây là **phần hỗ trợ trước (draft/support)** cho [Issue #48 (`I25`)](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/48), **chưa phải bản nghiệm thu cuối**. Issue `#48` vẫn giữ `OPEN` và cần gắn endpoint `GET /runs/{run_id}/export` ở `I22` cùng dữ liệu chạy thật từ `I15`/`I21` trước khi nghiệm thu.

## Thành phần đã dựng (trên nền `I02`, `I03`, `I12`)

- `backend/exporter.py`:
  - `build_export_zip(...)`: chỉ trích các tệp được Git track dưới `app/` tại đúng `code_commit` (không đọc `.env`, cache, `.git` hay symlink), đọc artifact qua `ArtifactStore.read` có đối chiếu SHA-256, kèm `reports/test_reports.json`, `README.md` và `EXPORT_MANIFEST.json` chứa bảng SHA-256 mọi tệp.
  - Bộ lọc secret nhiều tầng (`scan_for_secrets`, `is_forbidden_path`, `assert_safe_zip_member`): chặn canary key của host, các mẫu credential phổ biến (`sk-`, `AIza`, `ghp_`, `AKIA`, `PRIVATE KEY`), chặn `.env`/tệp riêng tư và chống Zip-Slip / path traversal.
  - `verify_export_zip(...)`: kiểm tra ngược toàn bộ tệp trong ZIP khớp `EXPORT_MANIFEST.json` và sạch canary.

## Cách chạy kiểm tra

```sh
uv run --frozen python -m unittest tests.test_exporter -v
```
