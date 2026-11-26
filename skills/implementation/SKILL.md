---
name: implementation
description: Triển khai mã ứng dụng CRUD trong vùng app/ theo đúng task và commit đầu vào qua MCP, chạy tự kiểm tra hợp lệ và bàn giao DevResult.
metadata:
  version: "1.1.0"
  status: "active"
---

# Quy trình chuẩn cho Dev Agent

1. Nhận đúng một task ở trạng thái `ready` hoặc `rework`, kèm `input_commit`, cặp `(requirements, architecture)` đã duyệt và `BugReport` (nếu đang ở vòng sửa lỗi).
2. Kiểm tra `workspace.list_files` và `git.status`. Đọc tệp đã tồn tại qua `workspace.read_file` để lấy hash. Khi tạo tệp mới, truyền `expected_hash=null`.
3. Mọi thay đổi mã gửi qua `workspace.apply_patch` phải:
   - Chỉ tác động tệp dưới `app/` bằng đường dẫn tương đối hợp lệ.
   - Khớp chính xác `input_commit` và `expected_hash` của từng tệp (tránh ghi đè stale).
   - Bảo toàn dữ liệu bền trong SQLite của ứng dụng và đáp ứng đúng validation/UI của task.
4. Có thể chạy các suite được cấp (`build`, `smoke`, `development`) qua `tests.run_suite` để tự kiểm tra trước khi bàn giao `DevResult(task_id, input_commit, output_commit, patch_sha256, changed_files, summary)`.
5. Điều cấm tuyệt đối:
   - Không ghi vào `tests_dev/`, `evaluation/`, `skills/`, tệp policy hay mã nền tảng.
   - Không chèn API key, `.env` hay lệnh shell tùy ý; không tự đánh dấu task đạt nghiệm thu cuối.
   - Không âm thầm đổi hợp đồng API/yêu cầu khi sửa bug; nếu thiếu dữ kiện trong `BugReport`, yêu cầu làm rõ có cấu trúc.
