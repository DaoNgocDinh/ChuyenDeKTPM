---
name: task-planning
description: Phân rã thiết kế thành đồ thị task DAG không chu trình, phủ 100% mã FR, kèm tệp dự kiến, điều kiện xong và kiểm thử cần chạy.
metadata:
  version: "0.2.0-draft"
  status: "support_proposal_pending_owner_review"
---

# Quy trình chuẩn cho Planning Agent

1. Đọc đúng cặp `requirements` (đã duyệt) và `architecture` (đúng phiên bản nguồn) từ Host.
2. Xuất đúng schema `Plan` (`D07`, cấm trường thừa):
   - `requirements` và `architecture`: `ArtifactRef` khớp chính xác bản nguồn trong cùng `run_id`.
   - `tasks`: mỗi `Task` gồm `task_id` duy nhất, `requirement_ids` (tối thiểu 1), `dependencies`, `files` dự kiến trong `app/`, `done_conditions` kiểm chứng được và danh sách `tests` cần chạy.
3. Ràng buộc toàn vẹn bắt buộc trước khi bàn giao vào Cổng duyệt 2:
   - Đồ thị `dependencies` tuyệt đối **không có chu trình**, không tự phụ thuộc, không trỏ tới `task_id` không tồn tại.
   - Hợp tất cả `requirement_ids` trên các task phải **bao phủ 100% mã FR** trong `requirements.functional` và không chứa mã không tồn tại.
   - Chia task đủ nhỏ, rõ thứ tự (ví dụ: DB schema → API CRUD/validation → React UI → tích hợp).
4. Điều cấm tuyệt đối: không viết mã ứng dụng, không sửa yêu cầu/kiến trúc nguồn, không tự đóng task thay `Dev`/`Tester`.
