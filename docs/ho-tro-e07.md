# E07 (Phần hỗ trợ trước) · Bộ script tính Metric, Rubric và Bảng kết quả

> **Trạng thái:** Đây là **phần hỗ trợ trước (draft/support)** cho [Issue #57 (`E07`)](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/57), **chưa phải bản nghiệm thu cuối**. Issue `#57` vẫn giữ `OPEN` và chỉ nghiệm thu sau khi có dữ liệu thực nghiệm thật của `E05`, `E06` và `V02`. Không chứa số liệu thực nghiệm thật hay số liệu giả.

## Thành phần đã dựng (dựa trên `E03` và bản Word mục `5.3–5.6`)

- `experiments/metrics.py`: tính toàn bộ chỉ số từ danh sách `RunManifest` đã xác thực (hoàn thành tự động `10/10 + build + manual_edits=0`, tiêu chí `/10`, build, trung vị/min/max thời gian tự động và thời gian chờ duyệt, tổng token, danh sách `missing_usage_run_ids`, chi phí gồm run lỗi, tỷ lệ sửa bug có xử lý mẫu số `0` → `"không áp dụng"`). Tách tuyệt đối `pilot`, `main`, `ablation` và gắn `run_ids` truy nguồn cho từng dòng.
- `experiments/rubric.py`: chấm rubric artifact `0/1/2` trên 4 chiều (`requirements`, `design`, `plan`, `test_evidence`), hỗ trợ tạo phiếu ẩn nhãn `S`/`M` (`create_blind_scoring_sheet`) và giải mã lại theo bảng khóa (`unmask_blind_scores`).
- `experiments/tables.py`: lệnh CLI đọc thư mục manifest thô, sinh bảng Markdown tách riêng dòng `S` và `M` theo từng bài đúng mẫu mục `5.6` và xuất CSV.

## Cách chạy kiểm tra

```sh
python -m unittest tests.test_e03_protocol tests.test_e07_metrics -v
```

Khi `E05`/`E06` có dữ liệu manifest thật:

```sh
python -m experiments.tables <thu_muc_manifest_that> <duong_dan_csv_dau_ra>
```
