# I24 · Giao diện React: Duyệt Artifact, Xem Diff, Test Report và Truy vết

Xây dựng tiếp trên nền `I23` để hoàn thiện đủ 4 màn hình MVP theo hợp đồng OpenAPI `D10` (`docs/openapi.json`), giữ nguyên hoàn toàn `frontend/package-lock.json` của `I01` (không thêm gói npm mới).

## Thành phần bổ sung ở `I24`

- `frontend/src/api/review.ts`: kiểm tra nguyên tử Cổng 1 (`1` artifact `requirements`) & Cổng 2 (`2` artifact `architecture` + `plan`), bắt buộc `comment` khi `request_changes`, hàm diff theo dòng (`computeLineDiff`), ghép chuỗi truy vết `FR → task → patch → test` (`buildTraceRows`) và kiểm tra payload nghiệm thu cuối (`buildAcceptancePayload`).
- `frontend/src/components/ApprovalView.tsx` (**Màn hình 3 — Duyệt artifact**): đọc danh sách artifact và nội dung qua `GET /artifacts/{artifact_id}?run_id=...`, so sánh với `previous_artifact_id`, gửi `POST /runs/{run_id}/approvals` gắn đúng `(artifact_id, version, sha256)`, xử lý riêng `409 approval_version_conflict` kèm nút tải lại phiên bản mới.
- `frontend/src/components/CodeTestTraceView.tsx` (**Màn hình 4 — Mã, Kiểm thử & Truy vết**): hiển thị bảng `test_reports` tách riêng số `passed`, `failed`, `errors`, `skipped` cùng `exit_code` và `commit`; bảng chuỗi `FR → task → patch → test`; trình xem diff/log/bug/trace; nút tải `GET /runs/{run_id}/export` (ZIP) và biểu mẫu `POST /runs/{run_id}/acceptance` gắn manifest.
- `frontend/src/App.tsx`: hoàn thiện thanh điều hướng đủ 4 màn hình MVP và nối trực tiếp hành động `review`, `inspect`, `accept_output` từ Màn hình 2.

## Kiểm tra nhánh `I24`

```sh
npm --prefix frontend ci
npm --prefix frontend run build
node --test frontend/tests/i23.test.ts frontend/tests/i24.test.ts
```

**Lưu ý phụ thuộc:** Theo nguyên tắc `P01`, Issue `#47 (I24)` chỉ nghiệm thu và đóng sau khi backend `I22` và truy vết `I21` chạy thật và kiểm thử đầu cuối qua FastAPI.
