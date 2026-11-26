# R08 · Nạp skill phân tích yêu cầu

Host chọn `skills/requirements-analysis` khi bắt đầu bước Requirement. `load_skill` đọc metadata, giữ nội dung và tài nguyên của phiên bản đó trong bộ nhớ. Chỉ mô tả ngắn cần xuất hiện khi khám phá skill. Khi thực hiện bước, host lấy `context(enabled=True)`. Tài nguyên bổ sung phải được yêu cầu theo tên trong gói.

Run dùng `skill_manifest` để ghi tên, version, Git commit, SHA-256 của danh sách đường dẫn và hash nội dung, cùng cờ bật/tắt. Với cấu hình no-skill, `context(enabled=False)` trả chuỗi rỗng, kể cả khi yêu cầu tài nguyên. Danh tính agent, model, schema đầu ra và quyền gọi MCP thuộc host. Quyết định khóa cấu hình thí nghiệm thuộc E04.

**Test** · Với Python ≥3.11 và Git, chạy `uv run --no-project --with PyYAML python -m unittest tests.test_skill -v`. Ba test kiểm tra cấp nội dung theo yêu cầu, thay đổi tài nguyên, truy vết đến commit và từ chối version rỗng.

[Đặc tả Agent Skills](https://agentskills.io/specification) · [Issue R08](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/10)
