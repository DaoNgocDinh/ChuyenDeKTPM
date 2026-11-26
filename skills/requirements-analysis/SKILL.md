---
name: requirements-analysis
description: Chuyển brief và câu trả lời làm rõ thành bộ yêu cầu cho một ứng dụng CRUD trước cổng duyệt yêu cầu.
metadata:
  version: "1.0"
---

Đọc brief, ràng buộc và câu trả lời thuộc đúng run. Khi sửa yêu cầu, lấy cả bản đã duyệt gần nhất làm đầu vào.

1. Trích tác nhân, mục tiêu và thao tác người dùng đã nêu. Gán ID ổn định cho mỗi yêu cầu và giữ ID khi sửa cùng yêu cầu.
2. Viết tiêu chí quan sát được cho từng chức năng. Dùng ví dụ nhập liệu sai khi brief có ràng buộc dữ liệu.
3. Nếu có hai cách hiểu dẫn đến hành vi khác nhau, gửi câu hỏi có ví dụ và dừng chờ câu trả lời. Ghi riêng các giả định đang chờ xác nhận.
4. Khi đã đủ đầu vào, trả bản yêu cầu có cấu trúc và bản Markdown tương ứng. Bàn giao cả hai cùng phiên bản cho Orchestrator mở cổng duyệt.
