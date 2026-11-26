# E01 · Bộ nghiệm thu độc lập cho A1, A2 và A3

Thư mục `evaluation/` giữ bộ tiêu chí, fixture và harness đánh giá độc lập cho ba bài toán đã duyệt tại `D02`, `D03`, `D04` (`A1.json`, `A2.json`, `A3.json`). Theo `P01` và `D11`, toàn bộ thư mục này nằm ngoài vùng đọc/ghi của `Dev`, `Tester` và container kiểm thử phát triển (`independent_suite_access = evaluation_host_only`).

## Kiến trúc nối không áp đặt tên endpoint

Chủ dự án chốt giữ brief nghiệp vụ độc lập, không ép tên endpoint hay tên trường JSON cho cấu hình `S` và `M`. Khi đánh giá một ứng dụng sinh ra tại một `code_commit`:

1. 30 ca kiểm tra trong `evaluation/suites.py` và fixture gốc trong `A1.json`, `A2.json`, `A3.json` được **khóa bất biến** bằng SHA-256 (`evaluation/checksums.json`).
2. Mỗi ứng dụng sinh ra được nối bằng một lớp adapter mỏng triển khai `TaskAppAdapter`, `NotesAppAdapter` hoặc `InventoryAppAdapter` (`evaluation/adapters.py`) để ánh xạ sang đường dẫn HTTP và cấu trúc phản hồi của ứng dụng đó.
3. Ba tiêu chí giao diện (`A1-10`, `A2-10`, `A3-10`) chạy qua giao diện `UIDriver` (`evaluation/ui_driver.py`), hỗ trợ `PlaywrightUIDriver` trong môi trường đánh giá riêng (không thay đổi `pyproject.toml`/`uv.lock` nền tảng của `I01`). Nếu thiếu `UIDriver`, ca UI trả trạng thái `error` và **tuyệt đối không suy ra pass từ test backend**.

## Quy tắc chấm và báo cáo đầu ra

- `build_ok == False` cưỡng chế `passed = 0`, `failed = 10` (`build fail = 0 pass`).
- Trạng thái `skipped`, `error` hoặc tiêu chí chưa chạy không bao giờ tính vào `acceptance_passed`.
- `run_case_evaluation(...)` xuất cả JSON (`<CASE>_report.json`) và JUnit XML (`<CASE>_junit.xml`) tương thích `I15`, gắn rõ `criterion_id`, `code_commit`, `build_ok` và `suite_bundle_sha256`.

## Kiểm tra nhánh `E01`

```sh
python -m evaluation.checksums
python -m unittest tests.test_e01_evaluation -v
```

Bộ kiểm tra dùng các ứng dụng mẫu HTTP + SQLite (`evaluation/fixtures/reference_apps.py`) để chứng minh:
- 30/30 tiêu chí đạt trên mẫu đúng (`10/10` cho mỗi bài `A1`, `A2`, `A3`).
- Các mẫu cố tình sai bị bắt đúng tiêu chí tương ứng.
- `build fail` trả `0 pass`, `skipped`/`error` không tính pass và thiếu UI driver làm đỏ ca UI.
- Sai lệch bất kỳ tệp nào trong danh sách khóa bị phát hiện ngay bởi `evaluation/checksums.py`.

**Đánh giá commit với Docker.** `evaluation.docker_build.run_docker_evaluation` nhận runner I15, Git repo, commit đầy đủ, thư mục kết quả và hàm `open_adapter(commit)` do host quản lý. Hàm này mở đúng ứng dụng đã triển khai ở commit cần chấm và trả adapter nghiệp vụ/UI qua context manager. Bộ chấm kiểm checksum của tiêu chí, chạy suite build thật, kiểm lại report và JUnit được lưu cho đúng commit. Nếu build lỗi, báo cáo vẫn có đủ mười tiêu chí, đạt 0/10, và không mở ứng dụng. Đối với S và M, người đánh giá lưu mapping adapter và cùng quy tắc chấm trước khi chạy tiêu chí. Bộ nghiệm thu và browser driver chạy bên ngoài vùng ghi của ứng dụng.

Kiểm tra đường nối thật bằng `python -m unittest -v tests.test_e01_docker` sau khi đặt `KTPM_RUNNER_IMAGE` theo [hướng dẫn I15](../docs/runner-docker.md). Bộ test tạo một commit hỏng trong repo tạm, chạy build Docker và kiểm tra kết quả E01. Kết quả đánh giá các ứng dụng sinh thật cần gắn với từng run E04–E06.
