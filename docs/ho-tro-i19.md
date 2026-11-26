# I19 (Phần hỗ trợ trước) · Bộ theo dõi và áp Quota toàn run

> **Trạng thái:** Đây là **phần hỗ trợ trước (draft/support)** cho [Issue #42 (`I19`)](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/42), **chưa phải bản nghiệm thu cuối**. Issue `#42` vẫn giữ `OPEN` và cần nối với `I04` (LLM adapter), `I06` (Orchestrator) và `I15` (Docker runner) khi các nhánh đó hoàn thành.

## Thành phần đã dựng (trên nền `I02`/`I03`, `D08`, mục `5.3–5.4`)

- `backend/quota.py` (`RunQuotaTracker`, `QuotaLimits`, `PricingSnapshot`, `UsageEntry`, `BudgetExceededError`):
  - Cộng dồn usage của cả 6 vai trò, retry và điều phối vào **một trần ngân sách chung duy nhất** (dùng chung nguyên trạng cho cả `M` và single-agent baseline `S` ở `E02`).
  - Phân biệt `input_tokens`, `output_tokens`, `cached_tokens`; nếu bước nào thiếu usage thì đánh dấu `usage_complete = False` và ghi lại `missing_usage_steps` (không ghi như `0` chính xác).
  - Tách riêng `approval_wait_seconds` khỏi `automated_elapsed_seconds`.
  - Hỗ trợ `max_total_tokens = None` theo cấu hình `D08` (Antigravity CLI `gemini-4-neon-high`), giữ `cost_usd = None` kèm `cost_note` khi không có bảng giá token trực tiếp.
  - Khi vượt ngưỡng, ném `BudgetExceededError(code="budget_exceeded", reason=...)` và `persist(..., transition_on_exceeded=True)` chuyển run sang `needs_human_review` qua `D08` kèm sự kiện `quota.exceeded`.

## Cách chạy kiểm tra

```sh
uv run --frozen python -m unittest tests.test_quota -v
```
