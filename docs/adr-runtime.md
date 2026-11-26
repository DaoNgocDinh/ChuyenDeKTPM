# R09 · Runtime cho một worker cục bộ

P01 đã duyệt state machine tường minh bằng Python, FastAPI, Pydantic và SQLite. Các bước dừng chờ duyệt, giới hạn sửa, chuyển trạng thái và ghi checkpoint cần có dấu vết ở từng run. Giữ một bộ chuyển trạng thái và một worker giúp đối chiếu mỗi bước với dữ liệu trong SQLite. LangGraph cũng cung cấp điều phối bền và quản lý trạng thái nhưng sẽ thêm một runtime có trách nhiệm trùng với state machine đã chọn. [P01](ke-hoach.md) · [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview)

API xác thực đầu vào bằng Pydantic rồi ghi job bằng transaction ngắn và trả HTTP 202. Một tiến trình worker mở lại cùng cơ sở dữ liệu để nhận việc. Job tồn tại qua vòng đời request, kể cả khi tiến trình API đã dừng. SQLite tuần tự hóa các lần ghi. Khi cần nhiều worker ghi đồng thời trên nhiều máy hoặc khi thời gian chờ khóa thường xuyên vượt tiêu chí vận hành đã duyệt, F03 sẽ đánh giá PostgreSQL và cơ chế claim job tương ứng. [FastAPI Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/) · [SQLite](https://www.sqlite.org/whentouse.html) · [Pydantic](https://docs.pydantic.dev/latest/concepts/models/)

### Kiểm tra

```sh
uv sync --frozen
uv run --frozen python -m unittest -v tests.test_stack_compatibility tests.test_mcp_stdio
```

Ngày 26/11/2026, trên Windows và CPython 3.14.7, cài từ `uv.lock` cho kết quả **2/2 test đạt**. FastAPI 0.165.0 với Pydantic 2.14.4 trả 422 cho brief rỗng, trả 202 cho brief hợp lệ. Sau khi client đóng, worker con nhận đúng job và cập nhật file SQLite 3.50.4. MCP Python SDK 2.3.0 đọc đề cương qua stdio và báo lỗi với mã không tồn tại. [Phép thử MCP](mcp-stdio.md)

Hai test này kiểm chứng stack trên máy phát triển. Queue vận hành với lease, phục hồi theo checkpoint và chính sách quota có tiêu chí nghiệm thu riêng ở I05/I20/I19. Adapter cho model `gemini-4-neon-high` qua Antigravity CLI sẽ được kiểm tra trên I04. Các phiên bản runtime và model dùng cho bộ thực nghiệm chính được duyệt ở E04 sau pilot.
