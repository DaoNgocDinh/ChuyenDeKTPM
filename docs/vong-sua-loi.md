# I18 · Vòng sửa lỗi Tester → Dev và định tuyến lỗi

Host điều phối khép kín vòng lặp `Dev → Tester → BugReport → Dev (rework) → Tester (retest + hồi quy)` dựa trên trạng thái bền vững (`D08`) và bằng chứng thật từ Git/runner:

- **Lỗi mã (`category == "code"`):** Host lưu `BugReport` gắn `parent_refs` tới `TestReport`, chuyển task từ `waiting_test` sang `rework` và đưa `bug_report` cùng tham chiếu artifact vào lượt `Dev` tiếp theo (lưu trọn chuỗi `dev_result`, `patch`, `test_report`, `document`/`ReviewReport`, `bug_report` qua từng vòng). `Dev` đọc thêm các tệp `tests_dev/` hiện có khi rework để sửa đúng gốc lỗi và giữ nguyên hồi quy.
- **Giới hạn 3 vòng sửa lỗi mã:** Sau lần giao đầu tiên và tối đa 3 vòng sửa (`repair_round` từ `0` đến `3`), nếu lần kiểm thử sau vòng 3 vẫn lỗi mã thì task chuyển sang `blocked` và run dừng ở `needs_human_review` (`repairs_exhausted`), tuyệt đối không chạy vòng 4.
- **Định tuyến lỗi yêu cầu/thiết kế:**
  - `category == "requirements"` → ghi sự kiện `fault.routed`, đặt `revision_route = "Requirement"` cùng `routing_bug`, chạy lại `Requirement` tạo phiên bản mới, xóa cờ định tuyến và mở lại Gate 1 (`waiting_approval`).
  - `category == "design"` → ghi sự kiện `fault.routed`, đặt `revision_route = "Architecture"` cùng `routing_bug`, chạy lại `Architecture` và `Planning`, xóa cờ định tuyến và mở lại Gate 2 (`waiting_approval`). Không chạy lại `Dev` trước khi chủ dự án duyệt.
- **Thử lại hữu hạn cho lỗi hạ tầng (`category == "infrastructure"`):** Tách biệt hoàn toàn khỏi hạn mức 3 vòng sửa mã (`repair_round` giữ nguyên). Host thử lại trực tiếp `Tester` tối đa `max_infra_retries` lần (mặc định `2`, cấu hình trong `run.config_json`) kèm sự kiện `infra.retry`; khi hết hạn mức thì ghi `infra.exhausted` và dừng run ở `needs_human_review`.

**Test** · `uv run --frozen python -m unittest tests.test_repair_loop tests.test_tester_agent tests.test_dev_agent tests.test_orchestrator -v`. Đặt `KTPM_TEST_RUNNER_IMAGE` (và tùy chọn `KTPM_LIVE_MODEL=1`) để chạy thêm ca vòng `fail → fix → retest` với Docker thật.
