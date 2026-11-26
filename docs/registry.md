# I08 · Registry sáu skill

Chủ dự án duyệt áp dụng sáu hướng dẫn của nhánh hỗ trợ `I08-draft-skills` cho run mới sau khi đối chiếu hợp đồng D05–D11. Phiên bản `1.1.0` làm rõ việc tạo tệp mới, nguồn metadata của host và commit thực tế khi Tester thêm test. Run đã đóng băng tiếp tục dùng commit và manifest cũ.

Host khởi tạo `RunSkills(skills_root, enabled=...)`, sau đó gọi `bind(run_dir / "skills.json")` trước lần gọi model đầu tiên và mỗi khi resume. Manifest ghi tên, version, commit, SHA-256 và cờ nạp theo từng vai trò. `context(role)` trả đúng hướng dẫn đang giữ trong bộ nhớ. Run no-skill dùng cùng role/tool policy và nhận chuỗi hướng dẫn rỗng.

**Test** · `uv run --no-project --with PyYAML python -m unittest tests.test_registry tests.test_skill -v`. Bốn test kiểm sáu ánh xạ, manifest bất biến, khôi phục với cấu hình khác, sửa tệp giữa run và chế độ no-skill.
