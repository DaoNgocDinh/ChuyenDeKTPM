# I17 · Tester Agent

Tester chạy ngay trong `backend/coding_agents.py` (`CodingAgents`, giữ đúng mô hình 6 vai trò và không tạo vai trò Reviewer thứ 7). Host kiểm tra quyết định duyệt hiện hành của Gate 1 (`requirements`) và Gate 2 (`architecture_plan`), kiểm trạng thái task `waiting_test`, đối chiếu `DevResult` với commit hiện tại của workspace, rồi mở phiên MCP `stdio` theo đúng bước chạy.

Quy trình hai pha của Tester:
1. Đọc `requirements`, `architecture`, `plan`, `dev_result`, `patch`, `git.diff` và mã nguồn liên quan cùng các tệp `tests_dev/` hiện có qua MCP; tiêm skill `testing-review` đang `active`.
2. Sinh hoặc cập nhật test phát triển **chỉ trong `tests_dev/`** (mọi nỗ lực sửa `app/` hoặc `evaluation/` bị `Gateway` chặn với `tool_denied` và ghi vết kiểm toán), sau đó chạy suite thật qua `tests.run_suite`.
3. Xuất `TestReport` gắn đúng `commit`, `report_id` và `runner_output`; nếu thất bại thì chẩn đoán từ `report` và `log_tail` đã lọc (từ I14) để xuất `BugReport` với bước tái hiện và phân loại `code` / `requirements` / `design` / `infrastructure` (ép `infrastructure` nếu runner báo lỗi hạ tầng/timeout). Báo cáo review có cấu trúc (`ReviewReport`) được lưu dưới dạng JSON bằng loại artifact `"document"` sẵn có của I03 để không sửa hợp đồng dùng chung `contracts.py` và `artifacts.py`.

**Test** · `uv run --frozen python -m unittest tests.test_tester_agent -v`. Đặt `KTPM_TEST_RUNNER_IMAGE` theo I15 để chạy thêm ca kiểm thử Docker thật; đặt thêm `KTPM_LIVE_MODEL=1` để gọi Neon High thật.
