# D10 · API và bốn màn hình

Bản để chủ dự án duyệt cùng D09. [Hợp đồng OpenAPI 3.1](openapi.json) gồm các schema, ví dụ JSON và mã trả về. Các path là API của nền tảng trên loopback. API đối chiếu người dùng cục bộ, dự án sở hữu run và ID con thuộc run trên mỗi thao tác. Đọc artifact cần cả `artifact_id` và `run_id`. Nếu cặp ID không khớp, trả `404 not_found`.

| Màn hình | Dữ liệu hiển thị và thao tác | Endpoint |
| --- | --- | --- |
| Dự án | Danh sách dự án, brief, ràng buộc và lịch sử run. Khi chủ dự án khởi chạy, giao diện giữ cùng `idempotency_key` cho lần gửi lại do mất kết nối. | GET/POST `/projects`, GET/POST `/projects/{project_id}/runs` |
| Chi tiết run | Hiển thị stage, bước, task, hạn mức đã dùng, lý do dừng và các hành động hợp lệ từ `next_actions`. Poll theo `after`, gộp event mới theo `sequence`, giữ cursor trên trang rỗng. Đóng/mở lại màn hình vẫn đọc lại được run. Hiển thị câu hỏi đang chờ từ nội dung artifact và gửi trả lời kèm đúng phiên bản. | GET `/runs/{run_id}`, GET `/events` và `/tasks` dưới run, POST `/clarifications`, `/cancel`, `/resume` dưới run |
| Duyệt | Đọc nội dung và phiên bản của requirements hoặc cả architecture/plan. So nội dung hiện hành với `previous_artifact_id`. Khi người dùng xác nhận, gửi ID, version, SHA256 đúng những bản đang hiển thị. Ghi một quyết định nguyên tử cho cả gate 2. | GET `/runs/{run_id}/artifacts`, GET `/artifacts/{artifact_id}?run_id=…`, POST `/runs/{run_id}/approvals` |
| Mã và kiểm thử | Mở diff, bug, log runner và liên kết FR → task → patch → test của commit. Hiển thị riêng số ca đạt, lỗi và bỏ qua. Tải ZIP và ghi nhận quyết định nghiệm thu cuối gắn manifest. | GET `/tasks`, `/test-reports`, `/artifacts`, `/export` dưới run, GET nội dung từng artifact, POST `/runs/{run_id}/acceptance` |

### Ví dụ thao tác

1. Gửi `POST /projects/p1/runs` với `{"idempotency_key":"a1-lan-1"}`. Một job mới trả `202 {"project_id":"p1","run_id":"r1","status":"queued"}`. Gửi lại cùng payload sẽ trả cùng `run_id`. Cùng khóa nhưng đổi cấu hình trả `409 idempotency_conflict`.
2. Khi cổng 1 yêu cầu chỉnh sửa, đọc nội dung requirements, sau đó gửi ví dụ `request_changes` trong OpenAPI. Phiên bản hoặc hash đã cũ trả `409 {"code":"approval_version_conflict","message":"Tải lại phiên bản mới trước khi duyệt."}`. Tải lại để người dùng xem thay đổi và tự quyết định.
3. Với cổng 2, backend đối chiếu đúng một architecture và một plan có tham chiếu tới architecture đó, cùng run, đúng phiên bản hiện hành. Hai bản trùng loại hoặc quyết định cho trạng thái đã chuyển đều bị từ chối. Chỉ mở Dev sau khi ghi thành công cả quyết định.
4. Khi chỉ định resume cho một run đã hoàn thành, trả `409 invalid_transition`. Tool bị chặn và hết ngân sách trong worker được hiển thị dưới dạng `tool_denied` và `budget_exceeded` trong `last_error` và timeline. Hai mã này thuộc kết quả bất đồng bộ của job.

### Kiểm tra

Chạy `python -m unittest tests.test_api_contract` để kiểm các tham chiếu schema, ràng buộc đường dẫn, idempotency, cổng duyệt và phạm vi đọc artifact. Dùng fixture trên khi I22–I24 có API/UI để đối chiếu hành vi chạy thật.
