---
name: testing-review
description: Đánh giá thay đổi tại commit được giao, viết test phát triển và phản hồi lỗi.
metadata:
  version: "1.0"
---

1. Đối chiếu task, FR, diff và commit mới. Thiết kế ca thường và ca biên theo tiêu chí đã duyệt; chỉ đề xuất ghi trong tests_dev.
2. Gọi suite được cấp, thu exit code, số lượng pass/fail/error/skip và bằng chứng runner. Với ca đỏ, ghi đầu vào, bước tái hiện, expected/actual cùng commit.
3. Phân loại lỗi và chuyển về đúng vai trò. Chạy lại ca đỏ và regression tại commit sửa; nếu thiếu bằng chứng runner thì báo chưa kiểm tra được.
