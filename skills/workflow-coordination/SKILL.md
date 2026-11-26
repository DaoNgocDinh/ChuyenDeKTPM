---
name: workflow-coordination
description: Điều phối sáu vai trò theo state machine, kiểm soát hai cổng duyệt, vòng sửa tối đa ba lượt và hạn mức toàn run.
metadata:
  version: "1.1.0"
  status: "active"
---

# Quy trình chuẩn cho Orchestrator Agent

1. Đọc metadata, trạng thái, checkpoint và quota do Host cung cấp. Đọc nội dung artifact bằng `project.read_artifact` theo đúng run, ID, version và SHA-256.
2. Luôn tôn trọng hai cổng duyệt bắt buộc:
   - Không giao `Architecture` khi `requirements` phiên bản hiện hành chưa được chủ dự án duyệt tại Cổng 1.
   - Không giao `Dev` khi cặp `(architecture, plan)` hiện hành chưa được duyệt nguyên tử tại Cổng 2.
3. Khi nhận `BugReport` từ `Tester`, định tuyến đúng theo `category`:
   - `code`: giao `Dev` sửa nếu `repair_round < 3`; nếu đã hết 3 vòng sửa sau lần triển khai đầu, dừng task (`blocked`) và chuyển run sang `needs_human_review`.
   - `requirements`: quay về `Requirement` tạo phiên bản mới và mở lại quy trình duyệt.
   - `design`: quay về `Architecture` tạo phiên bản thiết kế mới và mở lại Cổng 2.
   - `infrastructure`: dừng và báo đầy đủ log lỗi môi trường/runner cho chủ dự án.
4. Điều cấm tuyệt đối:
   - Không tự duyệt thay chủ dự án.
   - Không tự sửa mã nguồn hoặc đề xuất thao tác vượt qua transition guard của state machine Python.
   - Không bỏ qua lỗi quota (`budget_exceeded`) hoặc lỗi phục hồi (`pending_recovery`).
