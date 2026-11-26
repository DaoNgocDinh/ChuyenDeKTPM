# I23 · Giao diện React: Dự án và Theo dõi Run bằng Polling

Triển khai Màn hình 1 (Dự án & Lịch sử run) và Màn hình 2 (Chi tiết run & Timeline 6 vai trò bằng polling theo cursor) bám đúng hợp đồng OpenAPI 3.1 tại `D10` (`docs/openapi.json`) và giữ nguyên lockfile `frontend/package-lock.json` của `I01` (không thêm gói npm mới).

## Thành phần đã xây

- `frontend/src/api/types.ts` và `frontend/src/api/client.ts`: kiểu dữ liệu và HTTP client bám trọn 14 endpoint + bộ mã lỗi `D10` (`not_found`, `approval_version_conflict`, `invalid_transition`, `tool_denied`, `budget_exceeded`, `invalid_request`, `idempotency_conflict`).
- `frontend/src/api/polling.ts`: `mergeEventsPage` (gộp theo `sequence` tăng dần, chống trùng, giữ nguyên cursor trên trang rỗng), `IdempotencyTracker` (giữ nguyên `idempotency_key` khi thử gửi lại do lỗi mạng) và `extractPendingQuestions`.
- `frontend/src/components/ProjectsView.tsx`: tạo dự án, xem brief/ràng buộc/lịch sử run và xếp hàng run `202` với `idempotency_key`.
- `frontend/src/components/RunDetailView.tsx`: theo dõi `status`, `stage`, `quota` (hiển thị rõ `usage_complete`), `last_error`, 6 vai trò, `tasks`, nút `cancel`/`resume` theo `next_actions`, trả lời câu hỏi làm rõ gắn đúng `ArtifactRef`, polling theo `after` và khôi phục đúng run từ URL hash khi mở lại trang.
- `frontend/vite.config.js`: proxy dev cho `/health`, `/projects`, `/runs`, `/artifacts` sang FastAPI loopback `127.0.0.1:${PLATFORM_PORT}` để nối thẳng khi `I22` hoàn thành.

## Kiểm tra nhánh `I23`

```sh
npm --prefix frontend ci
npm --prefix frontend run build
node --test frontend/tests/i23.test.ts
```

**Lưu ý phụ thuộc:** Theo nguyên tắc `P01`, Issue `#46 (I23)` chỉ nghiệm thu và đóng sau khi backend `I22` chạy thật và nối kiểm thử trực tiếp với FastAPI.
