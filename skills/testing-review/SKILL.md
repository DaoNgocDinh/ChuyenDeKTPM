---
name: testing-review
description: Rà soát diff tại đúng commit, viết test phát triển trong tests_dev/, chạy runner thật và xuất TestReport/BugReport có bằng chứng xác thực.
metadata:
  version: "1.1.0"
  status: "active"
---

# Quy trình chuẩn cho Tester Agent

1. Đọc FR, tiêu chí chấp nhận, đặc tả task, diff tại đúng `commit` của `Dev` (`git.diff`, `workspace.read_file`).
2. Viết hoặc cập nhật test phát triển chỉ trong `tests_dev/` (bao phủ cả trường hợp hợp lệ, validation biên và hồi quy cho các task trước đó).
3. Chạy kiểm thử thật qua `tests.run_suite` (`build`, `smoke`, `development`) trên đúng commit chứa mã đã giao và test. Nếu Tester vừa thêm test, dùng commit checkpoint mới, dẫn lại commit đầu vào của Dev và xác nhận diff chỉ đổi `tests_dev/`.
4. Xuất kết quả theo đúng schema `D07`:
   - `TestReport`: ghi đúng `task_id` và `commit`, `suite_id`, `runner_output` (`ArtifactRef`), `exit_code`, `passed`, `failures`, `errors`, `skipped`. Chỉ coi là đạt khi `exit_code == 0`, `passed > 0` và `failures == errors == skipped == 0`.
   - Khi thất bại, xuất `BugReport(task_id, commit, report, requirement_ids, reproduce, expected, actual, category)` với bước tái hiện cụ thể và phân loại chính xác `category` (`code`, `requirements`, `design`, hoặc `infrastructure`).
5. Điều cấm tuyệt đối:
   - Không sửa bất kỳ tệp nào trong `app/`.
   - Không truy cập hay sao chép bộ kiểm thử độc lập `evaluation/`.
   - Không bao giờ báo đạt khi chưa chạy runner thật hoặc khi suite rỗng/bị skip/lỗi hạ tầng.
