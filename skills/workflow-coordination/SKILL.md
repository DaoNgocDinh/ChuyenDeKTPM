---
name: workflow-coordination
description: Điều phối các vai trò trong run khi có job, kết quả của một bước hoặc quyết định duyệt.
metadata:
  version: "1.0"
---

1. Đọc stage, checkpoint, quota còn lại và các artifact đúng run. Đối chiếu sự kiện mới nhất với trạng thái do host cung cấp.
2. Đề xuất đúng một bước, kèm vai trò nhận việc, task và các phiên bản đầu vào. Nếu thiếu bằng chứng, nêu rõ dữ liệu còn thiếu.
3. Tại cổng requirements hoặc architecture + plan, gửi yêu cầu duyệt. Sau report đỏ, định tuyến lỗi cho vai trò chịu trách nhiệm; hết lượt sửa thì dừng để người dùng xem.
