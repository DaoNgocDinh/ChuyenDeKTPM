---
name: implementation
description: Thực hiện task đã được host giao hoặc sửa lỗi mã mà Tester tái hiện.
metadata:
  version: "1.0"
---

1. Lấy đầu vào đã duyệt, task và commit cơ sở. Đọc phần liên quan qua công cụ của run. Nếu lỗi do yêu cầu/thiết kế, trả blocker.
2. Chuẩn bị patch nhỏ trong app, nêu task, input commit và expected hash. Gửi yêu cầu qua Gateway. Chỉ coi là đã ghi khi có receipt và commit thật.
3. Chạy suite được cấp, trả diff, commit và kết quả thật cho Tester. Khi sửa lỗi, giữ liên kết đến bug/report của lần trước.
