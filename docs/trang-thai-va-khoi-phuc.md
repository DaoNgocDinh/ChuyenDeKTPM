# D08 · Bảng chuyển trạng thái và khôi phục

Bản thiết kế để chủ dự án duyệt. Bảng tra đầy đủ ở `RUN_EVENTS` và `TASK_EVENTS` trong `backend/lifecycle.py`. Chỉ host có quyền áp sự kiện sau khi kiểm guard. Stage requirements, architecture, planning, development, testing được lưu độc lập với trạng thái run.

| Trường hợp | Guard & tác động bền |
| --- | --- |
| Claim | Chọn một job queued trong transaction, đặt lease riêng và chuyển running. Mỗi lần heartbeat/ghi kết quả phải khớp lease hiện tại. |
| Approval | Đặt waiting_approval với run và tập artifact hiện thời. Duyệt đúng version/hash hoặc yêu cầu sửa thì xếp lại job vào queue. Với yêu cầu sửa, tạo phiên bản mới và vô hiệu duyệt phụ thuộc. |
| Patch/test | Ghi operation_id, run/task, input commit và expected hash trước tác dụng phụ. Sau tác dụng phụ lưu receipt/hash/commit cùng output. Chỉ đánh dấu task done khi suite thật gắn đúng commit qua. |
| Repair | Lần triển khai đầu có repair_count=0. Tăng bộ đếm khi bắt đầu mỗi lần sửa. Test đỏ sau ba lần sửa thì task blocked, run needs_human_review. |
| Quota | Kiểm thời gian, tool calls và quota token theo cấu hình của cả run trước khi cấp lần gọi tiếp. Cấu hình chủ dự án hiện dùng một Neon High và không đặt trần token phía ứng dụng. Ghi usage thực tế trong mọi trường hợp. Hạn mức thời gian và tool sẽ khóa sau pilot. |
| Cancel | Ngừng cấp bước mới, thu hồi lease và chờ runner dừng cây tiến trình. Lưu event, kết quả dừng hoặc tác dụng còn chưa xác định. Run cancelled không tự khởi động lại. |
| Restart | Lease hết hạn đưa run về pending_recovery. Đối chiếu operation, input commit, patch hash, HEAD và receipt. Đã chứng minh commit mới đúng thì tiến bước mà không áp lại. Thiếu/sai bằng chứng thì giữ pending_recovery, trình log cho chủ dự án. |

**Test** · `python -m unittest tests.test_lifecycle -v` kiểm duyệt/sửa, quota, cấm hoàn tất khi đang chờ duyệt, giới hạn ba lượt sửa, và receipt sai hoặc thiếu sau restart.
