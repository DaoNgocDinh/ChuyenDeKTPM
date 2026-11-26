# I04 · Gọi Gemini Neon High qua Antigravity

Actor gọi `backend.llm.invoke(prompt, output_schema, tool_schemas=...)` với schema do host cung cấp. Adapter dùng `agy --model gemini-4-neon-high` trong thư mục tạm, nhận JSON, xác thực kiểu và trả đề xuất tool cho host. Caller dùng `ModelReply.persist` để ghi output, usage, hash prompt và cấu hình vào ArtifactStore gắn với run/lease.

CLI dùng phiên đăng nhập hiện tại của người dùng. Adapter chuyển một danh sách biến môi trường phục vụ tiến trình Windows/Linux, bật sandbox, đặt quyền `strict`, từ chối file, web, shell và MCP. Hook `PreToolUse` trong thư mục tạm trả `deny` cho mọi tool. CLI 1.4.12 vẫn liệt kê danh mục tool trong bản tin `init`. Adapter kiểm tra chế độ quyền và loại bước trước khi chấp nhận kết quả. [Quyền CLI](https://antigravity.google/docs/permissions?tab=cli) · [Hook trước khi chạy tool](https://antigravity.google/docs/hooks/) · [Headless JSON](https://antigravity.google/docs/cli/headless/)

Mỗi lần gọi adapter khởi chạy CLI một lần, timeout mặc định 90 giây. Adapter giữ số liệu của chính provider, kể cả các bước sửa JSON bên trong CLI. Trường thiếu được giữ nguyên và `usage_complete` phản ánh việc có cả input/output. Với CLI 1.4.12, trường `response` đôi khi chứa nhiều bản sao của cùng một JSON. Adapter xác thực nội dung, từ chối hai bản khác nhau.

### Test

```powershell
uv sync --frozen
$env:SDLC_LIVE_MODEL = '1'
uv run --frozen python -m unittest -v tests.test_llm
```

Lệnh cần `agy` đã đăng nhập và model có trong `agy models`. Bỏ biến `SDLC_LIVE_MODEL` để chỉ chạy các ca offline. Kết quả 6/6 test đạt. Lượt thật trả tiêu đề “Task Manager Task List”, danh sách tool rỗng, 23.230 input token, 1.022 output token và 24.252 tổng token. Cached/thinking lần lượt là 42.795 và 946 theo cách đếm của CLI. Test đã ghi và đọc lại artifact v1 `275f9219e230414485137e8cb8ba21ae` trong workspace tạm, SHA-256 `00b27fec168ace5bae450ec724e2e514efe1e49515529cfe2d30862228e04e6e`. Đây là phép thử kết nối, nằm ngoài ma trận thực nghiệm E05.
