---
name: task-planning
description: Lập DAG triển khai từ yêu cầu đã duyệt và thiết kế cùng run.
metadata:
  version: "1.0"
---

1. Đối chiếu danh mục FR, ràng buộc và phiên bản thiết kế. Chia công việc thành task có thể kiểm chứng bằng hành vi.
2. Mỗi task liệt kê FR, phụ thuộc, vùng tệp, điều kiện xong và test. Kiểm tra ID duy nhất, đủ FR, không có dependency lạ và không có chu trình.
3. Bàn giao cả thiết kế và plan để chủ dự án duyệt. Khi nguồn thay đổi, trả bản mới có tham chiếu nguồn thay thế.
