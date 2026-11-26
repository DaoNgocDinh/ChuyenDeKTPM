# I15 · Build, smoke và kiểm thử theo Git commit

Host tạo `DockerRunner(image_digest, report_root, secrets=...)` rồi gọi `run(repo, commit, suite_id, cancel=...)`. `repo` và `report_root` lấy từ context của run, do host quản lý. Nếu adapter có credential, host cung cấp giá trị để lọc khi đóng gói/ghi log; runner chỉ dùng giá trị này trong tiến trình host. Tên suite là tham số duy nhất do Gateway chuyển từ tool call. `cancel` là `threading.Event` của host.

| Suite | Điều kiện và hành vi |
| --- | --- |
| `build` | Commit chứa mã Python trong `app/` cùng `app/frontend/package-lock.json`. Chạy compileall và npm ci/build trong container, tạo hai testcase JUnit. |
| `smoke` | Chạy `pytest tests_dev/test_smoke.py` và xuất JUnit thật. Ví dụ smoke có thể gọi endpoint của ứng dụng bằng ASGI TestClient. |
| `development` | Chạy toàn bộ `tests_dev/` trên cùng commit. Có ca lỗi, bỏ qua, không thu được report hoặc không có test thì lượt chạy không đạt. |

Mỗi lượt kiểm tra Git commit đầy đủ và chỉ sao chụp tệp đã track thuộc `app/` và `tests_dev/`. Snapshot bỏ qua tệp ẩn và credential thông dụng, từ chối symlink và từ chối dữ liệu khớp credential host đã cung cấp. Docker chỉ thấy bản snapshot chỉ đọc cùng scratch tạm. Profile dùng 2 CPU, 2 GiB, 128 PID, 180 giây, 1 MiB log và bridge Internet. Container chạy với UID/GID không đặc quyền, rootfs chỉ đọc và không có Docker socket. Host buộc dọn container cùng tiến trình con ở mọi đường thoát. Lỗi dọn được ghi riêng.

Kết quả lưu tại `report_root/<report_id>/report.json` cùng log đã lọc và JUnit lược bỏ stdout/stderr của test khi có. Mỗi báo cáo ghi digest image, commit, suite, exit code, số pass/fail/error/skip và thời lượng quan sát từ host. Suite không cung cấp JUnit hợp lệ trả lỗi hạ tầng. Điểm nghiệm thu độc lập thuộc E01.

### Kiểm tra

Chạy `python -m unittest tests.test_docker_runner` tại gốc nhánh. Để thực hiện cả ca Docker thật, bật Linux containers trên daemon cục bộ rồi chạy trong PowerShell:

```powershell
docker build -t ktpm-runner:local backend/runner_image
$env:KTPM_RUNNER_IMAGE = docker image inspect --format '{{.Id}}' ktpm-runner:local
python -m unittest -v tests.test_docker_runner.RunnerTests.test_real_docker_suites_and_cleanup
```

Ca Docker thật tự tạo Git fixture, kiểm tra ba suite đạt, test bị skip, test lỗi, suite không có test, timeout và cancel. Hai lượt cuối kiểm tra container đã dọn. Khi thiếu biến image, unittest ghi rõ `skipped`. Có thể đặt `KTPM_RUNNER_EVIDENCE` thành đường dẫn tệp để xuất bằng chứng JSON kèm log và JUnit. [Bằng chứng của lượt kiểm tra I15](i15-docker.json). Khi chốt protocol ở E04, lưu chính xác image ID hoặc digest đã dùng để tái lập.
