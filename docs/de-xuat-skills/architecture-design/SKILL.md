---
name: architecture-design
description: Thiết kế ADR, thành phần, lược đồ SQLite, hợp đồng API và bố cục React bám chặt stack cố định và phủ 100% FR đã duyệt.
metadata:
  version: "0.2.0-draft"
  status: "support_proposal_pending_owner_review"
---

# Quy trình chuẩn cho Architecture Agent

1. Chỉ làm việc trên đúng phiên bản `requirements` đã duyệt do Host cấp (`ArtifactRef` khớp `run_id`, `version`, `sha256`).
2. Giữ cố định stack ứng dụng đầu ra theo `P01`: **FastAPI + React + SQLite** (dữ liệu nghiệp vụ nằm riêng trong workspace `app/`, tuyệt đối tách khỏi DB vận hành của nền tảng).
3. Xuất đầy đủ schema `Architecture` (`D07`, cấm trường thừa):
   - `requirements`: `ArtifactRef` trỏ đúng bản yêu cầu nguồn.
   - `adr`: tối thiểu 1 quyết định kiến trúc có lý do rõ ràng.
   - `components`, `entities`, `api_contract`: mô tả nhất quán tên bảng, quan hệ, ràng buộc validation và endpoint HTTP.
   - `frontend`: cấu trúc màn hình/biểu mẫu đáp ứng luồng UI tối thiểu.
   - `test_strategy`: kế hoạch kiểm thử cho `tests_dev/` (`smoke` + `development`).
   - `fr_components`: ánh xạ **mọi mã FR** trong `requirements.functional` tới tối thiểu 1 khóa tồn tại trong `components`.
4. Nếu phát hiện yêu cầu mâu thuẫn hoặc bất khả thi trong stack cố định, trả blocker tường minh về `Requirement`; không âm thầm bỏ sót FR.
5. Điều cấm tuyệt đối: không tự đổi framework, không mở cổng duyệt, không sửa mã và không chạy suite.
