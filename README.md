# Chuyên đề Kỹ thuật phần mềm

Nền tảng điều phối sáu vai trò để phát triển và kiểm thử ứng dụng CRUD. Đề cương P01 đã duyệt ở [docs/ke-hoach.md](docs/ke-hoach.md). Xem [các issue và phụ thuộc](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/1) để theo dõi tiến độ.

| Thư mục | Nội dung |
| --- | --- |
| `backend/` | API FastAPI, worker, agent, lưu trữ và MCP server chạy cục bộ. |
| `frontend/` | Giao diện React quản lý dự án, theo dõi run, duyệt phiên bản và xem kết quả. |
| `tests/` | Kiểm thử nền tảng theo thành phần và luồng tích hợp. |
| `evaluation/` | Fixture và kiểm thử nghiệm thu độc lập của A1–A3. |
| `docs/` | Đề cương, đặc tả, quyết định đã duyệt và báo cáo. |

Mỗi công việc dùng một nhánh theo mã issue, ví dụ `R07`. Ghi lệnh kiểm tra cùng kết quả mong đợi trong commit hoặc tài liệu của nhánh. Các quyết định về yêu cầu, hợp đồng và nghiệm thu cần xác nhận của chủ dự án.

Khi có triển khai tương ứng, sáu skill dùng chung thư mục `skills/`, protocol và công cụ thu dữ liệu dùng `experiments/`. Mỗi run tạo dữ liệu tại `workspaces/` trên máy.

### Kiểm tra cấu trúc

Chạy `git ls-tree --name-only HEAD` và mở đường dẫn đề cương ở trên. Nội dung đề cương được giữ nguyên từ commit duyệt `8c2fe71`.
