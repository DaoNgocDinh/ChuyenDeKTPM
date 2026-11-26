---
name: requirements-analysis
description: Phân tích brief thành SRS có cấu trúc khớp schema Requirements (D07), đặt câu hỏi làm rõ chặn rủi ro và bảo toàn phạm vi MVP.
metadata:
  version: "1.1.0"
  status: "active"
---

# Quy trình chuẩn cho Requirement Agent

1. Đọc kỹ brief gốc, danh sách ràng buộc và câu trả lời làm rõ (nếu có) cùng phiên bản `requirements` trước đó khi được yêu cầu chỉnh sửa.
2. Trả về đúng schema `Requirements` (`D07`, cấm trường thừa):
   - `actors`: tối thiểu 1 tác nhân.
   - `functional`: danh sách `RequirementItem(id, description, acceptance)` với `id` duy nhất và mỗi FR có tối thiểu 1 tiêu chí chấp nhận kiểm chứng được.
   - `nonfunctional`: yêu cầu phi chức năng tương ứng phạm vi ứng dụng.
   - `assumptions`: giả định tường minh, không ẩn giả định trong mô tả.
   - `questions`: chỉ đặt câu hỏi thật sự ảnh hưởng tới hành vi dữ liệu/luật nghiệp vụ.
3. Kèm bản Markdown ngắn gọn để chủ dự án đọc duyệt tại Cổng 1.
4. Điều cấm tuyệt đối:
   - Không tự bịa thêm tính năng ngoài brief (đăng nhập, phân quyền phức tạp, thanh toán, dịch vụ ngoài).
   - Không ghi đè phiên bản đã duyệt; mọi chỉnh sửa phát hành phiên bản tăng dần qua Artifact Store.
   - Không gọi Git, không chạm workspace mã và không đọc artifact của run khác.
