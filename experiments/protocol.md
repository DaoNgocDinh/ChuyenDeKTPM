# E03 · Protocol thực nghiệm, ma trận run và hợp đồng Manifest

Tài liệu khóa phương pháp đo cho `RQ1` (`S` vs `M`), `RQ2` (ảnh hưởng skill) và chuẩn bị thu dữ liệu cho `E04–E08`, bám sát `Ke_hoach_nghien_cuu_he_thong_Multi_Agent.docx` (mục `5.1–5.5`), [đề cương P01](../docs/ke-hoach.md) và cấu hình đã ghi nhận tại `D08`/`R09`.

> **Trạng thái khóa:** Đây là khung protocol `E03` chuẩn bị trước khi hoàn thành `E02` và `I21`. Các tham số vận hành phụ thuộc kết quả 3 run pilot (`infra_retry_limit`, `time_budget_seconds`, `tool_call_limit`, `runner_image_digest`, `system_commit`) được đánh dấu tường minh **`pending_owner_freeze`** và chỉ chốt cố định tại `E04` trước khi chạy 18 run chính (`E05`).

---

## 1. Cấu trúc tập thí nghiệm và thứ tự chạy cố định

Toàn bộ lịch chạy được định nghĩa tường minh trong [run_matrix.json](run_matrix.json):

| Tập (`split`) | Số run | Phạm vi | Quy tắc tách biệt |
| --- | ---: | --- | --- |
| **`pilot`** | 3 | `A1`, `A2`, `A3` (1 lượt mỗi bài cho cấu hình `M`) | Chỉ dùng kiểm tra tính khả thi và chốt hạn mức ở `E04`; **tuyệt đối tách khỏi mẫu số của 18 run chính**. |
| **`main`** | 18 | `3 bài (A1, A2, A3) × 3 lần lặp × 2 cấu hình (S, M)` | Thứ tự **luân phiên cố định `S`, `M`** theo vòng lặp `rep 1 → rep 2 → rep 3` trên trình tự `A1 → A2 → A3` (đã chốt theo xác nhận của chủ dự án, không dùng seed ngẫu nhiên). |
| **`ablation`** | 3 | `A3 × 3 lần lặp × M_no_skill` | Thực nghiệm thăm dò cho `RQ2`, đối chiếu với 3 run `M` có skill của `A3` trong tập `main`; chỉ chạy khi chủ dự án duyệt ngân sách. |

---

## 2. Quy tắc công bằng giữa cấu hình `S` và `M`

1. **Tài nguyên tương đương:** `S` và `M` dùng cùng `model_id` (`gemini-4-neon-high` qua Antigravity CLI theo `D08`/`R09`), cùng tham số suy luận, cùng brief và kịch bản trả lời làm rõ (`D02–D04`), cùng tập tool MCP, cùng Docker runner và **chung một trần ngân sách toàn run** (6 agent của `M` chia chung ngân sách, không nhân sáu).
2. **Quyền của baseline `S`:** Một agent duy nhất đảm nhận toàn bộ pha, được cấp hợp quyền ghi `app/` và `tests_dev/`, vẫn bị cấm truy cập `evaluation/`, policy, skill và DB nền tảng.
3. **Workspace sạch:** Mỗi run bắt đầu trên thư mục `workspaces/{project_id}/{run_id}/` sạch và cùng template khởi đầu; cấm tái sử dụng mã, lịch sử hội thoại hay bug từ run trước.
4. **Cấm sửa mã thủ công để cứu run:** Mọi thao tác can thiệp của con người đều phải ghi vào `manual_edits` và nhật ký; run có `manual_edits > 0` **không bao giờ được tính là thành công tự động**.

---

## 3. Quy tắc đo Usage, Thời gian, Chi phí và Xử lý lỗi

- **Token & `usage_complete`:** Tổng `input_tokens`, `output_tokens`, `cached_tokens` tính gộp mọi agent, retry và bước điều phối trong run. Nếu provider không trả đủ usage, bắt buộc đặt `usage_complete = false` và ghi rõ lý do/phương pháp ước tính ở `usage_note`; không ghi giá trị thiếu như số đo chính xác.
- **Chi phí (`cost_usd` & `cost_note`):** Theo xác nhận của chủ dự án, khi chạy `gemini-4-neon-high` qua Antigravity CLI (`token_limit_app_side = null` theo `D08`), ghi `cost_usd = null` kèm `cost_note` nêu rõ kênh gói CLI thay vì tự bịa đơn giá; nếu về sau chuyển sang API tính tiền theo token thì chụp đơn giá đúng ngày chạy và tính `cost = tổng token từng loại × đơn giá + phí tool` (không suy chi phí từ số message).
- **Thời gian:** Lưu `start_time`, `end_time` (ISO-8601) và tách riêng `approval_wait_seconds` (thời gian chờ con người làm rõ/duyệt) khỏi thời gian máy chạy thực.
- **Retry hạ tầng & giữ run thất bại trong mẫu số:**
  - Ngưỡng `infra_retry_limit`, `time_budget_seconds` và `tool_call_limit` giữ trạng thái `pending_owner_freeze` đến `E04`.
  - Chỉ được loại và chạy lại khi lỗi thuộc sự cố hạ tầng bên ngoài đáp ứng tiêu chí khóa trước (ví dụ provider mất kết nối hoàn toàn), vẫn lưu log lần lỗi và ghi nhận tổng chi phí/usage.
  - **Không bao giờ loại run thất bại** do lỗi mã, lỗi schema hoặc hết ngân sách khỏi mẫu số `18 run` và không cắt giảm số lần lặp sau khi thấy kết quả bất lợi.
- **Thay đổi phiên bản sau khi khóa:** Nếu buộc phải sửa nền tảng, prompt, skill hoặc test độc lập sau mốc `E04`, phải tăng phiên bản, công bố phạm vi ảnh hưởng và chạy lại đồng đều các điều kiện liên quan.

---

## 4. Hợp đồng Manifest (`experiments/manifest.py`)

Mỗi run xuất một tệp manifest JSON chứa đầy đủ 25 trường cốt lõi của mục `5.4` bản Word cùng metadata phân tách tập và chi phí:
- Định danh: `run_id`, `case_id`, `condition`, `repetition`, `split` (`pilot`/`main`/`ablation`).
- Truy vết phiên bản/hash: `system_commit`, `model_id`, `config_hash`, `prompt_hash`, `skill_hash`, `tool_version`.
- Thời gian & usage: `start_time`, `end_time`, `approval_wait_seconds`, `input_tokens`, `output_tokens`, `cached_tokens`, `usage_complete`, `usage_note`, `cost_usd`, `cost_note`.
- Kết quả & bằng chứng: `repair_rounds`, `manual_edits`, `build_ok`, `acceptance_passed`, `acceptance_total` (`10`), `final_status`, `artifact_manifest_uri`, `code_commit`, `runner_report_uri`.

## Kiểm tra nhánh `E03`

```sh
python -m unittest tests.test_e03_protocol -v
```

Bộ kiểm tra xác minh ma trận đủ `3 pilot + 18 main + 3 ablation`, thứ tự luân phiên cố định `S/M`, trạng thái `pending_owner_freeze` cho các ngưỡng chưa khóa, và toàn bộ ràng buộc kiểm tra trường/hash/URI/usage/chi phí/thất bại của manifest.
