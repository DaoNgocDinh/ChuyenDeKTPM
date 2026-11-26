# I13 · Gateway

Host cấp `HostStep(project_id, run_id, step_id, lease)`. Gateway tra lại step đang hoạt động và role trong SQLite trước khi cho dispatch. Danh tính và quyền chỉ đến từ host. Mỗi lần gọi được ghi operation riêng trước tác dụng phụ. Nếu kết quả chưa ghi xong khi mất lease, I20 phải đối chiếu trước khi tiếp tục.

Chỉ các tham số trong schema từng tool được tiếp nhận. Dev ghi app, Tester ghi tests_dev, việc đọc artifact yêu cầu đúng run, ID, version và hash. Audit giữ kiểu, số phần tử, kết quả, thời gian và operation ID. Giá trị tự do, payload mã, token và nội dung exception không vào event.

**Test** · `python -m unittest tests.test_gateway -v` dùng SQLite thật để kiểm quyền, đường dẫn, giả role, khác run, audit của kết quả/lỗi và chống dispatch lại cùng operation.
