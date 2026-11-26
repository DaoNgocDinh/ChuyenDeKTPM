# D07 · Envelope và artifact

Bản đề xuất phiên bản 1 nằm trong `backend/contracts.py`. Host tạo Envelope từ danh tính của bước trong DB và kiểm tra run của từng tham chiếu. Model chỉ được trả payload theo vai trò. Host đối chiếu version, SHA-256 và commit với bản lưu trước khi chuyển bước hoặc ghi tác dụng phụ. Cổng duyệt luôn kiểm tra artifact đang có trên host.

`check_handoff` nối ba đầu ra Requirements → Architecture → Plan theo bản nguồn chính xác, kiểm tra độ phủ FR và các component được tham chiếu. Mỗi task ghi điều kiện xong và test. TestReport ghi số lượng và exit code độc lập. Ví dụ hợp lệ và các trường hợp lỗi có thể chạy trực tiếp ở `tests/test_contracts.py`.

Khi payload sai schema hoặc tham chiếu, host ghi lỗi và trả thông báo cho vai trò nguồn. Số lần thử lại chịu giới hạn cấu hình toàn run. Chủ dự án duyệt giới hạn ở D08/E04.

**Test** · `uv run --no-project --with "pydantic>=2,<3" python -m unittest tests.test_contracts -v` chạy bốn nhóm ca gồm stale version, thiếu FR, chu trình, khác run và test rỗng/skipped.
