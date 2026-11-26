# I16 · Dev Agent

Host kiểm tra task đang thực hiện và quyết định duyệt đúng phiên bản của requirements, architecture và plan. Dev đọc các đầu vào và tệp liên quan qua MCP rồi gửi nội dung đã quan sát cho model. Host kiểm hash, áp patch qua MCP, lưu diff và commit, sau đó chạy suite Docker. Tester có thể đọc report của lần tự kiểm tra này.

**Test** · `uv run --frozen python -m unittest tests.test_dev_agent -v`. Đặt `KTPM_TEST_RUNNER_IMAGE` theo I15 để chạy cả test Docker. Đặt thêm `KTPM_LIVE_MODEL=1` để gọi Neon High thật cho task mẫu. Các quyết định duyệt trong fixture chỉ phục vụ kiểm thử dịch vụ.

Lượt kiểm tra I16 ngày 27/11/2026 chạy hai ca trong 59,295 giây. Neon High sinh hàm `greeting()` trong workspace tạm. Docker chạy smoke trên commit của workspace `e49980cea3d7d10dfa255cd278599d7c37823ae6` và ghi 1 pass, 0 fail. CLI trả 24.587 input token và 1.681 output token. Lượt này thuộc kiểm thử thành phần I16.
