# I12 · Workspace và checkpoint Git

Host tạo `Workspace(root, project_id, run_id)` rồi gọi `initialize()`. Mỗi run có Git riêng, vùng mã `app/`, test phát triển `tests_dev/`, artifact và log. `apply` nhận task, commit đầu vào và các thay đổi theo tệp. Giá trị `expected_hash=None` yêu cầu tệp chưa tồn tại; `text=None` xóa tệp khi hash khớp.

Receipt liên kết task, patch ID, hash của thay đổi, commit trước/sau và diff. Journal được ghi trước khi sửa tệp. Nếu tác dụng phụ chưa được xác nhận, lần gọi kế tiếp trả pending recovery. Host đọc Git và receipt để đối chiếu. I13 kiểm tra quyền riêng của từng vai trò trước khi dispatch.

**Test** · `python -m unittest tests.test_workspace -v` dùng ba repo Git tạm để kiểm tra hai run độc lập, diff có thể dựng lại, stale hash/commit, phạm vi đường dẫn và dừng khi mất xác nhận.
